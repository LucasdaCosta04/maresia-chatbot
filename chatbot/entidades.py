"""Extracao de entidades das mensagens com regex e dicionarios.

Pratos, alergenicos e sinonimos vem da base de conhecimento (CAMINHO_BASE).
Este modulo so extrai: regras de negocio (dia fechado, limite de pessoas,
janela de reserva) ficam no conhecimento.py.
"""

import json
import re
import unicodedata
from datetime import date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from chatbot.config import CAMINHO_BASE, FUSO_HORARIO

_NUMEROS = {
    "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4,
    "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10,
    "onze": 11, "doze": 12, "treze": 13, "quatorze": 14, "catorze": 14,
    "quinze": 15, "dezesseis": 16, "dezessete": 17, "dezoito": 18,
    "dezenove": 19, "vinte": 20,
}
_PALAVRAS_NUM = "|".join(sorted(_NUMEROS, key=len, reverse=True))
_N = rf"(?:\d{{1,2}}|{_PALAVRAS_NUM})"

_DIAS_SEMANA = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]
_MESES = [
    "janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho",
    "agosto", "setembro", "outubro", "novembro", "dezembro",
]
_PRA = r"(?:pra|para|pro|p/)"

# Restricoes alimentares: ids iguais aos campos booleanos dos pratos na base.
_RESTRICOES = {
    "vegetariano": r"\bvegetarian[oa]s?\b|\bnao\s+como\s+carne\b",
    "vegano": r"\bvegan[oa]?s?\b",
    "sem_gluten": r"\bsem\s+gluten\b|\bgluten\s+free\b|\bceliac[oa]s?\b"
                  r"|\bintoleran\w*\s+(?:a\s+|ao\s+)?gluten\b",
    "sem_lactose": r"\bsem\s+lactose\b|\bzero\s+lactose\b|\blactose\s+free\b"
                   r"|\bintoleran\w*\s+(?:a\s+)?lactose\b",
}

# Categorias do cardapio: ids iguais ao campo "categoria" dos pratos na base.
_CATEGORIAS = {
    "entrada": r"\bentradas?\b|\bpetiscos?\b|\baperitivos?\b",
    "prato_principal": r"\bpratos?\s+principa(?:l|is)\b|\bprincipais\b",
    "acompanhamento": r"\bacompanhamentos?\b",
    "salada": r"\bsaladas?\b",
    "sobremesa": r"\bsobremesas?\b|\bdoces?\b",
}

# Preco: so vale com contexto de dinheiro na mensagem, para "ate 10 pessoas"
# ou "ate as 20h" nao virarem faixa de preco.
_RE_CONTEXTO_PRECO = re.compile(
    r"r\$|\b(?:reais|real|contos?|pila|prec\w*|cust\w*|valor\w*|gastar|orcamento"
    r"|barat\w*|car[oa]s?)\b"
)
_NUM_PRECO = r"(?:r\$\s*)?(\d{1,4}(?:[.,]\d{1,2})?)"
_RE_PRECO_ENTRE = re.compile(
    r"\bentre\s+" + _NUM_PRECO + r"(?:\s*(?:reais|real))?\s+e\s+" + _NUM_PRECO
)
_RE_PRECO_MAX = re.compile(
    r"\b(?:ate|abaixo de|menos de|no maximo|inferior a|nao passe de|max)\s+" + _NUM_PRECO
)
_RE_PRECO_MIN = re.compile(
    r"\b(?:acima de|mais de|a partir de|pelo menos|superior a|minimo de)\s+" + _NUM_PRECO
)
_RE_MAIS_CARO = re.compile(r"\b(?:mais\s+car[oa]s?|maior(?:es)?\s+prec\w*)\b")
_RE_MAIS_BARATO = re.compile(
    r"\b(?:mais\s+(?:barat[oa]s?|em conta|economic[oa]s?)|menor(?:es)?\s+prec\w*|barat\w*)\b"
)

