"""Runner que devolve cada confirmação ao agente que a pediu.

No ADK 2.2.0, `Runner._find_agent_to_run` escolhe o agente de uma nova execução
olhando só os eventos já gravados, antes de a resposta do morador entrar na
sessão. Na prática, a resposta vai para o último agente que falou. Se uma
confirmação do agente `reservas` ficou pendente e a conversa seguiu para
`visitantes`, a resposta chega ao agente errado e a tool não é encontrada.

Aqui o dono da confirmação é informado por uma ContextVar (isolada por requisição)
e usado na escolha do agente. Sem ela, o comportamento do ADK é mantido.
"""

from contextvars import ContextVar

from google.adk.runners import Runner

dono_da_confirmacao: ContextVar[str | None] = ContextVar("dono_da_confirmacao", default=None)


class RunnerAurora(Runner):
    def _find_agent_to_run(self, session, root_agent):
        nome = dono_da_confirmacao.get()
        if nome and (dono := root_agent.find_agent(nome)) is not None:
            return dono
        return super()._find_agent_to_run(session, root_agent)
