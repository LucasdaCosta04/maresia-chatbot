"""Testes do avaliador (avaliar.py): estrutura das saidas, nao o numero de acertos."""

import csv
import json

import pytest

import avaliar
import chatbot.modelo as modelo_mod
from chatbot.config import LIMIAR_CONFIANCA
from chatbot.modelo import carregar_dataset, salvar_modelo, treinar_modelo
from treinar import treinar

ARQUIVOS = [
    "resultados_casos.csv",
    "matriz_testes.md",
    "resumo_metricas.json",
    "matriz_confusao.png",
    "limiar_confianca.csv",
    "limiar_confianca.png",
    "comparacao_abordagens.csv",
    "comparacao_abordagens.png",
    "verificacao_vazamento.csv",
]


@pytest.fixture(scope="session")
def caminho_modelo(tmp_path_factory):
    caminho = tmp_path_factory.mktemp("modelos") / "classificador.joblib"
    return salvar_modelo(treinar_modelo(*carregar_dataset()), caminho)


@pytest.fixture(scope="session")
def saida(caminho_modelo, tmp_path_factory):
    pasta = tmp_path_factory.mktemp("resultados")
    resumo = avaliar.gerar_resultados(caminho_modelo, pasta)
    return pasta, resumo


def _ler_csv(caminho):
    with open(caminho, encoding="utf-8", newline="") as arquivo:
        leitor = csv.DictReader(arquivo)
        return leitor.fieldnames, list(leitor)


def test_gera_todos_os_arquivos(saida):
    pasta, _ = saida
    for nome in ARQUIVOS:
        assert (pasta / nome).stat().st_size > 0, nome
    for nome in ARQUIVOS:
        if nome.endswith(".png"):
            assert (pasta / nome).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_resultados_casos_tem_34_linhas_e_colunas(saida):
    pasta, _ = saida
    colunas, linhas = _ler_csv(pasta / "resultados_casos.csv")
    assert colunas == avaliar.COLUNAS_CASOS
    assert len(linhas) == 34
    assert [l["id"] for l in linhas] == [f"T{n:02d}" for n in range(1, 35)]
    for linha in linhas:
        assert linha["passou"] in ("sim", "nao")
        assert (linha["passou"] == "nao") == bool(linha["motivo_falha"])
        assert linha["resposta"]


def test_resumo_json_valido_e_consistente(saida):
    pasta, resumo = saida
    dados = json.loads((pasta / "resumo_metricas.json").read_text(encoding="utf-8"))
    assert dados == resumo
    assert dados["casos"]["total"] == 34
    assert 0 <= dados["casos"]["acertos"] <= 34
    categorias = dados["por_categoria"]
    assert set(categorias) == set(avaliar.checar.DISTRIBUICAO)
    assert sum(c["acertos"] for c in categorias.values()) == dados["casos"]["acertos"]
    assert sum(c["total"] for c in categorias.values()) == 34
    vc = dados["validacao_cruzada"]
    assert 0 <= vc["acuracia_media"] <= 1 and 0 <= vc["f1_macro_media"] <= 1
    assert dados["data_referencia"] == "2026-11-18T18:00:00-03:00"
    assert dados["dataset"]["n_frases"] == len(carregar_dataset()[0])


def test_matriz_testes_lista_as_falhas(saida):
    pasta, resumo = saida
    texto = (pasta / "matriz_testes.md").read_text(encoding="utf-8")
    _, linhas = _ler_csv(pasta / "resultados_casos.csv")
    total = resumo["casos"]
    assert f"**{total['acertos']}/{total['total']}**" in texto
    for linha in linhas:
        if linha["passou"] == "nao":
            assert f"| {linha['id']} |" in texto


def test_limiar_varre_de_030_a_070_e_restaura(saida):
    pasta, _ = saida
    colunas, linhas = _ler_csv(pasta / "limiar_confianca.csv")
    assert colunas == ["limiar", "acertos", "total", "fallbacks", "abstencoes"]
    assert [float(l["limiar"]) for l in linhas] == pytest.approx(
        [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]
    )
    assert all(int(l["total"]) == 34 for l in linhas)
    assert modelo_mod.LIMIAR_CONFIANCA == LIMIAR_CONFIANCA


def test_varrer_limiar_restaura_mesmo_com_erro(caminho_modelo, monkeypatch):
    original = modelo_mod.LIMIAR_CONFIANCA
    monkeypatch.setattr(avaliar, "avaliar_casos", lambda *a, **k: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        avaliar.varrer_limiar(modelo_mod.carregar_modelo(caminho_modelo), [], base={})
    assert modelo_mod.LIMIAR_CONFIANCA == original


def test_comparacao_tem_4_abordagens_e_atual_bate_com_treinar(saida, tmp_path):
    pasta, resumo = saida
    colunas, linhas = _ler_csv(pasta / "comparacao_abordagens.csv")
    assert colunas == [
        "abordagem", "acuracia_media", "acuracia_desvio", "f1_macro_media", "f1_macro_desvio",
    ]
    assert len(linhas) == 4
    metricas = treinar(caminho_saida=tmp_path / "m.joblib", verbose=False)
    vc = resumo["validacao_cruzada"]
    assert vc["acuracia_media"] == pytest.approx(metricas["acuracia_media"], abs=1e-4)
    assert vc["acuracia_desvio"] == pytest.approx(metricas["acuracia_desvio"], abs=1e-4)
    assert vc["f1_macro_media"] == pytest.approx(metricas["f1_macro"], abs=1e-4)


def test_verificacao_vazamento(saida):
    pasta, _ = saida
    colunas, linhas = _ler_csv(pasta / "verificacao_vazamento.csv")
    assert colunas == [
        "id", "mensagem", "frase_treino_mais_parecida", "similaridade", "acima_do_limite",
    ]
    assert len(linhas) == 34
    assert all(0 <= float(l["similaridade"]) <= 1 for l in linhas)


def test_duas_execucoes_geram_arquivos_identicos(saida, caminho_modelo, tmp_path):
    pasta, _ = saida
    avaliar.gerar_resultados(caminho_modelo, tmp_path)
    for nome in ARQUIVOS:
        assert (tmp_path / nome).read_bytes() == (pasta / nome).read_bytes(), nome


def test_sem_modelo_sai_com_codigo_1(tmp_path, capsys):
    codigo = avaliar.main(tmp_path / "nao_existe.joblib", tmp_path / "saida")
    assert codigo == 1
    assert "python treinar.py" in capsys.readouterr().out
    assert not (tmp_path / "saida").exists()


def test_formatar_tabela_usa_virgula_decimal():
    resumo = {
        "por_categoria": {"esperada": {"acertos": 5, "total": 6}},
        "casos": {"acertos": 26, "total": 34},
    }
    tabela = avaliar.formatar_tabela(resumo)
    assert "26/34 = 76,5%" in tabela
    assert "5/6 = 83,3%" in tabela
