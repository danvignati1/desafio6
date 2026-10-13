# Residencial Aurora: assistente virtual

Assistente de chat para os moradores do Residencial Aurora, construído com Google ADK e exposto por uma API HTTP em `http://localhost:8000`. Pelo chat, o morador reserva o salão de festas, a churrasqueira e a quadra, cancela as próprias reservas, autoriza visitantes e tira dúvidas sobre o regulamento interno.

A ideia central: **o modelo decide o caminho, o código decide o que é permitido.** Nenhuma regra crítica depende do prompt. Todas estão em tools, no banco ou na API, e continuam valendo seja qual for a mensagem do morador.

## Tecnologias

- Python 3.12+ gerenciado por uv (`pyproject.toml` e `uv.lock` versionados)
- Google ADK `2.2.0` (versão exata fixada)
- Gemini via Google AI Studio (`gemini-3.6-flash` por padrão, configurável em `MODELO`)
- FastAPI e Uvicorn
- SQLite: dados do condomínio em `estado/aurora.db`, sessões do ADK em `estado/sessoes.db` (`DatabaseSessionService`, `sqlite+aiosqlite`)

## Arquitetura

```
Morador ──HTTP──> FastAPI (api.py) ──> Runner (ADK, App com retomada ligada)
                                          │
                                   agente principal "aurora"
                          ┌───────────────┼────────────────┐
                    "reservas"      "visitantes"      "regulamento"
                          │               │                 │
                  tools (tools.py) ──> repositorio.py ──> SQLite (aurora.db)
                                                    regulamento.py ──> dados/regulamento.md
```

### Agentes

Os especialistas são `sub_agents` do principal, acionados por transferência (`transfer_to_agent`). Cada um tem só as tools do seu assunto, o que reduz erro de roteamento e limita o estrago de uma decisão errada do modelo.

| Agente | Responsabilidade | Tools | Por que existe |
|---|---|---|---|
| `aurora` (principal) | Entende o pedido e transfere. Responde só cumprimentos. Não recebe o regulamento nas instruções. | nenhuma | Roteamento barato e instruções curtas em toda mensagem. |
| `reservas` | Reservar, consultar agenda, listar e cancelar reservas. | `reservar_area`, `consultar_agenda`, `listar_minhas_reservas`, `cancelar_reserva` | Concentra a regra de cobrança por taxa e a disputa por data. |
| `visitantes` | Autorizar e listar visitantes. | `autorizar_visitante`, `listar_meus_visitantes` | Separa a ação que libera acesso, que sempre exige confirmação. |
| `regulamento` | Responder dúvidas sobre o regulamento. | `consultar_regulamento` | Isola a consulta ao texto longo, que nunca vai para as instruções. |

**Por que transferência e não desligar a transferência entre agentes?** Um spike com o ADK 2.2.0 mostrou que especialistas com `disallow_transfer_to_parent` e `disallow_transfer_to_peers` falham em silêncio: a rota de confirmação aceita a resposta, nenhum erro aparece e a tool não executa. Com a transferência permitida (padrão) e `ResumabilityConfig(is_resumable=True)`, o Runner devolve a confirmação ao agente que a pediu, inclusive depois de reiniciar a API com sessão em SQLite. A API ainda confere que a tool foi retomada e responde `500` se não foi, para nunca aceitar em silêncio.

### Estrutura

| Arquivo | Conteúdo |
|---|---|
| [src/aurora/api.py](src/aurora/api.py) | Rotas, pendências de confirmação, retomada via Runner. |
| [src/aurora/agentes.py](src/aurora/agentes.py) | Agente principal, especialistas e `App`. |
| [src/aurora/tools.py](src/aurora/tools.py) | Tools expostas ao modelo. |
| [src/aurora/repositorio.py](src/aurora/repositorio.py) | Regras de negócio sobre o banco. |
| [src/aurora/db.py](src/aurora/db.py) | Schema, índices, carga dos JSON. |
| [src/aurora/regulamento.py](src/aurora/regulamento.py) | Busca por capítulo no regulamento. |
| [src/aurora/restaurar.py](src/aurora/restaurar.py) | Comando de restauração dos dados. |
| [scripts/](scripts) | Verificações: regras, agentes, regulamento, API com modelo falso e o fluxo do avaliador. |

## Garantias

### 1. Cobrança ou acesso só com confirmação

- **Onde:** [tools.py:119](src/aurora/tools.py) e [tools.py:125](src/aurora/tools.py) registram as tools com `require_confirmation` do ADK. A reserva usa um callable, [`exige_confirmacao_reserva`](src/aurora/tools.py) (tools.py:71), que consulta a taxa da área no banco: taxa maior que zero (ou área desconhecida) pede confirmação, taxa zero não. `autorizar_visitante` sempre pede.
- **Rota:** [`confirmacoes_pendentes`](src/aurora/api.py) (api.py:79) lê os eventos persistidos da sessão e lista os pedidos `adk_request_confirmation` sem resposta. A rota de confirmações responde `409` quando o id não está nessa lista (api.py:155), o que cobre id inexistente e id já respondido. A retomada devolve um `FunctionResponse` ao Runner.
- **Por que não depende do modelo:** a confirmação é um mecanismo do ADK, sem caminho textual. "Já estou confirmando aqui" é só texto na conversa: a tool pausa do mesmo jeito e só a rota de confirmações a libera.

