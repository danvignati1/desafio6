"""Verifica as regras de negócio direto nas tools, sem modelo e sem API.

Uso: uv run python scripts/verificar_regras.py
Restaura o estado inicial antes de rodar.
"""

import asyncio
import json
from types import SimpleNamespace

from aurora import restaurar, tools

falhas = 0


def conferir(descricao: str, condicao: bool) -> None:
    global falhas
    print(("ok    " if condicao else "FALHA ") + descricao)
    falhas += 0 if condicao else 1


def ctx(apartamento: str | None) -> SimpleNamespace:
    return SimpleNamespace(state={"apartamento": apartamento} if apartamento else {})


async def main() -> None:
    restaurar.main()
    c101, c302, c201 = ctx("101"), ctx("302"), ctx("201")

    # Garantia 2: o apartamento vem do state
    r = await tools.listar_minhas_reservas(c101)
    conferir("101 lista só a própria reserva", [x["codigo"] for x in r["reservas"]] == ["RSV-1377"])
    r = await tools.listar_meus_visitantes(c101)
    conferir("101 não vê visitantes de outros", r["visitantes"] == [])
    conferir("sem apartamento na sessão, tool recusa", (await tools.listar_minhas_reservas(ctx(None)))["ok"] is False)

    r = await tools.consultar_agenda("salao-de-festas", "2030-03-16", c101)
    conferir("agenda ocupada devolve só livre=False", r == {"ok": True, "area": "salao-de-festas", "data": "2030-03-16", "livre": False})

    r = await tools.cancelar_reserva(c101, area="salao-de-festas", data="2030-03-16")
    conferir("101 não cancela reserva do 302", r["ok"] is False)
    conferir("recusa não vaza código nem dono", "RSV-4821" not in json.dumps(r) and "302" not in json.dumps(r))
    r = await tools.cancelar_reserva(c101, codigo="RSV-4821")
    conferir("101 não cancela reserva do 302 por código", r["ok"] is False and "302" not in json.dumps(r))
    r = await tools.cancelar_reserva(c101, area="salao-de-festas", data="2031-01-01")
    conferir("reserva inexistente dá a mesma resposta", r["motivo"] == (await tools.cancelar_reserva(c101, codigo="RSV-4821"))["motivo"])

    r = await tools.reservar_area("salao-de-festas", "2030-03-16", c101)
    conferir("reservar data ocupada pelo 302 é recusado sem vazar", r["ok"] is False and "RSV-4821" not in json.dumps(r) and "302" not in json.dumps(r))
    conferir("reserva do 302 intacta", [x["codigo"] for x in (await tools.listar_minhas_reservas(c302))["reservas"]] == ["RSV-4821"])

    # Regra 4: cancelar a própria reserva
    r = await tools.cancelar_reserva(c101, area="quadra", data="2030-03-09")
    conferir("101 cancela a própria reserva", r["ok"] is True and r["codigo"] == "RSV-1377")

    # Confirmação decidida em código pela taxa
    conferir("quadra (taxa 0) não pede confirmação", tools.exige_confirmacao_reserva("quadra", "2030-04-06") is False)
    conferir("salão (taxa > 0) pede confirmação", tools.exige_confirmacao_reserva("salao-de-festas", "2030-04-20") is True)
    conferir("área desconhecida pede confirmação", tools.exige_confirmacao_reserva("piscina", "2030-04-20") is True)

    # Regra 5: códigos nunca repetem, inclusive de reserva cancelada
    a = await tools.reservar_area("quadra", "2030-04-06", c101)
    await tools.cancelar_reserva(c101, codigo=a["codigo"])
    b = await tools.reservar_area("quadra", "2030-04-06", c101)
    conferir("reserva nova ocupa data de reserva cancelada", a["ok"] and b["ok"])
    conferir("código novo difere do cancelado e do seed", len({a["codigo"], b["codigo"], "RSV-1377", "RSV-4821", "RSV-2950"}) == 5)

    # Validação de entrada
    conferir("data inválida é recusada", (await tools.reservar_area("quadra", "20/04/2030", c101))["ok"] is False)
    conferir("área inexistente é recusada", (await tools.reservar_area("piscina", "2030-04-20", c101))["ok"] is False)

    # Visitantes e idempotência
    v1 = await tools.autorizar_visitante("Joana Ribeiro", "2030-04-21", c101)
    v2 = await tools.autorizar_visitante("joana ribeiro", "2030-04-21", c101)
    visitantes = (await tools.listar_meus_visitantes(c101))["visitantes"]
    conferir("autorizar visitante grava uma vez", v1["ok"] and v2["ja_autorizado"] and len(visitantes) == 1)
    conferir("nome vazio é recusado", (await tools.autorizar_visitante("  ", "2030-04-21", c101))["ok"] is False)

    # Garantia 5: disputa
    apartamentos = ["101", "102", "201", "202", "301", "302"] * 4
    resultados = await asyncio.gather(
        *(tools.reservar_area("salao-de-festas", "2030-05-11", ctx(a)) for a in apartamentos)
    )
    vencedoras = [r for r in resultados if r["ok"]]
    conferir(f"disputa de {len(apartamentos)} pedidos: exatamente 1 vence", len(vencedoras) == 1)
    conferir("perdedores recebem recusa normal, sem exceção", all(r["ok"] or r["motivo"] for r in resultados))

    print("\nTudo certo." if falhas == 0 else f"\n{falhas} falha(s).")
    raise SystemExit(1 if falhas else 0)


asyncio.run(main())