# Pista de alergia logo antes do termo: o termo vale como alergenico, nao prato.
_RE_PISTA_ALERGIA = re.compile(
    r"(?:alergi\w*|alergic\w*|intoleran\w*|sem|livres?\s+de|nao\s+(?:como|posso\s+comer"
    r"|tem|tenham?|levam?|leve|contem|contenham?|possuem?|vem\s+com))"
    r"\s+(?:(?:a|ao|aos|as|de|do|da|com)\s+)?$"
)

_RE_PESSOAS = [
    (re.compile(rf"\b({_N})\s+adultos?\s+e\s+({_N})\s+criancas?\b"), "soma"),
    (re.compile(rf"\beu\s+e\s+mais\s+({_N})\b"), "mais_um"),
    (re.compile(rf"\b({_N})\s+(?:pessoas?|lugares|lugar|convidados|adultos?)\b"), "n"),
    (re.compile(rf"\bmesa\s+{_PRA}\s*({_N})\b(?!\s*(?:h\b|hs\b|hrs\b|:|/|horas?\b))"), "n"),
    (re.compile(rf"\bsomos\s+(?:em\s+)?({_N})\b"), "n"),
    (re.compile(
        rf"\b{_PRA}\s*({_N})\b"
        r"(?!\s*(?:h\b|hs\b|hrs\b|:|/|horas?\b|e\s+meia|(?:da|de)\s+(?:manha|tarde|noite)))"
        rf"(?!\s+de\s+(?:{'|'.join(_MESES)}))"
    ), "n_sem_um"),
    (re.compile(r"\beu\s+e\s+(?:(?:a|o)\s+)?(?:minha|meu|ela|ele)\b"), "dois"),
    (re.compile(r"\bcasal\b|\ba\s+dois\b"), "dois"),
]

_RE_DEPOIS_AMANHA = re.compile(r"\b(?:depois|dps)\s+de\s+amanha\b")
_RE_AMANHA = re.compile(r"\b(?:amanha|amnh)\b")
_RE_HOJE = re.compile(r"\b(?:hoje|hj)\b")
_RE_DATA_BARRA = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?:/(\d{4}|\d{2}))?(?![\d/])")
_RE_DATA_MES = re.compile(
    rf"\b({_N})\s+de\s+({'|'.join(_MESES)})(?:\s+de\s+(\d{{4}}))?\b"
)
_RE_DIA_N = re.compile(r"\bdia\s+(\d{1,2})\b(?!\s*/)")
_RE_DIA_SEMANA = re.compile(
    r"\b(?:(proxim[oa])\s+)?(" + "|".join(_DIAS_SEMANA) + r")(?:\s+feira)?"
    r"(?:\s+(que\s+vem))?\b"
)

_RE_PERIODO = re.compile(
    r"\b(?P<almoco>almoco|almocar|almocando)\b|\b(?P<jantar>jantar|janta|jantinha|noite)\b"
)
_RE_MEIO_DIA = re.compile(r"\b(meio\s+dia|meia\s+noite)(\s+e\s+meia)?\b")
_RE_HORA = re.compile(
    r"(?P<marc>\b(?:as|das|pelas|pras|umas|ate\s+as|a(?=\s+uma\b))\s+)?"
    rf"(?<![\d/:])(?P<h>\d{{1,2}}|{_PALAVRAS_NUM})"
    r"(?:\s*(?P<hsep>hrs|hs|horas?|h)\s*(?P<m1>\d{2})?(?!\d)|:(?P<m2>\d{2}))?"
    r"(?:\s+e\s+(?P<emin>meia|quinze|trinta|\d{2}))?"
    r"(?:\s+(?:da|de)\s+(?P<per>manha|tarde|noite|madrugada))?"
    r"(?![\w/])"
)
_MINUTOS_EXTENSO = {"meia": 30, "quinze": 15, "trinta": 30}

