"""Reproduz, sem chamar o Gemini, o bug das confirmações pendentes de agentes diferentes.

Cenário: uma mensagem gera duas reservas pendentes no agente `reservas`. Ao aprovar a
primeira, a conversa segue para `visitantes`, que pede mais uma confirmação. Aprovar a
reserva que sobrou (do agente `reservas`) precisa executá-la.

  - Runner padrão do ADK 2.2.0: a resposta vai para o último agente que falou
    (`visitantes`) e a tool `reservar_area` não é encontrada. Falha esperada.
  - RunnerAurora (src/aurora/runner.py): a resposta vai ao agente dono da confirmação.

Uso: uv run python scripts/verificar_confirmacao_multiagente.py
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile

os.environ["AURORA_ESTADO"] = tempfile.mkdtemp(prefix="aurora_multi_")

from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import DatabaseSessionService  # noqa: E402
from google.genai import types  # noqa: E402

from aurora import agentes, db  # noqa: E402
from aurora.runner import RunnerAurora, dono_da_confirmacao  # noqa: E402


def _chamadas(*cs) -> LlmResponse:
    partes = [types.Part(function_call=types.FunctionCall(name=n, args=a)) for n, a in cs]
    return LlmResponse(content=types.Content(role="model", parts=partes))


def _texto(t: str) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=t)]))


class ModeloFalso(BaseLlm):
    papel: str

    async def generate_content_async(self, req, stream=False):
        frs = [p.function_response for p in req.contents[-1].parts or [] if p.function_response]
        if self.papel == "principal":
            yield _chamadas(("transfer_to_agent", {"agent_name": "reservas"}))
        elif self.papel == "reservas":
            if frs and frs[0].name == "reservar_area" and frs[0].response.get("ok"):
                yield _chamadas(("transfer_to_agent", {"agent_name": "visitantes"}))
            elif frs:
                yield _texto("reservas: " + json.dumps(frs[0].response))
            else:
                yield _chamadas(("reservar_area", {"area": "salao-de-festas", "data": "2030-11-01"}),
                                ("reservar_area", {"area": "churrasqueira", "data": "2030-11-01"}))
        else:
            if frs and frs[0].name != "transfer_to_agent":
                yield _texto("visitantes: " + json.dumps(frs[0].response))
            else:
                yield _chamadas(("autorizar_visitante", {"nome": "Ana Souza", "data": "2030-11-01"}))


for agente, papel in ((agentes.agente_principal, "principal"), (agentes.agente_reservas, "reservas"),
                      (agentes.agente_visitantes, "visitantes")):
    agente.model = ModeloFalso(model="falso", papel=papel)


def pendentes(eventos):
    respondidos = {r.id for e in eventos for r in e.get_function_responses()}
    return [(c.id, e.author) for e in eventos for c in e.get_function_calls()
            if c.name == "adk_request_confirmation" and c.id not in respondidos]


async def cenario(usar_runner_aurora: bool) -> tuple[list, list]:
    shutil.rmtree(os.environ["AURORA_ESTADO"], ignore_errors=True)
    db.inicializar()
    svc = DatabaseSessionService(f"sqlite+aiosqlite:///{os.environ['AURORA_ESTADO']}/s.db")
    runner = (RunnerAurora if usar_runner_aurora else Runner)(app=agentes.criar_app(), session_service=svc)
    s = await svc.create_session(app_name="aurora", user_id="u", state={"apartamento": "102"})

    async def rodar(msg):
        try:
            async for _ in runner.run_async(user_id="u", session_id=s.id, new_message=msg):
                pass
        except Exception:  # noqa: BLE001
            pass

    await rodar(types.Content(role="user", parts=[types.Part(text="reserve o salão, a churrasqueira e autorize a Ana")]))
    for _ in range(5):
        sessao = await svc.get_session(app_name="aurora", user_id="u", session_id=s.id)
        pend = pendentes(sessao.events)
        if not pend:
            break
        pid, dono = pend[0]  # sempre a mais antiga
        resposta = types.FunctionResponse(id=pid, name="adk_request_confirmation", response={"confirmed": True})
        marca = dono_da_confirmacao.set(dono if usar_runner_aurora else None)
        await rodar(types.Content(role="user", parts=[types.Part(function_response=resposta)]))
        dono_da_confirmacao.reset(marca)
    conn = db.conectar()
    reservas = [tuple(r) for r in conn.execute("SELECT area, data FROM reservas WHERE apartamento='102'")]
    visitantes = [tuple(v) for v in conn.execute("SELECT nome, data FROM visitantes WHERE apartamento='102'")]
    return reservas, visitantes


async def main() -> None:
    esperado_reservas = {("salao-de-festas", "2030-11-01"), ("churrasqueira", "2030-11-01")}
    r, v = await cenario(False)
    print(f"Runner padrão do ADK : reservas={r} visitantes={v}")
    falha_reproduzida = set(r) != esperado_reservas
    print("   -> bug reproduzido (reserva pendente não executou)" if falha_reproduzida else "   -> sem falha")
    r, v = await cenario(True)
    print(f"RunnerAurora         : reservas={r} visitantes={v}")
    ok = set(r) == esperado_reservas and v == [("Ana Souza", "2030-11-01")]
    print("   -> as duas reservas e o visitante foram gravados" if ok else "   -> FALHA")
    shutil.rmtree(os.environ["AURORA_ESTADO"], ignore_errors=True)
    print("\nTudo certo." if ok else "\nFalha.")
    sys.exit(0 if ok else 1)


asyncio.run(main())