### 2. Cada sessão pertence a um apartamento

- **Onde:** o apartamento é gravado uma vez em `state` por `POST /sessoes` ([api.py](src/aurora/api.py)) e lido por [`_apartamento`](src/aurora/tools.py) (tools.py:24). **Nenhuma tool tem parâmetro de apartamento**; `scripts/verificar_agentes.py` confere o esquema de cada tool.
- **Dados de terceiros:** [`cancelar`](src/aurora/repositorio.py) (repositorio.py:114) filtra pelo `apartamento` da sessão. Reserva de outro apartamento e reserva inexistente dão a mesma resposta, sem código nem dono. [`consultar_agenda`](src/aurora/tools.py) devolve só `livre: true/false`. A recusa de reserva em data ocupada também não cita o dono. Como esses dados nunca entram no resultado das tools, também não chegam aos eventos da sessão.
- **Por que não depende do modelo:** se o morador diz ser do 302, o modelo não tem como mudar o `state`, e as tools só enxergam o apartamento da sessão.

### 3. Nada se perde no reinício

- **Onde:** sessões e eventos em SQLite via `DatabaseSessionService` ([api.py:54](src/aurora/api.py)), com WAL e `busy_timeout`. Reservas e visitantes em `estado/aurora.db`. [`db.inicializar`](src/aurora/db.py) só cria o schema e carrega os JSON se o banco estiver vazio, então reiniciar nunca recarrega nem apaga nada.
- **Pendências:** são derivadas dos eventos persistidos, não de memória. Uma confirmação pedida antes do reinício continua pendente depois dele.
- **Códigos:** vêm de uma sequência `AUTOINCREMENT` iniciada em 10000 ([db.py:10](src/aurora/db.py)), que nunca reaproveita número. Cancelar uma reserva só muda o `status`, então o código nunca volta a ser usado.

### 4. O regulamento é consultado, não carregado

- **Onde:** [`regulamento.buscar`](src/aurora/regulamento.py) (regulamento.py:107) divide o arquivo em capítulos e artigos, pontua com BM25 simples (sem acento, plural, sinônimos, bônus por palavra no título), escolhe **um único capítulo** e devolve no máximo 3 artigos dele (`MAX_ARTIGOS`). Pergunta fora do regulamento não devolve texto.
- **Por que não depende do modelo:** o texto do regulamento não está em instrução nenhuma. O que entra na sessão é o resultado da tool, que por construção nunca mistura capítulos. A pergunta da piscina aos domingos devolve cerca de 1,4 mil caracteres, contra 43 mil do regulamento.

### 5. Dois moradores, uma reserva

- **Onde:** o índice único parcial [`uq_reserva_ativa`](src/aurora/db.py) (db.py:34) em `reservas(area, data) WHERE status = 'ativa'`. [`reservar`](src/aurora/repositorio.py) (repositorio.py:82) **não confere a agenda antes**: o `INSERT` é a conferência, e o banco recusa o perdedor com `IntegrityError`, que vira `{"ok": false, "motivo": "data indisponível"}` (resposta normal, sem erro de servidor). A escrita roda em `BEGIN IMMEDIATE`.
- **Por que vale na gravação:** a exclusividade é do banco, no instante do `INSERT`, e não de uma checagem anterior. Reserva cancelada sai do índice e libera a data.
- **Visitantes:** [`uq_visitante`](src/aurora/db.py) torna a autorização idempotente (mesmo nome e data não duplicam).

## Como rodar

### Pré-requisitos