_RE_GATILHO_NOME = re.compile(
    r"\b(?:(?:em|no)\s+nome\s+(?:de|do|da)|meu\s+nome\s+(?:e|eh)|me\s+chamo"
    rf"|(?:reserva|reservar|mesa)\s+{_PRA}\s*(?:(?:o|a)\s+)?)\s*"
)
_RE_PALAVRA = re.compile(r"[ \t]*([a-z]+)")
_CONECTORES_NOME = {"da", "de", "do", "das", "dos"}
_PARADAS_NOME = (
    set(_NUMEROS) | set(_DIAS_SEMANA) | set(_MESES) | {
        "a", "o", "as", "os", "e", "eu", "mim", "nos", "gente", "familia", "mesa",
        "pessoa", "pessoas", "hoje", "hj", "amanha", "depois", "dia", "proximo",
        "proxima", "que", "vem", "esta", "essa", "semana", "almoco", "jantar",
        "janta", "noite", "tarde", "manha", "meio", "minha", "meu", "sou", "com",
        "sem", "por", "favor", "obrigado", "obrigada", "pra", "para", "pro",
        "casal", "agora", "aniversario", "hora", "horas", "feira", "um", "uma",
        "amigos", "amigas", "grupo", "empresa", "galera", "turma", "ela", "ele",
    }
)


def _normalizar(texto: str) -> str:
    """Minusculas e sem acento, caractere a caractere (mesmo comprimento)."""
    saida = []
    for caractere in texto:
        decomposto = unicodedata.normalize("NFD", caractere.lower())
        base = decomposto[0] if decomposto else caractere
        saida.append(" " if base in "-_" else base)
    return "".join(saida)


def _regex_termo(termo: str) -> re.Pattern:
    """Regex de um termo normalizado, com plural opcional e borda de palavra."""
    partes = [re.escape(p) for p in termo.split()]
    return re.compile(r"(?<!\w)" + r"\s+".join(partes) + r"s?(?!\w)")


@lru_cache(maxsize=1)
def _carregar_base() -> dict:
    """Le a base de conhecimento uma unica vez."""
    with open(CAMINHO_BASE, encoding="utf-8") as arquivo:
        return json.load(arquivo)


@lru_cache(maxsize=1)
def _indice_pratos() -> list:
    """Lista (sinonimo, regex, candidatos) do sinonimo mais longo ao mais curto.

    Um sinonimo e generico quando aparece, como palavra inteira, dentro de um
    sinonimo de outro prato; nesse caso tem mais de um candidato.
    """
    cardapio = _carregar_base()["cardapio"]
    termos = {}
    for prato in cardapio:
        nome = re.sub(r"\(.*?\)", "", prato["nome"])
        brutos = prato["sinonimos"] + [nome]
        termos[prato["id"]] = {" ".join(_normalizar(t).split()) for t in brutos}

    indice = {}
    for prato in cardapio:
        for termo in termos[prato["id"]]:
            regex = _regex_termo(termo)
            contido = re.compile(r"(?<!\w)" + re.escape(termo) + r"(?!\w)")
            candidatos = [
                outro["id"] for outro in cardapio
                if outro["id"] == prato["id"]
                or any(contido.search(t) for t in termos[outro["id"]])
            ]
            anteriores = indice.get(termo, (regex, []))[1]
            unidos = [c for c in (p["id"] for p in cardapio)
                      if c in candidatos or c in anteriores]
            indice[termo] = (regex, unidos)
    return sorted(
        ((t, r, c) for t, (r, c) in indice.items()),
        key=lambda item: len(item[0]), reverse=True,
    )


