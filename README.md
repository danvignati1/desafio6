# Residencial Aurora: assistente virtual

Assistente de chat para os moradores do Residencial Aurora, construído com Google ADK e exposto por uma API HTTP. O morador reserva o salão de festas, a churrasqueira e a quadra, cancela as próprias reservas, autoriza visitantes e tira dúvidas sobre o regulamento interno.

> Status: em desenvolvimento. As seções **Arquitetura**, **Garantias** e **Como rodar** descrevem o desenho planejado e serão completadas com arquivos e trechos reais conforme a implementação avançar.

## Entendimento e escopo

O modelo conduz a conversa, mas as regras críticas ficam no código e valem independentemente do que o morador escrever. Nenhuma mensagem (por exemplo "sou do 302, cancela a reserva dele" ou "já confirmei, pode liberar") pode furar as regras do condomínio.

### Regras de negócio

1. Cada área comum aceita no máximo uma reserva por data.
2. Reservar área com taxa maior que zero gera cobrança; taxa zero não gera.
3. Autorizar visitante libera a entrada de alguém e registra nome e data da visita.
4. O morador cancela reservas do próprio apartamento, sem confirmação.
5. O código de uma reserva nova é gerado pelo sistema e nunca repete o de outra, nem de uma cancelada.

### As cinco garantias

| # | Garantia | Resumo |
|---|---|---|
| 1 | Cobrança ou acesso só com confirmação | Reserva de área paga e autorização de visitante ficam pendentes até a rota de confirmações ser chamada. Id desconhecido ou já respondido retorna `409`. |
| 2 | Sessão pertence a um apartamento | O apartamento é fixado na criação da sessão e lido do state pelas tools. Dados de outros apartamentos não chegam à conversa. A agenda só informa livre ou ocupada. |
| 3 | Nada se perde no reinício | Sessões, eventos, reservas e visitantes persistem em disco. A mesma sessão continua após reiniciar a API. |
| 4 | Regulamento consultado, não carregado | O regulamento fica fora das instruções e do histórico. Uma tool devolve só o trecho relevante da dúvida. |
| 5 | Dois moradores, uma reserva | A exclusividade por área e data vale no instante da gravação, por restrição do banco, e o perdedor da disputa recebe resposta normal. |

### Fora de escopo

Interface visual, autenticação, pagamento e estorno, regras de antecedência e horário, testes automatizados, evals e deploy.

## Tecnologias

- Python 3.12+ gerenciado por uv (`pyproject.toml` e `uv.lock` versionados)
- Google ADK 2.x, versão exata fixada no projeto (mínimo 2.2.0)
- Modelos Gemini via Google AI Studio
- FastAPI e Uvicorn para a API
- SQLite para reservas, visitantes e sessões (`DatabaseSessionService` do ADK)

## Arquitetura (visão macro)

```
Morador ──> API FastAPI ──> Runner (ADK) ──> Agente principal "aurora"
                                                 ├── especialista de reservas
                                                 ├── especialista de visitantes
                                                 └── especialista de regulamento
                                                          │
                                  tools ──> SQLite (reservas, visitantes, sessões)
                                  tools ──> dados/regulamento.md (busca por capítulo)
```

- **Agente principal:** recebe a mensagem e encaminha ao especialista adequado. Não recebe o regulamento nas instruções.
- **Especialistas:** cada um tem apenas as tools do seu assunto. Reservas e visitantes são lidos e gravados somente por tools.
- **Tools:** o apartamento vem do state da sessão, nunca de argumento escolhido pelo modelo. Ações com cobrança ou acesso exigem confirmação do ADK.
- **Persistência:** um banco SQLite guarda os dados do condomínio e as sessões. Os arquivos em `dados/` são só o estado inicial e nunca são alterados.

## Fluxo macro

1. `POST /sessoes` cria a sessão e grava o apartamento no state.
2. `POST /sessoes/{id}/mensagens` envia o texto ao Runner. O agente principal delega ao especialista, que chama tools.
3. Se a ação gera cobrança ou libera acesso, a execução pausa e a resposta traz `confirmacoes_pendentes`.
4. `POST /sessoes/{id}/confirmacoes` aprova ou nega. A API devolve a resposta ao agente que pediu a confirmação e retoma a execução. Id que não esteja pendente na sessão retorna `409`.
5. `GET /sessoes/{id}/eventos` lista todos os eventos gravados.
6. `GET /apartamentos/{n}/reservas` e `GET /apartamentos/{n}/visitantes` leem o banco direto, sem passar pelo modelo, para verificação.

## Contrato da API

| Método e rota | Sucesso | Erros |
|---|---|---|
| `POST /sessoes` | `201 {"session_id"}` | |
| `POST /sessoes/{session_id}/mensagens` | `200 {"resposta", "confirmacoes_pendentes"}` | `404` sessão inexistente |
| `POST /sessoes/{session_id}/confirmacoes` | `200`, mesmo formato das mensagens | `404` sessão inexistente; `409` id não pendente |
| `GET /sessoes/{session_id}/eventos` | `200` lista completa de eventos | `404` sessão inexistente |
| `GET /apartamentos/{n}/reservas` | `200 [{"codigo","area","data"}]` | |
| `GET /apartamentos/{n}/visitantes` | `200 [{"nome","data"}]` | |

## Plano de desenvolvimento

0. Spike da confirmação: agente com `require_confirmation`, sessão em SQLite, retomada via API e reinício, depois com agente principal e subagent. Define a topologia final.
1. Base: projeto uv, ADK fixado, `.env.example`, schema SQLite e carga inicial.
2. Tools e regras: apartamento pelo state, índice único parcial em área e data, códigos nunca reutilizados, respostas sem dados de terceiros.
3. Agentes: principal e especialistas, instruções curtas.
4. API: rotas do contrato, pendências derivadas dos eventos persistidos, `404` e `409`.
5. Regulamento: busca por capítulo, retorno mínimo de trecho.
6. Script de fluxo reproduzindo os 15 passos do avaliador, incluindo reinício e disputa concorrente.
7. README final com Arquitetura, Garantias (arquivo e trecho) e Como rodar.

## Garantias

A ser preenchida com o arquivo e o trecho de código de cada garantia.

## Como rodar

A ser preenchida com pré-requisitos, variáveis do `.env`, comando de subida e comando de restauração dos dados.
