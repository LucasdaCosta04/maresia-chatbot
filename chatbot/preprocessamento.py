"""Pre-processamento do texto para o classificador de intencoes.

Usado SO pelo classificador (treino e predicao). A extracao de entidades
tem a sua propria normalizacao em entidades.py.

Etapas, nesta ordem:
1. minusculas;
2. remocao de acentos (o "c" cedilha vira "c");
3. expansao de abreviacoes de chat, por palavra inteira;
4. cada numero vira o token "num";
5. pontuacao, emojis e simbolos viram espaco;
6. espacos colapsados e strip.

As stopwords NAO sao removidas: foi uma decisao empirica. Remove-las baixou
a acuracia da validacao cruzada de 0,828 para 0,819, porque palavras curtas
como "pra", "de" e "a" ajudam a diferenciar as intencoes (ex.: "mesa pra 4"
x "mesa de jantar").
"""

import re
import unicodedata

# Abreviacoes de chat -> forma completa. A chave ja esta em minusculas e sem
# acento, porque a expansao roda depois das etapas 1 e 2.
ABREVIACOES = {
    "vc": "voce",
    "vcs": "voces",
    "q": "que",
    "hj": "hoje",
    "qnto": "quanto",
    "qnt": "quanto",
    "tb": "tambem",
    "tbm": "tambem",
    "pq": "porque",
    "p/": "para",
    "pra": "para",
    "msm": "mesmo",
    "blz": "beleza",
    "obg": "obrigado",
    "td": "tudo",
    "cmg": "comigo",
    "oq": "o que",
    "dps": "depois",
}

_ALFANUM = "a-z0-9"


def _padrao_abreviacao(abreviacao: str) -> str:
    """Monta o regex de uma abreviacao casando so palavra inteira.

    Antes da abreviacao nao pode haver letra ou digito. Depois, so exige
    fronteira se a abreviacao termina em letra/digito: "p/" casa em "p/mim",
    mas "q" nao casa dentro de "quero".
    """
    padrao = rf"(?<![{_ALFANUM}]){re.escape(abreviacao)}"
    if abreviacao[-1].isalnum():
        padrao += rf"(?![{_ALFANUM}])"
    return padrao


# Abreviacoes mais longas primeiro, para "qnto" ter prioridade sobre "qnt".
_RE_ABREVIACOES = re.compile(
    "|".join(
        f"(?P<a{i}>{_padrao_abreviacao(abrev)})"
        for i, abrev in enumerate(sorted(ABREVIACOES, key=len, reverse=True))
    )
)
_ABREV_POR_GRUPO = {
    f"a{i}": ABREVIACOES[abrev]
    for i, abrev in enumerate(sorted(ABREVIACOES, key=len, reverse=True))
}

# Sequencia numerica, com separadores internos ":", "," ou "." (19:30, 2,5).
_RE_NUMERO = re.compile(r"\d+(?:[:.,]\d+)*")
# Tudo que nao e letra a-z, digito ou espaco.
_RE_NAO_ALFANUM = re.compile(r"[^a-z0-9 ]+")
_RE_ESPACOS = re.compile(r"\s+")


def _remover_acentos(texto: str) -> str:
    """Decompoe em NFKD e descarta as marcas combinantes (acentos, cedilha).

    Assim "a" com til vira "a" e "c" cedilha vira "c".
    """
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def _expandir_abreviacoes(texto: str) -> str:
    """Troca cada abreviacao de ABREVIACOES pela forma completa."""
    return _RE_ABREVIACOES.sub(
        lambda m: f" {_ABREV_POR_GRUPO[m.lastgroup]} ", texto
    )


def _substituir_numeros(texto: str) -> str:
    """Troca cada sequencia numerica pelo token "num" separado por espacos.

    Ex.: "19:30" -> " num ", "20h" -> " num h".
    """
    return _RE_NUMERO.sub(" num ", texto)


def preprocessar(texto: str) -> str:
    """Normaliza uma mensagem para o classificador de intencoes.

    Ex.: "Mesa p/ 4 às 20h!! 😀" -> "mesa para num as num h".
    """
    texto = texto.lower()
    texto = _remover_acentos(texto)
    texto = _expandir_abreviacoes(texto)
    texto = _substituir_numeros(texto)
    texto = _RE_NAO_ALFANUM.sub(" ", texto)
    return _RE_ESPACOS.sub(" ", texto).strip()
