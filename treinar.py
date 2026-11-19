"""Treina o classificador de intenções da Maresia e salva o modelo em modelos/.

Uso:
    python treinar.py

Etapas:
1. carrega o dataset (dados/intencoes_treino.csv) e mostra a contagem por intenção;
2. faz validação cruzada estratificada para estimar o desempenho;
3. treina o modelo final com o dataset inteiro e salva o .joblib.
"""

from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import StratifiedKFold, cross_val_predict, cross_validate

from chatbot.config import ARQUIVO_MODELO, CAMINHO_DATASET, FOLDS_VALIDACAO, SEMENTE
from chatbot.modelo import (
    carregar_dataset,
    construir_pipeline,
    salvar_modelo,
    treinar_modelo,
)


def _formatar_matriz(matriz, rotulos: list[str]) -> str:
    """Monta a matriz de confusão como texto, com os nomes das intenções.

    Linhas = intenção real; colunas = intenção prevista.
    """
    largura_rotulo = max(len(r) for r in rotulos)
    largura_celula = max(largura_rotulo, max(len(str(v)) for v in matriz.flat))
    cabecalho = " " * largura_rotulo + " | " + " ".join(
        r.rjust(largura_celula) for r in rotulos
    )
    linhas = [cabecalho, "-" * len(cabecalho)]
    for rotulo, valores in zip(rotulos, matriz):
        linhas.append(
            rotulo.ljust(largura_rotulo) + " | "
            + " ".join(str(v).rjust(largura_celula) for v in valores)
        )
    return "\n".join(linhas)


def treinar(
    caminho_dataset=CAMINHO_DATASET,
    caminho_saida=ARQUIVO_MODELO,
    verbose: bool = True,
) -> dict:
    """Valida, treina e salva o classificador. Devolve um dict de métricas."""

    def mostrar(texto: str = "") -> None:
        if verbose:
            print(texto)

    # a) Dataset
    frases, intencoes = carregar_dataset(caminho_dataset)
    contagem = Counter(intencoes)
    mostrar(f"Dataset: {caminho_dataset}")
    mostrar(f"Total de frases: {len(frases)}")
    for intencao, quantidade in sorted(contagem.items()):
        mostrar(f"  {intencao}: {quantidade}")

    # b) Validação cruzada estratificada: cada fold mantém a proporção das
    # intenções. construir_pipeline() é passado ainda sem treino, e o
    # scikit-learn clona e treina um pipeline novo em cada fold. Assim o
    # TF-IDF só aprende o vocabulário das frases de treino daquele fold
    # (sem vazamento de dados para o fold de teste).
    folds = StratifiedKFold(n_splits=FOLDS_VALIDACAO, shuffle=True, random_state=SEMENTE)
    resultados = cross_validate(
        construir_pipeline(), frases, intencoes,
        cv=folds, scoring=["accuracy", "f1_macro"],
    )
    acuracias = resultados["test_accuracy"]
    acuracia_media = float(np.mean(acuracias))
    acuracia_desvio = float(np.std(acuracias))
    f1_macro = float(np.mean(resultados["test_f1_macro"]))

    # c) Relatório. cross_val_predict usa os mesmos folds (mesma semente),
    # então cada frase é prevista por um modelo que não a viu no treino.
    previstas = cross_val_predict(construir_pipeline(), frases, intencoes, cv=folds)
    rotulos = sorted(contagem)

    mostrar()
    mostrar(f"Validação cruzada estratificada ({FOLDS_VALIDACAO} folds)")
    mostrar(
        "  Acurácia por fold: "
        + ", ".join(f"{a:.3f}" for a in acuracias)
    )
    mostrar(f"  Acurácia: {acuracia_media:.3f} ± {acuracia_desvio:.3f}")
    mostrar(f"  F1-macro: {f1_macro:.3f}")
    mostrar()
    mostrar("Relatório por intenção (previsões fora do fold de treino):")
    mostrar(classification_report(intencoes, previstas, labels=rotulos, digits=3))
    mostrar("Matriz de confusão (linhas = real, colunas = prevista):")
    mostrar(_formatar_matriz(confusion_matrix(intencoes, previstas, labels=rotulos), rotulos))

    # d) Modelo final com o dataset inteiro.
    modelo = treinar_modelo(frases, intencoes)
    caminho = salvar_modelo(modelo, caminho_saida)

    # e) Métricas
    return {
        "acuracia_media": acuracia_media,
        "acuracia_desvio": acuracia_desvio,
        "f1_macro": f1_macro,
        "n_frases": len(frases),
        "caminho_modelo": Path(caminho),
    }


if __name__ == "__main__":
    metricas = treinar()
    print()
    print(f"Modelo treinado com {metricas['n_frases']} frases e salvo em: {metricas['caminho_modelo']}")
