"""Valida os casos de teste (dados/casos_teste.csv).

Verifica cabecalho, quantidade de linhas, ids, categorias e a distribuicao
combinada, tipos e intencoes esperados. Depois mede a similaridade de cada
mensagem com todas as frases do treino (TF-IDF de n-gramas de caracteres 2-5
sobre o texto normalizado, cosseno) e imprime a frase mais parecida.
Retorna codigo de saida 1 se houver erro, copia normalizada exata do treino
ou similaridade acima do limite.

Uso: python scripts/checar_casos_teste.py [casos_teste.csv] [intencoes_treino.csv]
"""

import csv
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
CAMINHO_CASOS = _RAIZ / "dados" / "casos_teste.csv"
CAMINHO_TREINO = _RAIZ / "dados" / "intencoes_treino.csv"

CABECALHO_ESPERADO = [
    "id",
    "categoria",
    "contexto",
    "mensagem",
    "tipo_esperado",
    "intencao_esperada",
    "resposta_deve_conter",
    "justificativa",
]
TOTAL_CASOS = 34
DISTRIBUICAO = {
    "esperada": 6,
    "reformulacao": 6,
    "ambigua": 4,
    "fora_escopo": 6,
    "limite": 5,
    "contexto": 3,
    "regra_negocio": 2,
    "encaminhamento": 2,
}
# Categorias que precisam de 2 casos por intencao de dominio.
CATEGORIAS_POR_INTENCAO = ("esperada", "reformulacao")
INTENCOES_DOMINIO = ("cardapio_alergenicos", "reserva", "horario_localizacao")
TIPOS_VALIDOS = (
    "aceita",
    "regra",
    "reserva",
    "esclarecimento",
    "abstencao",
    "fallback",
    "encaminhamento",
)
INTENCOES_VALIDAS = INTENCOES_DOMINIO + ("fora_escopo", "")
SEPARADOR_CONTEXTO = " || "
LIMITE_SIMILARIDADE = 0.85


def normalizar(texto):
    """Minusculas, sem acento, sem pontuacao e com espacos simples."""
    texto = unicodedata.normalize("NFKD", texto.lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^\w\s]", " ", texto)
    return " ".join(texto.split())


def ler_casos(caminho=CAMINHO_CASOS):
    """Le o CSV de casos e devolve (cabecalho, lista de dicionarios)."""
    with open(caminho, encoding="utf-8", newline="") as arquivo:
        leitor = csv.DictReader(arquivo)
        return list(leitor.fieldnames or []), list(leitor)


def ler_frases_treino(caminho=CAMINHO_TREINO):
    """Le apenas a coluna frase do dataset de treino."""
    with open(caminho, encoding="utf-8", newline="") as arquivo:
        return [linha["frase"] for linha in csv.DictReader(arquivo)]


def validar(cabecalho, casos):
    """Valida estrutura e distribuicao dos casos. Devolve a lista de erros."""
    erros = []
    if cabecalho != CABECALHO_ESPERADO:
        erros.append(f"cabecalho {cabecalho} != {CABECALHO_ESPERADO}")
        return erros

    if len(casos) != TOTAL_CASOS:
        erros.append(f"esperado {TOTAL_CASOS} casos, encontrado {len(casos)}")

    ids = [caso["id"] for caso in casos]
    repetidos = sorted(i for i, n in Counter(ids).items() if n > 1)
    if repetidos:
        erros.append(f"ids repetidos: {repetidos}")
    esperados = [f"T{n:02d}" for n in range(1, TOTAL_CASOS + 1)]
    if sorted(ids) != esperados:
        erros.append("ids devem ser exatamente T01..T34")

    por_categoria = Counter()
    por_intencao = Counter()
    for caso in casos:
        rotulo = caso["id"] or "?"
        if None in caso.values() or None in caso:
            erros.append(f"{rotulo}: numero de colunas diferente do cabecalho")
            continue
        categoria = caso["categoria"]
        if categoria not in DISTRIBUICAO:
            erros.append(f"{rotulo}: categoria invalida '{categoria}'")
        por_categoria[categoria] += 1

        if not caso["mensagem"].strip():
            erros.append(f"{rotulo}: mensagem vazia")
        if not caso["justificativa"].strip():
            erros.append(f"{rotulo}: justificativa vazia")

        tipos = caso["tipo_esperado"].split("|")
        invalidos = [t for t in tipos if t not in TIPOS_VALIDOS]
        if invalidos or len(set(tipos)) != len(tipos):
            erros.append(f"{rotulo}: tipo_esperado invalido '{caso['tipo_esperado']}'")

        intencao = caso["intencao_esperada"]
        if intencao not in INTENCOES_VALIDAS:
            erros.append(f"{rotulo}: intencao_esperada invalida '{intencao}'")
        if categoria in CATEGORIAS_POR_INTENCAO:
            por_intencao[(categoria, intencao)] += 1

        trecho = caso["resposta_deve_conter"]
        if trecho != normalizar_trecho(trecho):
            erros.append(
                f"{rotulo}: resposta_deve_conter deve ser minusculo e sem acento ('{trecho}')"
            )

        contexto = caso["contexto"]
        if contexto and any(not p.strip() for p in contexto.split(SEPARADOR_CONTEXTO)):
            erros.append(f"{rotulo}: contexto com mensagem vazia")
        if categoria == "contexto" and not contexto:
            erros.append(f"{rotulo}: categoria contexto sem mensagens anteriores")

    for categoria, quantidade in DISTRIBUICAO.items():
        if por_categoria[categoria] != quantidade:
            erros.append(
                f"categoria {categoria}: esperado {quantidade}, encontrado {por_categoria[categoria]}"
            )
    for categoria in CATEGORIAS_POR_INTENCAO:
        for intencao in INTENCOES_DOMINIO:
            if por_intencao[(categoria, intencao)] != 2:
                erros.append(
                    f"categoria {categoria}: esperado 2 casos de {intencao}, "
                    f"encontrado {por_intencao[(categoria, intencao)]}"
                )
    return erros