- Python 3.12 ou superior
- [uv](https://docs.astral.sh/uv/)
- Chave do Google AI Studio com créditos ou cota disponível

### Configuração

```bash
cp .env.example .env
# edite o .env e preencha GOOGLE_API_KEY (e, se quiser, MODELO)
uv sync
```

| Variável | Descrição |
|---|---|
| `GOOGLE_API_KEY` | Chave do Google AI Studio. |
| `MODELO` | Modelo Gemini dos agentes. Vazio usa `gemini-3.6-flash`. |

### Restaurar os dados iniciais

```bash
uv run aurora-restaurar
```

Apaga reservas, visitantes **e as sessões**, e recarrega `dados/*.json`. As sessões são apagadas junto para que nenhuma conversa antiga aponte para reservas ou confirmações que deixaram de existir. Os arquivos de `dados/` nunca são alterados.

### Subir a API

```bash
uv run aurora-api
```

Responde em `http://localhost:8000`. Reiniciar (Ctrl+C e subir de novo) preserva sessões e dados. Não é preciso restaurar antes: a primeira subida já cria o banco com os dados iniciais.

### Exemplo

```bash
curl -s -X POST localhost:8000/sessoes -H 'content-type: application/json' -d '{"apartamento": "101"}'
curl -s -X POST localhost:8000/sessoes/SESSION_ID/mensagens -H 'content-type: application/json' \
  -d '{"texto": "Reserve o salão de festas para 2030-04-20"}'
curl -s -X POST localhost:8000/sessoes/SESSION_ID/confirmacoes -H 'content-type: application/json' \
  -d '{"id": "ID_DA_CONFIRMACAO", "confirmado": true}'
curl -s localhost:8000/apartamentos/101/reservas
```

### Contrato da API

| Rota | Sucesso | Erros |
|---|---|---|
| `POST /sessoes` | `201 {"session_id"}` | `422` apartamento inexistente |
| `POST /sessoes/{id}/mensagens` | `200 {"resposta", "confirmacoes_pendentes"}` | `404` sessão inexistente; `502` falha do modelo |
| `POST /sessoes/{id}/confirmacoes` | `200`, mesmo formato | `404` sessão inexistente; `409` id não pendente |
| `GET /sessoes/{id}/eventos` | `200` todos os eventos, em ordem | `404` sessão inexistente |
| `GET /apartamentos/{n}/reservas` | `200 [{"codigo","area","data"}]` | |
| `GET /apartamentos/{n}/visitantes` | `200 [{"nome","data"}]` | |

### Verificações

Os scripts ficam em `scripts/`. Os quatro primeiros e o `--grupo A` dos adversariais não chamam o Gemini. Todos restauram os dados antes de rodar; não os execute com a API em uso.

```bash
uv run python scripts/verificar_regras.py       # regras das tools e disputa de 24 reservas simultâneas
uv run python scripts/verificar_regulamento.py  # busca por capítulo e isolamento entre capítulos
uv run python scripts/verificar_api.py          # fluxo do avaliador com modelo falso, por HTTP real
uv run python scripts/verificar_confirmacao_multiagente.py  # confirmações de agentes diferentes (reproduz o bug do Runner padrão)
uv run python scripts/fluxo_avaliador.py        # fluxo do avaliador com o Gemini real (consome créditos)
uv run python scripts/teste_usuario.py          # conversa como morador, com o Gemini real
uv run python scripts/testes_adversarios.py     # 22 casos adversariais; --grupo A roda só os que não chamam o Gemini
```

`fluxo_avaliador.py` reproduz os 15 passos: sobe a API, reinicia com Ctrl+C sem restaurar, dispara as duas aprovações concorrentes e confere o repositório. Use `--externo` para subir e reiniciar a API você mesmo.

## Testes e evidências

Todos os testes realizados estão registrados em [docs/TESTES.md](docs/TESTES.md), com o resultado de cada suíte e as falhas que eles encontraram:

| Suíte | Resultado | Evidência |
|---|---|---|
| Regras, agentes, regulamento e fluxo com modelo falso (sem Gemini) | 22 + 14 + 22 + 46 verificações | `scripts/verificar_*.py` |
| Fluxo do avaliador, passos 1 a 15, com o Gemini real | 46/46 | [docs/evidencias/fluxo_avaliador.md](docs/evidencias/fluxo_avaliador.md) |
| Teste como morador, em linguagem natural | sem violação de regra | [docs/evidencias/teste_usuario.md](docs/evidencias/teste_usuario.md) |
| Testes adversariais (22 casos: injeção de prompt, confirmação forjada, disputa de 12 sessões, `kill -9`, entradas hostis) | 22/22 | [docs/evidencias/testes_adversarios.md](docs/evidencias/testes_adversarios.md) |

Os testes adversariais acharam um bug real, corrigido em [runner.py](src/aurora/runner.py): confirmação pendente de um agente aprovada depois que a conversa seguiu para outro. A rodada anterior à correção (21/22) está preservada em [docs/evidencias/testes_adversarios_rodada_1_com_falha.md](docs/evidencias/testes_adversarios_rodada_1_com_falha.md).

## Decisões e limites

- **Apartamento inexistente** na criação da sessão devolve `422`. Nas rotas de verificação, devolve lista vazia.
- **Nova mensagem com confirmação pendente** é aceita. A pendência continua listada e nada executa sem a rota de confirmações.
- **Falha silenciosa da retomada:** a API responde `500` se a confirmação for aceita mas a tool não for retomada.
- **Concorrência:** a exclusividade vale entre threads e processos, porque é do arquivo SQLite. Em um banco com várias instâncias da API, o mesmo índice único seria a garantia.
- Fora de escopo, conforme o enunciado: interface, autenticação, pagamento e estorno, antecedência e horários, testes automatizados formais e deploy.
