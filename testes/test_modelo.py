"""Testes do classificador de intencoes e da politica de decisao."""

import pytest

from chatbot.config import INTENCAO_FORA_ESCOPO
from chatbot.modelo import (
    Decisao,
    carregar_dataset,
    carregar_modelo,
    classificar,
    decidir,
    prever_probabilidades,
    salvar_modelo,
    treinar_modelo,
)

CARD = "cardapio_alergenicos"
RES = "reserva"
HOR = "horario_localizacao"
FORA = INTENCAO_FORA_ESCOPO


def _probs(card=0.0, res=0.0, hor=0.0, fora=0.0):
    return {CARD: card, RES: res, HOR: hor, FORA: fora}


# --- decidir: probabilidades montadas a mao, sem treinar ---------------------

def test_aceita_com_confianca_alta():
    decisao = decidir(_probs(res=0.80, card=0.10, hor=0.05, fora=0.05))
    assert isinstance(decisao, Decisao)
    assert decisao.tipo == "aceita"
    assert decisao.intencao == RES
    assert decisao.confianca == pytest.approx(0.80)
    assert decisao.candidatas == []


def test_aceita_no_limite_confianca_045_margem_015():
    decisao = decidir(_probs(res=0.45, card=0.30, hor=0.15, fora=0.10))
    assert decisao.tipo == "aceita"
    assert decisao.intencao == RES


def test_aceita_no_limite_com_diferenca_que_arredonda_para_baixo():
    # 0.60 - 0.45 da 0.14999999999999997 em ponto flutuante.
    decisao = decidir(_probs(res=0.60, card=0.45))
    assert decisao.tipo == "aceita"


def test_margem_014_nao_aceita():
    decisao = decidir(_probs(res=0.45, card=0.31, hor=0.14, fora=0.10))
    assert decisao.tipo != "aceita"
    assert decisao.tipo == "esclarecimento"


def test_confianca_044_nao_aceita():
    decisao = decidir(_probs(res=0.44, card=0.18, hor=0.18, fora=0.20))
    assert decisao.tipo != "aceita"


def test_abstencao_com_fora_escopo_no_topo():
    decisao = decidir(_probs(fora=0.95, res=0.03, card=0.01, hor=0.01))
    assert decisao.tipo == "abstencao"
    assert decisao.intencao == FORA
    assert decisao.candidatas == []


def test_abstencao_com_fora_escopo_no_topo_mesmo_com_confianca_baixa():
    decisao = decidir(_probs(fora=0.30, res=0.25, card=0.25, hor=0.20))
    assert decisao.tipo == "abstencao"


def test_esclarecimento_no_limite_soma_070():
    # Distribuicao real (soma 1): 0.40 + 0.30 = 0.70, margem 0.10.
    decisao = decidir(_probs(res=0.40, card=0.30, hor=0.20, fora=0.10))
    assert decisao.tipo == "esclarecimento"
    assert decisao.candidatas == [RES, CARD]


def test_soma_069_cai_no_fallback():
    decisao = decidir(_probs(res=0.40, card=0.29, hor=0.21, fora=0.10))
    assert decisao.tipo == "fallback"


# Os dois testes abaixo usam dicionarios que NAO somam 1 de proposito: com
# probabilidades normalizadas, soma >= 0.70 com 2a em 0.20 ou 0.19 sempre
# cai na regra (a). Aqui o fora_escopo alto derruba a margem da regra (a)
# para isolar o limite MIN_SEGUNDA_ESCLARECIMENTO da regra (c).

def test_esclarecimento_no_limite_soma_070_segunda_020():
    decisao = decidir(_probs(res=0.50, fora=0.40, card=0.20, hor=0.0))
    assert decisao.tipo == "esclarecimento"
    assert decisao.candidatas == [RES, CARD]


def test_segunda_019_cai_no_fallback():
    decisao = decidir(_probs(res=0.51, fora=0.41, card=0.19, hor=0.0))
    assert decisao.tipo == "fallback"


def test_fallback_com_probabilidades_espalhadas():
    decisao = decidir(_probs(res=0.28, card=0.26, hor=0.24, fora=0.22))
    assert decisao.tipo == "fallback"
    assert decisao.candidatas == []
    assert decisao.intencao == RES


def test_fora_escopo_nunca_entra_em_candidatas():
    # fora_escopo e o 2o mais provavel, mas so intencoes de dominio entram.
    decisao = decidir(_probs(res=0.42, fora=0.30, card=0.28, hor=0.0))
    assert decisao.tipo == "esclarecimento"
    assert FORA not in decisao.candidatas
    assert decisao.candidatas == [RES, CARD]


def test_decisao_guarda_as_probabilidades():
    probs = _probs(res=0.80, card=0.10, hor=0.05, fora=0.05)
    assert decidir(probs).probabilidades == probs


# --- modelo treinado com o dataset real --------------------------------------

@pytest.fixture(scope="module")
def modelo():
    frases, intencoes = carregar_dataset()
    return treinar_modelo(frases, intencoes)


def test_dataset_tem_as_quatro_intencoes():
    frases, intencoes = carregar_dataset()
    assert len(frases) == len(intencoes) > 0
    assert set(intencoes) == {CARD, RES, HOR, FORA}


@pytest.mark.parametrize(
    "texto, esperada",
    [
        ("quero reservar uma mesa para 4 pessoas", RES),
        ("vocês têm prato sem glúten?", CARD),
        ("que horas vocês abrem?", HOR),
    ],
)
def test_modelo_real_acerta_frases_claras(modelo, texto, esperada):
    probs = prever_probabilidades(modelo, texto)
    assert max(probs, key=probs.get) == esperada
    assert sum(probs.values()) == pytest.approx(1.0)
    assert set(probs) == {CARD, RES, HOR, FORA}


def test_classificar_devolve_decisao(modelo):
    decisao = classificar(modelo, "quero reservar uma mesa para 4 pessoas")
    assert isinstance(decisao, Decisao)
    assert decisao.intencao == RES


# --- salvar e carregar --------------------------------------------------------

def test_salvar_e_carregar(modelo, tmp_path):
    caminho = tmp_path / "sub" / "modelo.joblib"
    salvar_modelo(modelo, caminho)
    assert caminho.exists()
    carregado = carregar_modelo(caminho)
    texto = "que horas vocês abrem?"
    assert prever_probabilidades(carregado, texto) == pytest.approx(
        prever_probabilidades(modelo, texto)
    )


def test_carregar_modelo_inexistente_da_erro_claro(tmp_path):
    with pytest.raises(FileNotFoundError, match="python treinar.py"):
        carregar_modelo(tmp_path / "nao_existe.joblib")
