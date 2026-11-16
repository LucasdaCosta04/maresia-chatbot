"""Valida a base de conhecimento (dados/base_conhecimento.json).

Verifica JSON valido em UTF-8, indentacao de 2 espacos, chaves sem acento,
cardapio com exatamente 23 pratos e ids unicos, alergenicos citados nos
pratos, coerencia dos booleanos, funcionamento (segunda fechada, horarios
HH:MM), regras de reserva, intencoes e temas reservados (pix, pagamento,
delivery, entrega, onibus). Imprime um resumo.
Retorna codigo de saida 1 se encontrar algum erro.

Uso: python scripts/checar_base.py [caminho_do_json]
"""

import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

CAMINHO_PADRAO = Path(__file__).resolve().parent.parent / "dados" / "base_conhecimento.json"
TOTAL_PRATOS = 23
MAX_PESSOAS = 10
INTENCOES_OBRIGATORIAS = (
    "cardapio_alergenicos",
    "reserva",
    "horario_localizacao",
    "fora_escopo",
)
# RDC 26/2015 da ANVISA + moluscos e gergelim.
ALERGENICOS_OBRIGATORIOS = (
    "trigo_gluten",
    "crustaceos",
    "ovos",
    "peixes",
    "amendoim",
    "soja",
    "leite",
    "castanhas",
    "latex_natural",
    "moluscos",
    "gergelim",
)
ANIMAIS_MARINHOS = {"peixes", "crustaceos", "moluscos"}
DE_ORIGEM_ANIMAL = ANIMAIS_MARINHOS | {"leite", "ovos"}
DIAS = ("segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo")
CAMPOS_PRATO = {
    "id": str,
    "nome": str,
    "categoria": str,
    "descricao": str,
    "preco": (int, float),
    "serve_pessoas": int,
    "sinonimos": list,
    "alergenicos": list,
    "pode_conter": list,
    "vegetariano": bool,
    "vegano": bool,
    "sem_gluten": bool,
    "sem_lactose": bool,
}
CATEGORIAS = {"entrada", "prato_principal", "acompanhamento", "salada", "sobremesa"}
# Temas reservados para o desafio ao vivo e para os casos de teste
# (ver dados/LEIAME_dados.md). Aplicados ao texto normalizado.
TEMAS_RESERVADOS = {
    "pix": r"pix",
    "pagamento": r"pagamentos?",
    "delivery": r"delivery",
    "entrega": r"entreg\w*",
    "onibus": r"onibus",
}
EMOJI_PERMITIDO = "\U0001F30A"  # 🌊
FAIXAS_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿]")
PADRAO_HORA = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
PADRAO_ID = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")


def normalizar(texto):
    """Minusculas, sem acento, sem pontuacao e com espacos simples."""
    texto = unicodedata.normalize("NFKD", texto.lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^\w\s]", " ", texto)
    return " ".join(texto.split())


def minutos(hora):
    """Converte 'HH:MM' em minutos desde a meia-noite."""
    horas, mins = hora.split(":")
    return int(horas) * 60 + int(mins)


def percorrer(no, caminho="$"):
    """Gera (caminho, chave, valor) para todo o JSON."""
    if isinstance(no, dict):
        for chave, valor in no.items():
            yield caminho, chave, valor
            yield from percorrer(valor, f"{caminho}.{chave}")
    elif isinstance(no, list):
        for indice, valor in enumerate(no):
            yield from percorrer(valor, f"{caminho}[{indice}]")


def textos(no):
    """Gera todas as strings (chaves e valores) do JSON."""
    if isinstance(no, dict):
        for chave, valor in no.items():
            yield chave
            yield from textos(valor)
    elif isinstance(no, list):
        for valor in no:
            yield from textos(valor)
    elif isinstance(no, str):
        yield no


