"""Banco do condomínio (SQLite): schema, carga inicial e conexão."""

import json
import sqlite3

from aurora import config

# Primeiro número da sequência de códigos novos. Os códigos do estado inicial
# (RSV-1377, RSV-4821, RSV-2950) ficam abaixo, então nunca colidem com os novos.
INICIO_SEQUENCIA = 10000

SCHEMA = """
CREATE TABLE IF NOT EXISTS apartamentos (
    numero  TEXT PRIMARY KEY,
    morador TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS areas (
    id   TEXT PRIMARY KEY,
    nome TEXT NOT NULL,
    taxa REAL NOT NULL CHECK (taxa >= 0)
);

CREATE TABLE IF NOT EXISTS reservas (
    codigo      TEXT PRIMARY KEY,
    apartamento TEXT NOT NULL REFERENCES apartamentos(numero),
    area        TEXT NOT NULL REFERENCES areas(id),
    data        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'ativa' CHECK (status IN ('ativa', 'cancelada'))
);

-- Garantia 5: no máximo uma reserva ativa por área e data, imposto pelo banco
-- no instante da gravação. Reserva cancelada não ocupa a data.
CREATE UNIQUE INDEX IF NOT EXISTS uq_reserva_ativa
    ON reservas (area, data) WHERE status = 'ativa';

CREATE INDEX IF NOT EXISTS ix_reservas_apartamento ON reservas (apartamento);

CREATE TABLE IF NOT EXISTS visitantes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    apartamento TEXT NOT NULL REFERENCES apartamentos(numero),
    nome        TEXT NOT NULL,
    data        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_visitantes_apartamento ON visitantes (apartamento);

-- Autorizar o mesmo visitante na mesma data duas vezes não duplica o registro (idempotência).
CREATE UNIQUE INDEX IF NOT EXISTS uq_visitante
    ON visitantes (apartamento, nome COLLATE NOCASE, data);

-- Sequência dos códigos de reserva. AUTOINCREMENT nunca reaproveita números.
CREATE TABLE IF NOT EXISTS sequencia_reserva (
    n INTEGER PRIMARY KEY AUTOINCREMENT
);
"""


def conectar() -> sqlite3.Connection:
    """Abre uma conexão nova. Autocommit: transações são controladas com BEGIN explícito."""
    config.DIR_ESTADO.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_CONDOMINIO, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def criar_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _ler_json(nome: str) -> list[dict]:
    return json.loads((config.DIR_DADOS / nome).read_text(encoding="utf-8"))


def carregar_dados_iniciais(conn: sqlite3.Connection) -> None:
    """Carrega dados/*.json no banco vazio. Os arquivos nunca são alterados."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.executemany(
            "INSERT INTO apartamentos (numero, morador) VALUES (:numero, :morador)",
            _ler_json("apartamentos.json"),
        )
        conn.executemany(
            "INSERT INTO areas (id, nome, taxa) VALUES (:id, :nome, :taxa)",
            _ler_json("areas.json"),
        )
        conn.executemany(
            "INSERT INTO reservas (codigo, apartamento, area, data) "
            "VALUES (:codigo, :apartamento, :area, :data)",
            _ler_json("reservas.json"),
        )
        conn.executemany(
            "INSERT INTO visitantes (apartamento, nome, data) "
            "VALUES (:apartamento, :nome, :data)",
            _ler_json("visitantes.json"),
        )
        conn.execute("INSERT INTO sequencia_reserva (n) VALUES (?)", (INICIO_SEQUENCIA,))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def inicializar() -> None:
    """Cria o schema e carrega os dados iniciais se o banco ainda estiver vazio.

    Chamado na subida da API: reiniciar nunca apaga nem recarrega dados existentes.
    """
    conn = conectar()
    try:
        criar_schema(conn)
        if conn.execute("SELECT COUNT(*) FROM apartamentos").fetchone()[0] == 0:
            carregar_dados_iniciais(conn)
    finally:
        conn.close()
