"""Consulta ao regulamento interno (dados/regulamento.md).

O regulamento nunca é carregado na conversa. A tool recebe a pergunta, escolhe
o capítulo mais pertinente e devolve só os artigos desse capítulo que
respondem a ela. Assim nenhum evento da sessão carrega capítulos de outros
assuntos, e o custo de tokens não cresce a cada mensagem.
"""

import math
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from aurora import config

MAX_ARTIGOS = 3

_STOPWORDS = set(
    "a o as os um uma uns umas de do da dos das em no na nos nas por para com sem ao aos ate que e ou "
    "se qual quais quem como quando onde posso pode podem devo deve ser sao ha tem ter ha eh mais "
    "muito pelo pela pelos pelas sobre entre eu meu minha nosso nossa esse essa isso este esta isto "
    "horas hora tambem ja nao sim voce".split()
)

# Aproxima a linguagem do morador da dos títulos dos capítulos.
_SINONIMOS = {
    "cachorro": "animais", "gato": "animais", "pet": "animais", "cao": "animais",
    "barulho": "silencio", "ruido": "silencio", "som": "silencio", "musica": "silencio",
    "carro": "garagem", "moto": "garagem", "vaga": "garagem", "estacionar": "garagem",
    "lixo": "reciclagem", "entulho": "reciclagem", "multa": "penalidades",
    "advertencia": "penalidades", "mudar": "mudancas", "caminhao": "mudancas",
    "obra": "reformas", "reforma": "reformas", "visitante": "portaria", "entregador": "portaria",
    "festa": "salao", "churrasco": "churrasqueira", "nadar": "piscina", "ginastica": "academia",
    "crianca": "brinquedoteca",
}


@dataclass(frozen=True)
class Artigo:
    capitulo: str
    numero: str
    texto: str


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")


def _radical(palavra: str) -> str:
    return palavra[:-1] if len(palavra) > 3 and palavra.endswith("s") else palavra


def _termos(texto: str) -> list[str]:
    palavras = re.findall(r"[a-z0-9]+", _normalizar(texto))
    return [_radical(p) for p in palavras if p not in _STOPWORDS and len(p) > 1]


@lru_cache(maxsize=1)
def _carregar() -> tuple[list[Artigo], dict[str, str]]:
    """Artigos do regulamento e o título de cada capítulo, lidos uma vez."""
    artigos: list[Artigo] = []
    titulos: dict[str, str] = {}
    capitulo = ""
    for bloco in (config.DIR_DADOS / "regulamento.md").read_text(encoding="utf-8").split("\n\n"):
        bloco = bloco.strip()
        if bloco.startswith("## "):
            capitulo = bloco[3:].strip()
            titulos[capitulo] = capitulo
        elif m := re.match(r"\*\*Art\. (\d+)", bloco):
            artigos.append(Artigo(capitulo, m[1], bloco))
        elif artigos and capitulo and not bloco.startswith("#"):
            # Incisos e parágrafos pertencem ao artigo anterior.
            ultimo = artigos[-1]
            artigos[-1] = Artigo(ultimo.capitulo, ultimo.numero, ultimo.texto + "\n\n" + bloco)
    return artigos, titulos


@lru_cache(maxsize=1)
def _indice() -> tuple[list[Artigo], list[list[str]], dict[str, float]]:
    artigos, _ = _carregar()
    termos_por_artigo = [_termos(a.capitulo + " " + a.texto) for a in artigos]
    n = len(artigos)
    docs_com_termo: dict[str, int] = {}
    for termos in termos_por_artigo:
        for t in set(termos):
            docs_com_termo[t] = docs_com_termo.get(t, 0) + 1
    idf = {t: math.log(1 + (n - df + 0.5) / (df + 0.5)) for t, df in docs_com_termo.items()}
    return artigos, termos_por_artigo, idf


def _termos_da_pergunta(pergunta: str) -> tuple[set[str], set[str]]:
    """Termos ditos pelo morador e termos de capítulo inferidos por sinônimo."""
    ditos = _termos(pergunta)
    inferidos = {_radical(_SINONIMOS[t]) for t in ditos if t in _SINONIMOS}
    return set(ditos), inferidos


# Pesos de quando uma palavra da pergunta aparece no título do capítulo.
_BONUS_TITULO = 4.0
_BONUS_TITULO_INFERIDO = 2.0
# Abaixo disso a pergunta não casa com nada do regulamento.
_PONTUACAO_MINIMA = 2.0


def buscar(pergunta: str) -> dict:
    """Devolve os artigos do capítulo mais pertinente à pergunta, no máximo MAX_ARTIGOS."""
    ditos, inferidos = _termos_da_pergunta(pergunta)
    consulta = ditos | inferidos
    artigos, termos_por_artigo, idf = _indice()
    if not consulta:
        return {"ok": False, "motivo": "pergunta sem conteúdo para consultar o regulamento"}

    pontos = []
    for termos in termos_por_artigo:
        contagem = {t: termos.count(t) for t in consulta if t in termos}
        pontos.append(sum(idf[t] * c / (c + 1.2) for t, c in contagem.items()))

    por_capitulo: dict[str, list[int]] = {}
    for i, artigo in enumerate(artigos):
        por_capitulo.setdefault(artigo.capitulo, []).append(i)

    def nota(capitulo: str) -> float:
        titulo = set(_termos(capitulo.split(":", 1)[-1]))
        bonus = _BONUS_TITULO * len(ditos & titulo) + _BONUS_TITULO_INFERIDO * len((inferidos - ditos) & titulo)
        melhores = sorted((pontos[i] for i in por_capitulo[capitulo]), reverse=True)[:2]
        return sum(melhores) + bonus

    # O capítulo vence inteiro: nunca se misturam artigos de capítulos diferentes.
    capitulo = max(por_capitulo, key=nota)
    if nota(capitulo) < _PONTUACAO_MINIMA:
        return {"ok": False, "motivo": "não encontrei esse assunto no regulamento"}
    candidatos = sorted(por_capitulo[capitulo], key=lambda i: pontos[i], reverse=True)[:MAX_ARTIGOS]
    candidatos = [i for i in candidatos if pontos[i] > 0] or candidatos[:1]
    return {
        "ok": True,
        "capitulo": capitulo,
        "trechos": [artigos[i].texto for i in sorted(candidatos)],
    }
