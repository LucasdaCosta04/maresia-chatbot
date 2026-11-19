"""Testes do script de treino (treinar.py)."""

import csv

from chatbot.config import CAMINHO_DATASET
from chatbot.modelo import carregar_modelo, classificar
from treinar import treinar


def test_treinar_salva_modelo_e_devolve_metricas(tmp_path):
    saida = tmp_path / "modelos" / "classificador.joblib"
    metricas = treinar(caminho_saida=saida, verbose=False)

    assert saida.exists()
    assert metricas["caminho_modelo"] == saida
    assert 0.0 <= metricas["acuracia_media"] <= 1.0
    assert metricas["acuracia_desvio"] >= 0.0
    assert 0.0 <= metricas["f1_macro"] <= 1.0

    with open(CAMINHO_DATASET, encoding="utf-8", newline="") as arquivo:
        n_linhas = sum(1 for _ in csv.DictReader(arquivo))
    assert metricas["n_frases"] == n_linhas

    modelo = carregar_modelo(saida)
    assert classificar(modelo, "quero reservar uma mesa").intencao == "reserva"


def test_treinar_silencioso_nao_imprime(tmp_path, capsys):
    treinar(caminho_saida=tmp_path / "m.joblib", verbose=False)
    assert capsys.readouterr().out == ""
