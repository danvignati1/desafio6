"""Exercita o fluxo do avaliador (scripts/fluxo_avaliador.py) com um modelo falso, sem chamar o Gemini.

O modelo falso decide o caminho por palavras-chave. Tudo que importa para as
garantias (tools, banco, confirmação, sessão persistida, reinício, disputa)
roda de verdade, por HTTP real em localhost.

Uso: uv run python scripts/verificar_api.py
"""

import asyncio
import json
import re
import sys
from pathlib import Path

import httpx
import uvicorn
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from aurora import agentes, config, restaurar
from aurora.api import app

BASE = "http://127.0.0.1:8765"
sys.path.insert(0, str(Path(__file__).parent))
import fluxo_avaliador  # noqa: E402
def _chamada(_funcao: str, /, **args) -> LlmResponse:
    parte = types.Part(function_call=types.FunctionCall(name=_funcao, args=args))
    return LlmResponse(content=types.Content(role="model", parts=[parte]))


def _texto(texto: str) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=texto)]))


class ModeloFalso(BaseLlm):
    papel: str

    async def generate_content_async(self, llm_request, stream=False):
        ultimo = llm_request.contents[-1]
        respostas = [p.function_response for p in ultimo.parts or [] if p.function_response]
        if respostas and respostas[0].name != "transfer_to_agent":
            yield _texto("Resultado: " + json.dumps(respostas[0].response, ensure_ascii=False))
            return
        usuario = next(
            (p.text for c in reversed(llm_request.contents) if c.role == "user"
             and not (c.parts and c.parts[0].text == "For context:")
             for p in c.parts or [] if p.text),
            "",
        ).lower()
        visitante = bool(re.search(r"visitante|libera|autoriz|entrada", usuario))
        regra = bool(re.search(r"piscina|regulamento|funciona", usuario))
        if self.papel == "principal":
            yield _chamada("transfer_to_agent", agent_name="regulamento" if regra else "visitantes" if visitante else "reservas")
        elif self.papel == "regulamento":
            if not regra:
                yield _chamada("transfer_to_agent", agent_name="visitantes" if visitante else "reservas")
            else:
                yield _chamada("consultar_regulamento", pergunta=usuario)
        elif self.papel == "reservas":
            if visitante or regra:
                yield _chamada("transfer_to_agent", agent_name="regulamento" if regra else "visitantes")
                return
            area = ("quadra" if "quadra" in usuario else
                    "churrasqueira" if "churrasqueira" in usuario else "salao-de-festas")
            data = (re.search(r"\d{4}-\d{2}-\d{2}", usuario) or [None])[0]
            if "cancel" in usuario:
                yield _chamada("cancelar_reserva", area=area, data=data)
            elif "reserv" in usuario and "quais" not in usuario:
                yield _chamada("reservar_area", area=area, data=data)
            else:
                yield _chamada("listar_minhas_reservas")
        else:
            if regra or not visitante:
                yield _chamada("transfer_to_agent", agent_name="regulamento" if regra else "reservas")
                return
            nome = re.search(r"\bda ([a-zà-ú]+ [a-zà-ú]+)", usuario)
            data = re.search(r"\d{4}-\d{2}-\d{2}", usuario)
            if nome and data:
                yield _chamada("autorizar_visitante", nome=nome[1].title(), data=data[0])
            else:
                yield _chamada("listar_meus_visitantes")


for agente, papel in ((agentes.agente_principal, "principal"),
                      (agentes.agente_reservas, "reservas"),
                      (agentes.agente_visitantes, "visitantes"),
                      (agentes.agente_regulamento, "regulamento")):
    agente.model = ModeloFalso(model="falso", papel=papel)


class Servidor:
    async def __aenter__(self):
        self.servidor = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8765, log_level="warning"))
        self.tarefa = asyncio.create_task(self.servidor.serve())
        while not self.servidor.started:
            await asyncio.sleep(0.05)
        return self

    async def __aexit__(self, *_):
        self.servidor.should_exit = True
        await self.tarefa


async def main() -> None:
    restaurar.main()
    servidor = Servidor()
    await servidor.__aenter__()

    async def reiniciar() -> None:
        nonlocal servidor
        await servidor.__aexit__()
        servidor = Servidor()
        await servidor.__aenter__()

    try:
        await fluxo_avaliador.fluxo(BASE, reiniciar)
    finally:
        await servidor.__aexit__()
    fluxo_avaliador.passo_15()
    falhas = fluxo_avaliador.falhas
    print("\nTudo certo." if not falhas else f"\n{len(falhas)} falha(s):\n- " + "\n- ".join(falhas))
    raise SystemExit(1 if falhas else 0)


asyncio.run(main())
