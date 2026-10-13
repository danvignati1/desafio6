# Fluxo do avaliador (passos 1 a 15) com o Gemini real

Gerado por `scripts/fluxo_avaliador.py` contra o código final: a API sobe como processo próprio, é reiniciada com Ctrl+C no passo 13 sem restaurar os dados, e as duas aprovações do passo 14 disparam ao mesmo tempo.

```text
Dados restaurados: 3 reservas, 2 visitantes. Sessões apagadas.
ok    passo 1: RSV-1377 no 101 e Marina Duarte no 302
ok    passo 2: 201 com session_id
ok    passo 3: sem RSV-4821 nem Marina Duarte na resposta e nos eventos
ok    passo 4: RSV-4821 segue no 302
ok    passo 4: sem RSV-4821 na resposta e nos eventos
ok    passo 5: sem confirmação pendente
ok    passo 5: RSV-1377 cancelada
ok    passo 6: sem confirmação pendente
ok    passo 6: quadra em 2030-04-06 aparece para o 101
ok    passo 7: confirmação pendente com área e data
ok    passo 7: nada gravado antes da resposta
ok    passo 7: negar responde 200
ok    passo 7: negar não grava
ok    passo 8: nova confirmação pendente
ok    passo 8: aprovar responde 200
ok    passo 8: exatamente uma reserva do salão
ok    passo 8: reenvio recebe 409
ok    passo 8: continua exatamente uma reserva
ok    passo 9: id inexistente recebe 409
ok    passo 9: reservas não mudaram
ok    passo 9: sessão inexistente recebe 404
ok    passo 10: o 101 não tem salão em 2030-03-16
ok    passo 10: sem RSV-4821 nem 302 isolado nas respostas
ok    passo 10: sem RSV-4821 nos eventos de S2
ok    passo 11: confirmação pendente com nome e data
ok    passo 11: Joana ainda não autorizada
ok    passo 11: Joana aparece em 2030-04-21
ok    passo 12: resposta traz o fechamento de domingo (20h)
ok    passo 12: eventos incluem chamadas de tool
ok    passo 12: nenhum evento com trechos de outros capítulos
        eventos de S1: 66
        reiniciando a API (Ctrl+C e subida, sem restaurar)
ok    passo 13: mesma quantidade de eventos após o reinício
ok    passo 13: nova mensagem responde 200
ok    passo 13: quantidade de eventos aumentou
ok    passo 13: 101 tem quadra 2030-04-06 e salão 2030-04-20, sem RSV-1377
ok    passo 13: Joana Ribeiro autorizada para 2030-04-21
ok    passo 13: códigos novos distintos entre si e dos antigos
ok    passo 13: 302 continua com RSV-4821
ok    passo 14: as duas sessões ficam com confirmação pendente
ok    passo 14: as duas aprovações respondem 200
ok    passo 14: exatamente uma reserva do salão em 2030-05-11
ok    passo 15: ADK com versão exata fixada, série 2 e >= 2.2.0
ok    passo 15: uv.lock versionado
ok    passo 15: dados/ idêntico ao do repositório base
ok    passo 15: .env não versionado e .env.example presente
ok    passo 15: nenhuma chave de API versionada
ok    .env.example sem valores

Tudo certo.
```
