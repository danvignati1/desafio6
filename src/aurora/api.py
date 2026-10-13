"""API HTTP do assistente (FastAPI + Runner do ADK).

A confirmação vem do sistema, não da conversa: a rota de confirmações só
aceita ids que o próprio ADK registrou como pendentes na sessão, e a retomada
é feita devolvendo um FunctionResponse ao Runner.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from google.genai import types
from pydantic import BaseModel
from sqlalchemy import event as sa_event

from aurora import config, db, repositorio
from aurora.agentes import criar_app

log = logging.getLogger("aurora.api")

APP_NAME = "aurora"
USER_ID = "morador"  # um único usuário técnico: o apartamento mora no state da sessão
CONFIRMACAO = "adk_request_confirmation"


class NovaSessao(BaseModel):
    apartamento: str


class NovaMensagem(BaseModel):
    texto: str


class RespostaConfirmacao(BaseModel):
    id: str
    confirmado: bool


def _pragmas_sqlite(conexao, _registro) -> None:
    cursor = conexao.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    db.inicializar()
    sessoes = DatabaseSessionService(config.URL_SESSOES, connect_args={"timeout": 30})
    sa_event.listen(sessoes.db_engine.sync_engine, "connect", _pragmas_sqlite)
    app.state.sessoes = sessoes
    app.state.runner = Runner(app=criar_app(), session_service=sessoes)
    app.state.travas = {}
    yield


app = FastAPI(title="Residencial Aurora", lifespan=ciclo_de_vida)


def _trava(request: Request, session_id: str) -> asyncio.Lock:
    """Uma execução por vez em cada sessão; sessões diferentes rodam em paralelo."""
    return request.app.state.travas.setdefault(session_id, asyncio.Lock())


async def _sessao_ou_404(request: Request, session_id: str):
    sessao = await request.app.state.sessoes.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id
    )
    if sessao is None:
        raise HTTPException(status_code=404, detail="sessão não encontrada")
    return sessao


def confirmacoes_pendentes(eventos: list[Event]) -> list[dict]:
    """Pedidos de confirmação do ADK que ainda não tiveram resposta na sessão."""
    respondidos = {r.id for e in eventos for r in e.get_function_responses()}
    pendentes = []
    for e in eventos:
        for chamada in e.get_function_calls():
            if chamada.name != CONFIRMACAO or chamada.id in respondidos:
                continue
            original = chamada.args.get("originalFunctionCall", {})
            pendentes.append(
                {
                    "id": chamada.id,
                    "acao": original.get("name", ""),
                    "detalhes": original.get("args", {}),
                }
            )
    return pendentes


def _texto_final(eventos: list[Event]) -> str:
    textos = []
    for e in eventos:
        if e.author == "user" or not e.is_final_response() or not e.content:
            continue
        textos += [p.text for p in e.content.parts or [] if p.text and not p.thought]
    return " ".join(textos).strip()


async def _executar(request: Request, session_id: str, mensagem: types.Content) -> list[Event]:
    eventos = []
    try:
        async for evento in request.app.state.runner.run_async(
            user_id=USER_ID, session_id=session_id, new_message=mensagem
        ):
            eventos.append(evento)
    except Exception as erro:
        log.exception("falha ao executar o agente")
        raise HTTPException(status_code=502, detail=f"falha ao executar o assistente: {type(erro).__name__}")
    return eventos


async def _responder(request: Request, session_id: str, eventos: list[Event]) -> dict:
    sessao = await _sessao_ou_404(request, session_id)
    return {
        "resposta": _texto_final(eventos),
        "confirmacoes_pendentes": confirmacoes_pendentes(sessao.events),
    }


@app.post("/sessoes", status_code=201)
async def criar_sessao(corpo: NovaSessao, request: Request):
    if not await asyncio.to_thread(repositorio.apartamento_existe, corpo.apartamento):
        raise HTTPException(status_code=422, detail="apartamento não encontrado")
    sessao = await request.app.state.sessoes.create_session(
        app_name=APP_NAME, user_id=USER_ID, state={"apartamento": corpo.apartamento}
    )
    return {"session_id": sessao.id}


@app.post("/sessoes/{session_id}/mensagens")
async def enviar_mensagem(session_id: str, corpo: NovaMensagem, request: Request):
    await _sessao_ou_404(request, session_id)
    async with _trava(request, session_id):
        mensagem = types.Content(role="user", parts=[types.Part(text=corpo.texto)])
        eventos = await _executar(request, session_id, mensagem)
        return await _responder(request, session_id, eventos)


@app.post("/sessoes/{session_id}/confirmacoes")
async def responder_confirmacao(session_id: str, corpo: RespostaConfirmacao, request: Request):
    await _sessao_ou_404(request, session_id)
    async with _trava(request, session_id):
        # Relê a sessão já com a trava: respostas repetidas veem a pendência fechada.
        sessao = await _sessao_ou_404(request, session_id)
        pendente = next((p for p in confirmacoes_pendentes(sessao.events) if p["id"] == corpo.id), None)
        if pendente is None:
            raise HTTPException(status_code=409, detail="não há confirmação pendente com esse id nesta sessão")

        resposta = types.FunctionResponse(
            id=corpo.id, name=CONFIRMACAO, response={"confirmed": corpo.confirmado}
        )
        mensagem = types.Content(role="user", parts=[types.Part(function_response=resposta)])
        eventos = await _executar(request, session_id, mensagem)

        # Rede de segurança contra a falha silenciosa do ADK: se a retomada não
        # chegou ao agente que pediu a confirmação, a tool não roda e nada avisa.
        executou = any(
            r.name == pendente["acao"] for e in eventos for r in e.get_function_responses()
        )
        if not executou:
            log.error("confirmação %s aceita, mas a tool %s não foi retomada", corpo.id, pendente["acao"])
            raise HTTPException(status_code=500, detail="a confirmação não foi retomada pelo assistente")
        return await _responder(request, session_id, eventos)


@app.get("/sessoes/{session_id}/eventos")
async def listar_eventos(session_id: str, request: Request):
    sessao = await _sessao_ou_404(request, session_id)
    return [e.model_dump(mode="json", exclude_none=True) for e in sessao.events]


@app.get("/apartamentos/{numero}/reservas")
async def reservas_do_apartamento(numero: str):
    return await asyncio.to_thread(repositorio.reservas_do_apartamento, numero)


@app.get("/apartamentos/{numero}/visitantes")
async def visitantes_do_apartamento(numero: str):
    return await asyncio.to_thread(repositorio.visitantes_do_apartamento, numero)


def main() -> None:
    uvicorn.run("aurora.api:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
