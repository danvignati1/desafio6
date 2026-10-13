"""Regras de negócio sobre o banco do condomínio.

Toda função que escreve recebe o apartamento como argumento explícito. Quem
decide qual apartamento usar é o código que chama (as tools leem do state da
sessão), nunca o modelo. Nenhuma função aqui devolve dados de outro apartamento
a quem pergunta por um apartamento específico.
"""

import re
import sqlite3
from datetime import date

from aurora import db

_FORMATO_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TAMANHO_MAX_NOME = 100


def data_valida(valor: object) -> bool:
    if not isinstance(valor, str) or not _FORMATO_DATA.match(valor):
        return False
    try:
        date.fromisoformat(valor)
    except ValueError:
        return False
    return True


def _consultar(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    conn = db.conectar()
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def ids_das_areas() -> list[str]:
    return [r["id"] for r in _consultar("SELECT id FROM areas ORDER BY rowid")]


def taxa_da_area(area: str) -> float | None:
    """Taxa em reais, ou None se a área não existe."""
    linhas = _consultar("SELECT taxa FROM areas WHERE id = ?", (area,))
    return linhas[0]["taxa"] if linhas else None


def apartamento_existe(apartamento: str) -> bool:
    return bool(_consultar("SELECT 1 FROM apartamentos WHERE numero = ?", (apartamento,)))


def reservas_do_apartamento(apartamento: str) -> list[dict]:
    linhas = _consultar(
        "SELECT codigo, area, data FROM reservas "
        "WHERE apartamento = ? AND status = 'ativa' ORDER BY data, codigo",
        (apartamento,),
    )
    return [dict(r) for r in linhas]


def visitantes_do_apartamento(apartamento: str) -> list[dict]:
    linhas = _consultar(
        "SELECT nome, data FROM visitantes WHERE apartamento = ? ORDER BY data, id",
        (apartamento,),
    )
    return [dict(r) for r in linhas]


def data_livre(area: str, data: str) -> bool:
    """Só diz se a data está livre. Não revela de quem é uma reserva existente."""
    return not _consultar(
        "SELECT 1 FROM reservas WHERE area = ? AND data = ? AND status = 'ativa'",
        (area, data),
    )


def _transacao_de_escrita():
    conn = db.conectar()
    conn.execute("BEGIN IMMEDIATE")
    return conn


def reservar(apartamento: str, area: str, data: str) -> dict:
    """Grava a reserva. A exclusividade de (area, data) é do índice único do banco.

    Não confere a agenda antes: confere-e-grava deixaria uma janela para outra
    reserva entrar. O INSERT é a conferência, e o banco recusa o perdedor.
    """
    if taxa_da_area(area) is None:
        return {"ok": False, "motivo": "área inexistente"}
    if not data_valida(data):
        return {"ok": False, "motivo": "data inválida, use AAAA-MM-DD"}
    conn = _transacao_de_escrita()
    try:
        n = conn.execute("INSERT INTO sequencia_reserva DEFAULT VALUES").lastrowid
        codigo = f"RSV-{n}"
        conn.execute(
            "INSERT INTO reservas (codigo, apartamento, area, data) VALUES (?, ?, ?, ?)",
            (codigo, apartamento, area, data),
        )
        conn.execute("COMMIT")
    except sqlite3.IntegrityError as erro:
        conn.execute("ROLLBACK")
        if "reservas.area" in str(erro):
            return {"ok": False, "motivo": "data indisponível para essa área"}
        raise
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return {"ok": True, "codigo": codigo, "area": area, "data": data}


def cancelar(
    apartamento: str,
    *,
    codigo: str | None = None,
    area: str | None = None,
    data: str | None = None,
) -> dict:
    """Cancela uma reserva ativa do próprio apartamento.

    Reserva de outro apartamento e reserva inexistente dão a mesma resposta,
    para que a recusa não vaze nada sobre terceiros.
    """
    nao_encontrada = {"ok": False, "motivo": "nenhuma reserva ativa sua encontrada com esses dados"}
    if codigo:
        filtro, params = "codigo = ?", (codigo,)
    elif area and data:
        filtro, params = "area = ? AND data = ?", (area, data)
    else:
        return {"ok": False, "motivo": "informe o código da reserva ou a área e a data"}

    conn = _transacao_de_escrita()
    try:
        linha = conn.execute(
            f"SELECT codigo, area, data FROM reservas "
            f"WHERE apartamento = ? AND status = 'ativa' AND {filtro}",
            (apartamento, *params),
        ).fetchone()
        if linha is None:
            conn.execute("ROLLBACK")
            return nao_encontrada
        conn.execute("UPDATE reservas SET status = 'cancelada' WHERE codigo = ?", (linha["codigo"],))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return {"ok": True, "codigo": linha["codigo"], "area": linha["area"], "data": linha["data"]}


def autorizar_visitante(apartamento: str, nome: str, data: str) -> dict:
    nome = (nome or "").strip()
    if not nome or len(nome) > _TAMANHO_MAX_NOME:
        return {"ok": False, "motivo": "nome do visitante inválido"}
    if not data_valida(data):
        return {"ok": False, "motivo": "data inválida, use AAAA-MM-DD"}
    conn = _transacao_de_escrita()
    try:
        conn.execute(
            "INSERT INTO visitantes (apartamento, nome, data) VALUES (?, ?, ?)",
            (apartamento, nome, data),
        )
        conn.execute("COMMIT")
        repetido = False
    except sqlite3.IntegrityError as erro:
        conn.execute("ROLLBACK")
        if "visitantes" not in str(erro):
            raise
        repetido = True
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return {"ok": True, "nome": nome, "data": data, "ja_autorizado": repetido}
