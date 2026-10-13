"""Restaura o estado inicial do condomínio: uv run aurora-restaurar.

Apaga reservas, visitantes e também as sessões, e recarrega dados/*.json.
As sessões são apagadas junto para que nenhuma conversa antiga aponte para
reservas ou confirmações que deixaram de existir.
"""

from aurora import config, db


def _apagar(caminho) -> None:
    for sufixo in ("", "-wal", "-shm"):
        caminho.with_name(caminho.name + sufixo).unlink(missing_ok=True)


def main() -> None:
    config.DIR_ESTADO.mkdir(parents=True, exist_ok=True)
    _apagar(config.DB_CONDOMINIO)
    _apagar(config.DB_SESSOES)
    db.inicializar()

    conn = db.conectar()
    try:
        n_res = conn.execute("SELECT COUNT(*) FROM reservas").fetchone()[0]
        n_vis = conn.execute("SELECT COUNT(*) FROM visitantes").fetchone()[0]
    finally:
        conn.close()
    print(f"Dados restaurados: {n_res} reservas, {n_vis} visitantes. Sessões apagadas.")


if __name__ == "__main__":
    main()