def checar_formato(bruto, erros):
    """Indentacao com espacos em multiplos de 2 e sem tabulacao."""
    for numero, linha in enumerate(bruto.splitlines(), start=1):
        recuo = linha[: len(linha) - len(linha.lstrip())]
        if "\t" in recuo:
            erros.append(f"linha {numero}: tabulacao na indentacao")
        elif len(recuo) % 2:
            erros.append(f"linha {numero}: indentacao nao e multipla de 2")


def checar_chaves(base, erros):
    """Chaves em portugues sem acento (ASCII, minusculas, snake_case)."""
    for caminho, chave, _ in percorrer(base):
        if not PADRAO_ID.match(chave):
            erros.append(f"{caminho}: chave '{chave}' fora do padrao snake_case sem acento")


def checar_cardapio(base, ids_alergenicos, erros):
    """Quantidade, ids, campos, alergenicos e coerencia dos booleanos."""
    cardapio = base.get("cardapio")
    if not isinstance(cardapio, list):
        erros.append("cardapio: ausente ou nao e lista")
        return []
    if len(cardapio) != TOTAL_PRATOS:
        erros.append(f"cardapio: {len(cardapio)} pratos, esperado {TOTAL_PRATOS}")

    contagem_ids = Counter(prato.get("id") for prato in cardapio if isinstance(prato, dict))
    for id_prato, vezes in contagem_ids.items():
        if vezes > 1:
            erros.append(f"cardapio: id '{id_prato}' repetido {vezes} vezes")

    for indice, prato in enumerate(cardapio):
        if not isinstance(prato, dict):
            erros.append(f"cardapio[{indice}]: nao e objeto")
            continue
        rotulo = prato.get("id", f"cardapio[{indice}]")
        for campo, tipo in CAMPOS_PRATO.items():
            valor = prato.get(campo)
            # bool e subclasse de int: nao aceitar True como numero.
            if not isinstance(valor, tipo) or (tipo is not bool and isinstance(valor, bool)):
                erros.append(f"{rotulo}: campo '{campo}' ausente ou com tipo errado")
        if any(not isinstance(prato.get(c), CAMPOS_PRATO[c]) for c in CAMPOS_PRATO):
            continue

        if not PADRAO_ID.match(prato["id"]):
            erros.append(f"{rotulo}: id nao esta em snake_case")
        if prato["categoria"] not in CATEGORIAS:
            erros.append(f"{rotulo}: categoria '{prato['categoria']}' invalida")
        if prato["preco"] <= 0:
            erros.append(f"{rotulo}: preco deve ser positivo")
        if prato["serve_pessoas"] < 1:
            erros.append(f"{rotulo}: serve_pessoas deve ser >= 1")
        if not prato["sinonimos"]:
            erros.append(f"{rotulo}: sinonimos vazio")

        alerg = set(prato["alergenicos"])
        contem = set(prato["pode_conter"])
        for id_alerg in sorted((alerg | contem) - ids_alergenicos):
            erros.append(f"{rotulo}: alergenico '{id_alerg}' nao existe em 'alergenicos'")
        for id_alerg in sorted(alerg & contem):
            erros.append(f"{rotulo}: '{id_alerg}' esta em alergenicos e em pode_conter")

        # Coerencia: "sem" exige ausencia tambem em pode_conter (criterio seguro).
        if prato["sem_gluten"] != ("trigo_gluten" not in alerg | contem):
            erros.append(f"{rotulo}: sem_gluten incoerente com trigo_gluten")
        if prato["sem_lactose"] != ("leite" not in alerg | contem):
            erros.append(f"{rotulo}: sem_lactose incoerente com leite")
        if prato["vegetariano"] and alerg & ANIMAIS_MARINHOS:
            erros.append(f"{rotulo}: vegetariano=true com {sorted(alerg & ANIMAIS_MARINHOS)}")
        if prato["vegano"] and alerg & DE_ORIGEM_ANIMAL:
            erros.append(f"{rotulo}: vegano=true com {sorted(alerg & DE_ORIGEM_ANIMAL)}")
        if prato["vegano"] and not prato["vegetariano"]:
            erros.append(f"{rotulo}: vegano=true exige vegetariano=true")
    return cardapio


