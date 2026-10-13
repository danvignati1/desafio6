"""Verifica a consulta ao regulamento, sem modelo.

Uso: uv run python scripts/verificar_regulamento.py
"""

import json
import re

from aurora import config, regulamento

falhas = 0


def conferir(descricao: str, condicao: bool) -> None:
    global falhas
    print(("ok    " if condicao else "FALHA ") + descricao)
    falhas += 0 if condicao else 1


texto = (config.DIR_DADOS / "regulamento.md").read_text(encoding="utf-8")
capitulos = {m[1]: m[2] for m in re.finditer(r"^## (.+?)\n(.*?)(?=^## |\Z)", texto, re.M | re.S)}

r = regulamento.buscar("Até que horas a piscina funciona aos domingos?")
conferir("piscina aos domingos: capítulo da piscina", r["ok"] and "Piscina" in r["capitulo"])
conferir("traz o horário de domingo (20h)", "das 9h às 20h" in json.dumps(r, ensure_ascii=False))
tamanho = len(json.dumps(r, ensure_ascii=False))
conferir(f"resposta pequena ({tamanho} caracteres, regulamento tem {len(texto)})", tamanho < 3000)

casos = {
    "Posso ter um cachorro no apartamento?": "Animais",
    "Qual o horário de silêncio à noite?": "Silêncio",
    "Como funciona a mudança, posso trazer o caminhão a qualquer hora?": "Mudanças",
    "Quais as regras da garagem para visitantes?": "Garagem",
    "Qual a multa por infração?": "Infrações",
    "Quando posso fazer reforma no apartamento?": "Obras",
    "Onde descarto o lixo reciclável?": "Coleta",
    "Qual o horário da academia?": "Academia",
}
for pergunta, esperado in casos.items():
    resultado = regulamento.buscar(pergunta)
    conferir(f"'{pergunta}' -> {esperado}", resultado["ok"] and esperado in resultado["capitulo"])

# Isolamento: nenhum trecho devolvido pertence a outro capítulo.
perguntas = ["Até que horas a piscina funciona aos domingos?", *casos]
for pergunta in perguntas:
    resultado = regulamento.buscar(pergunta)
    corpo_do_capitulo = next(c for t, c in capitulos.items() if t == resultado["capitulo"])
    outros = [c for t, c in capitulos.items() if t != resultado["capitulo"]]
    ok = all(trecho in corpo_do_capitulo for trecho in resultado["trechos"]) and not any(
        trecho in o for trecho in resultado["trechos"] for o in outros
    )
    conferir(f"só trechos do próprio capítulo: {pergunta[:45]}", ok)

for fora in ("Qual a capital da França?", "Quem ganhou a copa do mundo?"):
    conferir(f"fora do regulamento não devolve texto: {fora}", regulamento.buscar(fora)["ok"] is False)
print("\nTudo certo." if falhas == 0 else f"\n{falhas} falha(s).")
raise SystemExit(1 if falhas else 0)
