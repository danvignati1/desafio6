"""Configuração central: caminhos, banco e modelo."""

import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[2]
load_dotenv(RAIZ / ".env")

DIR_DADOS = RAIZ / "dados"
DIR_ESTADO = Path(os.environ.get("AURORA_ESTADO", RAIZ / "estado"))

# Dados do condomínio (reservas, visitantes) e sessões do ADK ficam em arquivos separados.
DB_CONDOMINIO = DIR_ESTADO / "aurora.db"
DB_SESSOES = DIR_ESTADO / "sessoes.db"
URL_SESSOES = f"sqlite+aiosqlite:///{DB_SESSOES}"

MODELO = os.environ.get("MODELO") or "gemini-3.6-flash"