def checar_alergenicos(base, erros):
    """Os 11 alergenicos obrigatorios, com id, nome, sinonimos e aviso."""
    secao = base.get("alergenicos")
    if not isinstance(secao, dict):
        erros.append("alergenicos: ausente ou nao e objeto")
        return set()
    if not str(secao.get("aviso_padrao", "")).strip():
        erros.append("alergenicos: aviso_padrao ausente")
    itens = secao.get("itens", {})
    for id_alerg in ALERGENICOS_OBRIGATORIOS:
        if id_alerg not in itens:
            erros.append(f"alergenicos: falta '{id_alerg}'")
    for chave, item in itens.items():
        if item.get("id") != chave:
            erros.append(f"alergenicos.{chave}: id interno diferente da chave")
        if not item.get("nome") or not item.get("sinonimos"):
            erros.append(f"alergenicos.{chave}: nome ou sinonimos vazio")
        for sinonimo in item.get("sinonimos", []):
            if normalizar(sinonimo).startswith("fruto"):
                erros.append(f"alergenicos.{chave}: 'frutos do mar' nao pode ser sinonimo")
    for termo in secao.get("termos_ambiguos", []):
        for id_alerg in termo.get("ids", []):
            if id_alerg not in itens:
                erros.append(f"termos_ambiguos '{termo.get('termo')}': id '{id_alerg}' inexistente")
    return set(itens)


def checar_funcionamento(base, erros):
    """Segunda fechada, demais dias com turnos HH:MM coerentes."""
    dias = base.get("funcionamento", {}).get("dias", {})
    turnos = []
    for dia in DIAS:
        info = dias.get(dia)
        if not isinstance(info, dict):
            erros.append(f"funcionamento: falta o dia '{dia}'")
            continue
        if dia == "segunda" and (info.get("aberto") or info.get("almoco") or info.get("jantar")):
            erros.append("funcionamento: segunda-feira deve estar FECHADO")
        if info.get("aberto") and not (info.get("almoco") or info.get("jantar")):
            erros.append(f"funcionamento.{dia}: aberto sem nenhum turno")
        for turno in ("almoco", "jantar"):
            faixa = info.get(turno)
            if faixa is None:
                continue
            abre, fecha = faixa.get("abre", ""), faixa.get("fecha", "")
            if not (PADRAO_HORA.match(abre) and PADRAO_HORA.match(fecha)):
                erros.append(f"funcionamento.{dia}.{turno}: horario fora do formato HH:MM")
            elif minutos(abre) >= minutos(fecha):
                erros.append(f"funcionamento.{dia}.{turno}: abre >= fecha")
            else:
                turnos.append((dia, turno, minutos(fecha) - minutos(abre)))
    if not str(base.get("funcionamento", {}).get("observacao_feriados", "")).strip():
        erros.append("funcionamento: observacao_feriados ausente")
    return turnos


def checar_reserva(base, turnos, erros):
    """max_pessoas, antecedencia, janela e politicas."""
    reserva = base.get("reserva", {})
    if reserva.get("max_pessoas") != MAX_PESSOAS:
        erros.append(f"reserva: max_pessoas = {reserva.get('max_pessoas')}, esperado {MAX_PESSOAS}")
    if reserva.get("antecedencia_minima_horas") != 1:
        erros.append("reserva: antecedencia_minima_horas deve ser 1")
    folga = reserva.get("janela", {}).get("ultima_reserva_minutos_antes_fechar")
    if not isinstance(folga, int) or folga < 0:
        erros.append("reserva: janela.ultima_reserva_minutos_antes_fechar invalida")
    else:
        for dia, turno, duracao in turnos:
            if folga >= duracao:
                erros.append(f"reserva: janela vazia em {dia}/{turno}")
    for campo in ("tolerancia_atraso_minutos", "politica_alteracao", "politica_cancelamento"):
        if not reserva.get(campo):
            erros.append(f"reserva: campo '{campo}' ausente")