@lru_cache(maxsize=1)
def _indice_alergenicos() -> list:
    """Lista (sinonimo, regex, valor) do sinonimo mais longo ao mais curto.

    O valor e o id do alergenico, ou ("grupo", termo) para as variacoes de
    alergenicos.termos_ambiguos da base ("frutos do mar").
    """
    secao = _carregar_base()["alergenicos"]
    indice = {}
    for item in secao["itens"].values():
        for sinonimo in item["sinonimos"] + [item["id"].replace("_", " ")]:
            termo = " ".join(_normalizar(sinonimo).split())
            indice.setdefault(termo, item["id"])
    for grupo in secao.get("termos_ambiguos", []):
        for variacao in grupo["variacoes"] + [grupo["termo"]]:
            termo = " ".join(_normalizar(variacao).split())
            indice.setdefault(termo, ("grupo", grupo["termo"]))
    return sorted(
        ((t, _regex_termo(t), i) for t, i in indice.items()),
        key=lambda item: len(item[0]), reverse=True,
    )


def _sobrepoe(inicio: int, fim: int, ocupados: list) -> bool:
    return any(inicio < f and i < fim for i, f in ocupados)


def _casar_termos(texto: str, indice: list, ocupados: list) -> list:
    """Casa termos do mais longo ao mais curto sem sobreposicao."""
    achados = []
    for termo, regex, valor in indice:
        for casamento in regex.finditer(texto):
            inicio, fim = casamento.span()
            if not _sobrepoe(inicio, fim, ocupados):
                ocupados.append((inicio, fim))
                achados.append((inicio, fim, termo, valor))
    return sorted(achados)


def _unicos(valores) -> list:
    return list(dict.fromkeys(valores))


@lru_cache(maxsize=1)
def _ids_grupos() -> dict:
    """Termo do grupo ("frutos do mar") -> ids dos alergenicos que ele cobre."""
    return {
        grupo["termo"]: grupo["ids"]
        for grupo in _carregar_base()["alergenicos"].get("termos_ambiguos", [])
    }


def _extrair_pratos_alergenicos(texto: str) -> tuple:
    """Pratos, pratos ambiguos, alergenicos e grupos de alergenicos.

    Prato vence, salvo pista de alergia: "risoto de frutos do mar" e prato;
    "sem frutos do mar" e o grupo. Os ids de um grupo entram em alergenicos.
    """
    alergenicos = _casar_termos(texto, _indice_alergenicos(), [])
    com_pista = [(i, f) for i, f, _, _ in alergenicos if _RE_PISTA_ALERGIA.search(texto[:i])]

    pratos, ambiguos, spans_pratos = [], {}, []
    for inicio, fim, termo, candidatos in _casar_termos(texto, _indice_pratos(), list(com_pista)):
        spans_pratos.append((inicio, fim))
        if len(candidatos) > 1:
            ambiguos.setdefault(termo, candidatos)
        else:
            pratos.append(candidatos[0])

    ids_alergenicos, grupos = [], []
    for inicio, fim, _, valor in alergenicos:
        if _sobrepoe(inicio, fim, spans_pratos):
            continue
        if isinstance(valor, tuple):
            grupos.append(valor[1])
            ids_alergenicos += _ids_grupos()[valor[1]]
        else:
            ids_alergenicos.append(valor)
    return _unicos(pratos), ambiguos, _unicos(ids_alergenicos), _unicos(grupos)


def _extrair_restricoes(texto: str) -> list:
    return [nome for nome, padrao in _RESTRICOES.items() if re.search(padrao, texto)]


def _extrair_categorias(texto: str) -> list:
    return [nome for nome, padrao in _CATEGORIAS.items() if re.search(padrao, texto)]


def _valor(texto: str) -> float:
    """'49,90' -> 49.9."""
    return float(texto.replace(",", "."))


def _extrair_preco(texto: str) -> dict | None:
    """Faixa de preco e ordem pedidas: {"min", "max", "ordem"}; None se nao ha.

    "ate 50 reais" -> max 50; "acima de 100 reais" -> min 100; "entre 50 e
    100 reais" -> min 50 e max 100; "mais barato"/"barato" -> ordem "barato";
    "mais caro" -> ordem "caro".
    """
    if not _RE_CONTEXTO_PRECO.search(texto):
        return None
    minimo = maximo = None
    entre = _RE_PRECO_ENTRE.search(texto)
    if entre:
        minimo, maximo = sorted((_valor(entre.group(1)), _valor(entre.group(2))))
    else:
        achado = _RE_PRECO_MAX.search(texto)
        maximo = _valor(achado.group(1)) if achado else None
        achado = _RE_PRECO_MIN.search(texto)
        minimo = _valor(achado.group(1)) if achado else None
    if _RE_MAIS_CARO.search(texto):
        ordem = "caro"
    elif _RE_MAIS_BARATO.search(texto):
        ordem = "barato"
    else:
        ordem = None
    if minimo is None and maximo is None and ordem is None:
        return None
    return {"min": minimo, "max": maximo, "ordem": ordem}


