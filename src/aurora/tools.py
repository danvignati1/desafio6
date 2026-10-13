"""Tools expostas aos agentes.

Nenhuma tool recebe apartamento como parâmetro: o apartamento vem sempre de
`tool_context.state["apartamento"]`, gravado uma única vez na criação da sessão.
O modelo não tem como escolher nem trocar o apartamento, qualquer que seja a
mensagem do morador. Falhas voltam como dict, nunca como exceção.
"""

import asyncio
import json
import sqlite3
from typing import Literal

from google.adk.tools import FunctionTool, ToolContext

from aurora import config, regulamento, repositorio

# Enum de áreas derivado de dados/areas.json: o modelo só consegue chamar com um id válido.
# Lê o arquivo, não o banco, para que importar este módulo funcione antes de o banco existir.
AreaId = Literal[tuple(a["id"] for a in json.loads((config.DIR_DADOS / "areas.json").read_text(encoding="utf-8")))]

_SEM_SESSAO = {"ok": False, "motivo": "sessão sem apartamento definido"}
_OCUPADO = {"ok": False, "motivo": "sistema ocupado, tente novamente em instantes"}


def _apartamento(tool_context: ToolContext) -> str | None:
    apartamento = tool_context.state.get("apartamento")
    return apartamento if isinstance(apartamento, str) and apartamento else None


async def _em_thread(funcao, *args, **kwargs) -> dict:
    """Roda o acesso ao SQLite fora do event loop e converte falha de banco em resposta."""
    try:
        return await asyncio.to_thread(funcao, *args, **kwargs)
    except sqlite3.OperationalError:
        return _OCUPADO


async def consultar_agenda(area: AreaId, data: str, tool_context: ToolContext) -> dict:
    """Informa se uma área comum está livre em uma data (AAAA-MM-DD).

    Devolve apenas livre ou ocupada. Nunca informa de quem é uma reserva.
    """
    if not repositorio.data_valida(data):
        return {"ok": False, "motivo": "data inválida, use AAAA-MM-DD"}
    if area not in repositorio.ids_das_areas():
        return {"ok": False, "motivo": "área inexistente"}
    livre = await asyncio.to_thread(repositorio.data_livre, area, data)
    return {"ok": True, "area": area, "data": data, "livre": livre}


async def listar_minhas_reservas(tool_context: ToolContext) -> dict:
    """Lista as reservas ativas do apartamento do morador."""
    apartamento = _apartamento(tool_context)
    if not apartamento:
        return _SEM_SESSAO
    reservas = await asyncio.to_thread(repositorio.reservas_do_apartamento, apartamento)
    return {"ok": True, "reservas": reservas}


async def reservar_area(area: AreaId, data: str, tool_context: ToolContext) -> dict:
    """Reserva uma área comum para o apartamento do morador em uma data (AAAA-MM-DD).

    Áreas com taxa geram cobrança e exigem confirmação do morador antes de gravar.
    Se a data já estiver ocupada, a reserva é recusada.
    """
    apartamento = _apartamento(tool_context)
    if not apartamento:
        return _SEM_SESSAO
    return await _em_thread(repositorio.reservar, apartamento, area, data)


def exige_confirmacao_reserva(area: str, data: str = "", tool_context=None) -> bool:
    """Decide em código se a reserva gera cobrança. Área desconhecida pede confirmação."""
    taxa = repositorio.taxa_da_area(area)
    return taxa is None or taxa > 0


async def cancelar_reserva(
    tool_context: ToolContext,
    codigo: str | None = None,
    area: AreaId | None = None,
    data: str | None = None,
) -> dict:
    """Cancela uma reserva do apartamento do morador, sem pedir confirmação.

    Informe o código da reserva, ou a área e a data. Só cancela reservas do
    próprio apartamento.
    """
    apartamento = _apartamento(tool_context)
    if not apartamento:
        return _SEM_SESSAO
    return await _em_thread(
        repositorio.cancelar, apartamento, codigo=codigo, area=area, data=data
    )


async def listar_meus_visitantes(tool_context: ToolContext) -> dict:
    """Lista os visitantes autorizados do apartamento do morador."""
    apartamento = _apartamento(tool_context)
    if not apartamento:
        return _SEM_SESSAO
    visitantes = await asyncio.to_thread(repositorio.visitantes_do_apartamento, apartamento)
    return {"ok": True, "visitantes": visitantes}


async def autorizar_visitante(nome: str, data: str, tool_context: ToolContext) -> dict:
    """Autoriza a entrada de um visitante no prédio em uma data (AAAA-MM-DD).

    Libera acesso ao prédio, por isso exige confirmação do morador antes de gravar.
    """
    apartamento = _apartamento(tool_context)
    if not apartamento:
        return _SEM_SESSAO
    return await _em_thread(repositorio.autorizar_visitante, apartamento, nome, data)


FERRAMENTAS_RESERVAS = [
    consultar_agenda,
    listar_minhas_reservas,
    FunctionTool(reservar_area, require_confirmation=exige_confirmacao_reserva),
    cancelar_reserva,
]

FERRAMENTAS_VISITANTES = [
    listar_meus_visitantes,
    FunctionTool(autorizar_visitante, require_confirmation=True),
]


async def consultar_regulamento(pergunta: str, tool_context: ToolContext) -> dict:
    """Consulta o regulamento interno e devolve só os artigos pertinentes à pergunta.

    Faça uma consulta por assunto. Responda apenas com base no que a tool devolver,
    citando o artigo. Se a tool não encontrar, diga que o regulamento não trata disso.
    """
    return await asyncio.to_thread(regulamento.buscar, pergunta)


FERRAMENTAS_REGULAMENTO = [consultar_regulamento]