def checar_respostas(base, erros):
    """Intencoes obrigatorias, 2-3 respostas fixas e uso de emoji."""
    intencoes = base.get("intencoes", [])
    nomes = [item.get("intencao") for item in intencoes]
    for nome in INTENCOES_OBRIGATORIAS:
        if nome not in nomes:
            erros.append(f"intencoes: falta '{nome}'")
    for nome, vezes in Counter(nomes).items():
        if vezes > 1:
            erros.append(f"intencoes: '{nome}' repetida")
    for item in intencoes:
        nome = item.get("intencao")
        if not isinstance(item.get("frases"), list):
            erros.append(f"intencoes.{nome}: 'frases' deve ser lista")
        respostas = item.get("respostas_fixas", [])
        if nome in INTENCOES_OBRIGATORIAS and not 2 <= len(respostas) <= 3:
            erros.append(f"intencoes.{nome}: esperado 2 a 3 respostas_fixas")
    for chave in ("fallback", "esclarecimento", "encaminhamento_humano"):
        if not base.get(chave):
            erros.append(f"'{chave}' ausente ou vazio")

    for texto in textos(base):
        emojis = FAIXAS_EMOJI.findall(texto)
        if any(e != EMOJI_PERMITIDO for e in emojis):
            erros.append(f"emoji nao permitido em '{texto[:50]}'")
        if texto.count(EMOJI_PERMITIDO) > 1:
            erros.append(f"mais de um emoji em '{texto[:50]}'")


def checar_temas(base, erros):
    """Nenhuma mencao a temas reservados em chaves ou valores."""
    for texto in textos(base):
        chave = normalizar(texto)
        for tema, padrao in TEMAS_RESERVADOS.items():
            if re.search(rf"\b{padrao}\b", chave):
                erros.append(f"tema reservado '{tema}' em '{texto[:60]}'")


def checar(caminho):
    """Valida a base e devolve (lista de erros, resumo)."""
    erros = []
    resumo = {}
    try:
        bruto = Path(caminho).read_text(encoding="utf-8")
        base = json.loads(bruto)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"nao foi possivel ler {caminho}: {exc}"], resumo
    if not isinstance(base, dict):
        return ["raiz do JSON deve ser um objeto"], resumo

    checar_formato(bruto, erros)
    checar_chaves(base, erros)
    ids_alergenicos = checar_alergenicos(base, erros)
    cardapio = checar_cardapio(base, ids_alergenicos, erros)
    turnos = checar_funcionamento(base, erros)
    checar_reserva(base, turnos, erros)
    checar_respostas(base, erros)
    checar_temas(base, erros)

    pratos = [p for p in cardapio if isinstance(p, dict)]
    resumo = {
        "pratos": len(pratos),
        "por categoria": dict(sorted(Counter(p.get("categoria") for p in pratos).items())),
        "vegetarianos": sum(bool(p.get("vegetariano")) for p in pratos),
        "veganos": sum(bool(p.get("vegano")) for p in pratos),
        "sem gluten": sum(bool(p.get("sem_gluten")) for p in pratos),
        "sem lactose": sum(bool(p.get("sem_lactose")) for p in pratos),
        "alergenicos cadastrados": len(ids_alergenicos),
        "turnos de funcionamento": len(turnos),
        "intencoes": len(base.get("intencoes", [])),
    }
    return erros, resumo


def main(argv):
    caminho = Path(argv[1]) if len(argv) > 1 else CAMINHO_PADRAO
    erros, resumo = checar(caminho)

    print(f"Arquivo: {caminho}")
    for chave, valor in resumo.items():
        print(f"  {chave:<25} {valor}")

    if erros:
        print(f"\n{len(erros)} erro(s) encontrado(s):")
        for erro in erros:
            print(f"  - {erro}")
        return 1
    print("\nNenhum erro encontrado.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