def normalizar_trecho(texto):
    """Minusculas e sem acento, preservando pontuacao (ex.: '23:30')."""
    texto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


def medir_similaridade(mensagens, frases_treino):
    """Para cada mensagem, devolve (frase de treino mais parecida, cosseno).

    TF-IDF de n-gramas de caracteres 2-5 sobre o texto normalizado,
    ajustado sobre treino + mensagens.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    treino_norm = [normalizar(f) for f in frases_treino]
    casos_norm = [normalizar(m) for m in mensagens]
    vetorizador = TfidfVectorizer(analyzer="char", ngram_range=(2, 5))
    vetorizador.fit(treino_norm + casos_norm)
    matriz = cosine_similarity(
        vetorizador.transform(casos_norm), vetorizador.transform(treino_norm)
    )
    resultado = []
    for linha in matriz:
        indice = int(linha.argmax())
        resultado.append((frases_treino[indice], float(linha[indice])))
    return resultado


def checar_copias(ids, mensagens, frases_treino, limite=LIMITE_SIMILARIDADE):
    """Erros de copia normalizada exata e de similaridade acima do limite.

    Devolve (erros, lista de (frase mais parecida, cosseno) por mensagem).
    """
    treino_norm = {normalizar(f) for f in frases_treino}
    similares = medir_similaridade(mensagens, frases_treino)
    erros = []
    for rotulo, mensagem, (_, valor) in zip(ids, mensagens, similares):
        if normalizar(mensagem) in treino_norm:
            erros.append(f"{rotulo}: copia normalizada de frase do treino ('{mensagem}')")
        elif valor > limite:
            erros.append(f"{rotulo}: similaridade {valor:.3f} > {limite} ('{mensagem}')")
    return erros, similares


def main(argv):
    caminho_casos = Path(argv[1]) if len(argv) > 1 else CAMINHO_CASOS
    caminho_treino = Path(argv[2]) if len(argv) > 2 else CAMINHO_TREINO

    try:
        cabecalho, casos = ler_casos(caminho_casos)
        frases_treino = ler_frases_treino(caminho_treino)
    except (OSError, UnicodeDecodeError, KeyError) as exc:
        print(f"Erro ao ler os arquivos: {exc}")
        return 1

    erros = validar(cabecalho, casos)
    contagem = Counter(caso["categoria"] for caso in casos)
    print(f"Arquivo: {caminho_casos}")
    print("Contagem por categoria:")
    for categoria in DISTRIBUICAO:
        print(f"  {categoria:<16} {contagem[categoria]:>3}")
    print(f"  {'total':<16} {len(casos):>3}")

    mensagens = [caso["mensagem"] or "" for caso in casos]
    ids = [caso["id"] for caso in casos]
    erros_copia, similares = checar_copias(ids, mensagens, frases_treino)
    erros += erros_copia

    print(f"\nSimilaridade com o treino ({caminho_treino.name}, {len(frases_treino)} frases):")
    for caso, (frase, valor) in zip(casos, similares):
        print(f"  {caso['id']}  {valor:.3f}  {caso['mensagem'][:60]!r}")
        print(f"         ~ {frase[:60]!r}")
    valores = [v for _, v in similares]
    if valores:
        print(f"\n  media  {sum(valores) / len(valores):.3f}")
        print(f"  maximo {max(valores):.3f} (limite {LIMITE_SIMILARIDADE})")

    if erros:
        print(f"\n{len(erros)} erro(s) encontrado(s):")
        for erro in erros:
            print(f"  - {erro}")
        return 1
    print("\nNenhum erro encontrado.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
