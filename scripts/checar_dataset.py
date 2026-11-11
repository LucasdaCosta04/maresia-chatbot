"""Valida o dataset de intencoes (dados/intencoes_treino.csv).

Verifica cabecalho, rotulos permitidos, frases vazias, duplicatas apos
normalizacao e temas reservados. Imprime a contagem por classe.
Retorna codigo de saida 1 se encontrar algum erro.

Uso: python scripts/checar_dataset.py [caminho_do_csv]
"""

import csv
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

CAMINHO_PADRAO = Path(__file__).resolve().parent.parent / "dados" / "intencoes_treino.csv"
CABECALHO_ESPERADO = ["frase", "intencao"]
ROTULOS_PERMITIDOS = (
    "cardapio_alergenicos",
    "reserva",
    "horario_localizacao",
    "fora_escopo",
)
# Temas deixados fora do treino de proposito (ver dados/LEIAME_dados.md).
# Cada padrao e aplicado ao texto ja normalizado, como palavra inteira.
TEMAS_RESERVADOS = {
    "clima": r"clima",
    "chuva": r"chuv\w*",
    "delivery": r"delivery",
    "entrega": r"entreg\w*",
    "pix": r"pix",
    "pagamento": r"pagamentos?",
    "futebol": r"futebol",
    "receita": r"receitas?",
    "onibus": r"onibus",
}


def normalizar(texto):
    """Minusculas, sem acento, sem pontuacao e com espacos simples."""
    texto = unicodedata.normalize("NFKD", texto.lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^\w\s]", " ", texto)
    return " ".join(texto.split())


def checar(caminho):
    """Valida o CSV e devolve (lista de erros, contagem por classe)."""
    erros = []
    contagem = Counter()
    vistas = {}

    try:
        with open(caminho, encoding="utf-8", newline="") as arquivo:
            linhas = list(csv.reader(arquivo))
    except (OSError, UnicodeDecodeError) as exc:
        return [f"nao foi possivel ler {caminho}: {exc}"], contagem

    if not linhas:
        return ["arquivo vazio"], contagem

    cabecalho = [campo.strip() for campo in linhas[0]]
    if cabecalho != CABECALHO_ESPERADO:
        erros.append(f"linha 1: cabecalho {linhas[0]} != {CABECALHO_ESPERADO}")

    for numero, linha in enumerate(linhas[1:], start=2):
        if len(linha) != 2:
            erros.append(f"linha {numero}: esperado 2 colunas, encontrado {len(linha)}")
            continue
        frase, intencao = linha
        if not frase.strip():
            erros.append(f"linha {numero}: frase vazia")
            continue
        if intencao not in ROTULOS_PERMITIDOS:
            erros.append(f"linha {numero}: rotulo invalido '{intencao}'")
        else:
            contagem[intencao] += 1

        chave = normalizar(frase)
        if chave in vistas:
            erros.append(
                f"linha {numero}: duplicata da linha {vistas[chave]} apos normalizar ('{frase}')"
            )
        else:
            vistas[chave] = numero

        for tema, padrao in TEMAS_RESERVADOS.items():
            if re.search(rf"\b{padrao}\b", chave):
                erros.append(f"linha {numero}: tema reservado '{tema}' em '{frase}'")

    return erros, contagem


def main(argv):
    caminho = Path(argv[1]) if len(argv) > 1 else CAMINHO_PADRAO
    erros, contagem = checar(caminho)

    print(f"Arquivo: {caminho}")
    print("Contagem por classe:")
    for rotulo in ROTULOS_PERMITIDOS:
        print(f"  {rotulo:<22} {contagem[rotulo]:>4}")
    print(f"  {'total':<22} {sum(contagem.values()):>4}")

    if erros:
        print(f"\n{len(erros)} erro(s) encontrado(s):")
        for erro in erros:
            print(f"  - {erro}")
        return 1
    print("\nNenhum erro encontrado.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