def _numero(token: str) -> int:
    """'4' ou 'quatro' -> 4."""
    return int(token) if token.isdigit() else _NUMEROS[token]


def _extrair_pessoas(texto: str) -> int | None:
    for regex, tipo in _RE_PESSOAS:
        for casamento in regex.finditer(texto):
            if tipo == "dois":
                return 2
            if tipo == "soma":
                return _numero(casamento.group(1)) + _numero(casamento.group(2))
            if tipo == "mais_um":
                return _numero(casamento.group(1)) + 1
            if tipo == "n_sem_um" and casamento.group(1) in ("um", "uma"):
                continue
            return _numero(casamento.group(1))
    return None


def _data_valida(ano: int, mes: int, dia: int) -> date | None:
    try:
        return date(ano, mes, dia)
    except ValueError:
        return None


def _proximo_dia_do_mes(hoje: date, dia: int) -> date | None:
    """Proxima data (a partir de hoje) com esse dia do mes."""
    ano, mes = hoje.year, hoje.month
    for _ in range(13):
        candidata = _data_valida(ano, mes, dia)
        if candidata and candidata >= hoje:
            return candidata
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return None


def _dia_mes_sem_ano(hoje: date, dia: int, mes: int) -> date | None:
    """dd/mm sem ano: este ano, ou o proximo se a data ja passou."""
    candidata = _data_valida(hoje.year, mes, dia)
    if candidata and candidata < hoje:
        candidata = _data_valida(hoje.year + 1, mes, dia)
    return candidata


def _extrair_data(texto: str, hoje: date) -> date | None:
    if _RE_DEPOIS_AMANHA.search(texto):
        return hoje + timedelta(days=2)
    if _RE_AMANHA.search(texto):
        return hoje + timedelta(days=1)
    if _RE_HOJE.search(texto):
        return hoje

    casamento = _RE_DATA_BARRA.search(texto)
    if casamento:
        dia, mes, ano = casamento.groups()
        if ano:
            ano = int(ano) + (2000 if len(ano) == 2 else 0)
            return _data_valida(ano, int(mes), int(dia))
        return _dia_mes_sem_ano(hoje, int(dia), int(mes))

    casamento = _RE_DATA_MES.search(texto)
    if casamento:
        dia, mes = _numero(casamento.group(1)), _MESES.index(casamento.group(2)) + 1
        if casamento.group(3):
            return _data_valida(int(casamento.group(3)), mes, dia)
        return _dia_mes_sem_ano(hoje, dia, mes)

    casamento = _RE_DIA_N.search(texto)
    if casamento:
        return _proximo_dia_do_mes(hoje, int(casamento.group(1)))

    casamento = _RE_DIA_SEMANA.search(texto)
    if casamento:
        proximo, nome, que_vem = casamento.groups()
        delta = (_DIAS_SEMANA.index(nome) - hoje.weekday()) % 7
        if delta == 0 and (proximo or que_vem):
            delta = 7
        return hoje + timedelta(days=delta)
    return None


def _extrair_periodo(texto: str) -> str | None:
    casamento = _RE_PERIODO.search(texto)
    if not casamento:
        return None
    return "almoco" if casamento.group("almoco") else "jantar"


def _formatar(hora: int, minuto: int) -> str:
    return f"{hora:02d}:{minuto:02d}"


