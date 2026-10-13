"""Confere a estrutura dos agentes, sem chamar o modelo.

Uso: uv run python scripts/verificar_agentes.py
"""

import re

from google.adk.tools import FunctionTool

from aurora import config
from aurora.agentes import agente_principal, criar_app

falhas = 0


def conferir(descricao: str, condicao: bool) -> None:
    global falhas
    print(("ok    " if condicao else "FALHA ") + descricao)
    falhas += 0 if condicao else 1


app = criar_app()
especialistas = agente_principal.sub_agents
conferir("agente principal com pelo menos 2 especialistas", len(especialistas) >= 2)
conferir("especialista de regulamento presente", any(a.name == "regulamento" for a in especialistas))
conferir("retomada ligada no App", bool(app.resumability_config and app.resumability_config.is_resumable))
conferir("especialistas mantêm a transferência permitida (retomada de confirmação)", all(
    not a.disallow_transfer_to_parent and not a.disallow_transfer_to_peers for a in especialistas
))

# O regulamento não pode estar nas instruções: nenhuma linha longa dele aparece nelas.
linhas = [l.strip() for l in (config.DIR_DADOS / "regulamento.md").read_text(encoding="utf-8").splitlines()]
instrucoes = " ".join(str(a.instruction) for a in [agente_principal, *especialistas])
conferir("instruções não contêm trechos do regulamento", not any(len(l) >= 40 and l in instrucoes for l in linhas))
conferir("instruções do principal são curtas", len(str(agente_principal.instruction)) < 3000)

# Nenhuma tool aceita apartamento como parâmetro.
for agente in especialistas:
    for t in agente.tools:
        ferramenta = t if isinstance(t, FunctionTool) else FunctionTool(t)
        esquema = ferramenta._get_declaration().parameters_json_schema or {}
        nomes = set(esquema.get("properties", {}))
        conferir(f"{agente.name}.{ferramenta.name} sem parâmetro de apartamento", not re.search("apart", " ".join(nomes), re.I))

agente_visitantes = next(a for a in especialistas if a.name == "visitantes")
conferir("autorizar_visitante sempre exige confirmação", any(
    isinstance(t, FunctionTool) and t.name == "autorizar_visitante" and t._require_confirmation is True
    for t in agente_visitantes.tools
))

print("\nTudo certo." if falhas == 0 else f"\n{falhas} falha(s).")
raise SystemExit(1 if falhas else 0)