def _extrair_horario(texto: str, periodo: str | None) -> tuple:
    """Retorna (horario, horario_ambiguo); no maximo um dos dois preenchido."""
    casamento = _RE_MEIO_DIA.search(texto)
    if casamento:
        hora = 12 if casamento.group(1).startswith("meio") else 0
        return _formatar(hora, 30 if casamento.group(2) else 0), None

    for casamento in _RE_HORA.finditer(texto):
        g = casamento.groupdict()
        if not any(g[k] for k in ("marc", "hsep", "m2", "emin", "per")):
            continue
        hora = _numero(g["h"])
        minuto_txt = g["m1"] or g["m2"] or g["emin"]
        if minuto_txt is None:
            minuto = 0
        elif minuto_txt.isdigit():
            minuto = int(minuto_txt)
        else:
            minuto = _MINUTOS_EXTENSO[minuto_txt]
        if hora > 23 or minuto > 59:
            continue

        if g["per"]:
            if g["per"] in ("tarde", "noite") and 1 <= hora <= 11:
                hora += 12
            return _formatar(hora, minuto), None
        if hora == 0 or hora >= 12 or g["h"].startswith("0"):
            return _formatar(hora, minuto), None
        if periodo == "jantar" or (periodo == "almoco" and hora <= 4):
            return _formatar(hora + 12, minuto), None
        if periodo == "almoco":
            return _formatar(hora, minuto), None
        return None, f"{_formatar(hora, minuto)}|{_formatar(hora + 12, minuto)}"
    return None, None


def _extrair_nome(original: str, texto: str) -> str | None:
    """Nome apos 'em nome de', 'meu nome e', 'me chamo' ou 'reserva pro'."""
    for gatilho in _RE_GATILHO_NOME.finditer(texto):
        posicao, palavras, pendentes = gatilho.end(), [], []
        while len(palavras) < 4:
            casamento = _RE_PALAVRA.match(texto, posicao)
            if not casamento:
                break
            token = casamento.group(1)
            inicio, fim = casamento.span(1)
            if token in _CONECTORES_NOME and palavras:
                pendentes.append(original[inicio:fim].lower())
            elif token in _PARADAS_NOME or token in _CONECTORES_NOME:
                break
            else:
                bruto = original[inicio:fim]
                palavras.extend(pendentes)
                palavras.append(bruto[0].upper() + bruto[1:].lower())
                pendentes = []
            posicao = fim
        if palavras:
            return " ".join(palavras)
    return None


def extrair_entidades(texto: str, referencia: datetime | None = None) -> dict:
    """Extrai pratos, alergenicos (e grupos), restricoes, categorias, preco,
    pessoas, data, horario, periodo e nome.

    `referencia` e o "agora" usado para datas relativas (padrao: agora no
    FUSO_HORARIO). Sempre devolve todas as chaves, com None ou vazio.
    """
    if referencia is None:
        referencia = datetime.now(ZoneInfo(FUSO_HORARIO))
    normalizado = _normalizar(texto or "")

    pratos, pratos_ambiguos, alergenicos, grupos = _extrair_pratos_alergenicos(normalizado)
    data = _extrair_data(normalizado, referencia.date())
    periodo = _extrair_periodo(normalizado)
    horario, horario_ambiguo = _extrair_horario(normalizado, periodo)

    return {
        "pratos": pratos,
        "pratos_ambiguos": pratos_ambiguos,
        "alergenicos": alergenicos,
        "grupos_alergenicos": grupos,
        "restricoes": _extrair_restricoes(normalizado),
        "categorias": _extrair_categorias(normalizado),
        "preco": _extrair_preco(normalizado),
        "pessoas": _extrair_pessoas(normalizado),
        "data": data.isoformat() if data else None,
        "dia_semana": _DIAS_SEMANA[data.weekday()] if data else None,
        "horario": horario,
        "horario_ambiguo": horario_ambiguo,
        "periodo": periodo,
        "nome": _extrair_nome(texto or "", normalizado),
    }
