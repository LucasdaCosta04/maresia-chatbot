"""Testes do pre-processamento usado pelo classificador de intencoes."""

import pytest

from chatbot.preprocessamento import ABREVIACOES, preprocessar


def test_minusculas():
    assert preprocessar("QUERO RESERVAR") == "quero reservar"


def test_remove_acentos():
    assert preprocessar("Você já está aí? Não!") == "voce ja esta ai nao"


def test_cedilha_vira_c():
    assert preprocessar("Açaí e PREÇO") == "acai e preco"


@pytest.mark.parametrize(
    "abreviacao, esperado",
    [(abrev, completo) for abrev, completo in ABREVIACOES.items()],
)
def test_cada_abreviacao_e_expandida(abreviacao, esperado):
    assert preprocessar(f"xx {abreviacao} yy") == f"xx {esperado} yy"


def test_abreviacao_no_inicio_e_no_fim():
    assert preprocessar("vcs abrem hj") == "voces abrem hoje"


def test_abreviacao_colada_em_pontuacao():
    assert preprocessar("vc abre hj?") == "voce abre hoje"


def test_p_barra_vira_para():
    assert preprocessar("mesa p/ 4") == "mesa para num"


def test_p_barra_colado_na_palavra_seguinte():
    assert preprocessar("reserva p/mim") == "reserva para mim"


def test_q_nao_e_trocado_dentro_de_quero():
    assert preprocessar("quero q vc reserve") == "quero que voce reserve"


@pytest.mark.parametrize("palavra", ["quero", "pratos", "prazo", "obgd", "tdo", "vcz"])
def test_abreviacao_nao_casa_dentro_de_palavra(palavra):
    assert preprocessar(palavra) == palavra


def test_qnto_tem_prioridade_sobre_qnt():
    assert preprocessar("qnto custa") == "quanto custa"


def test_oq_vira_duas_palavras():
    assert preprocessar("oq tem de sobremesa") == "o que tem de sobremesa"


def test_numero_simples():
    assert preprocessar("somos 4 pessoas") == "somos num pessoas"


def test_numero_com_varios_digitos():
    assert preprocessar("mesa para 12") == "mesa para num"


def test_horario_com_dois_pontos():
    assert preprocessar("às 19:30") == "as num"


def test_horario_com_h():
    assert preprocessar("às 20h") == "as num h"


def test_numero_decimal():
    assert preprocessar("custa 2,5 ou 3.5") == "custa num ou num"


def test_exemplo_completo():
    assert preprocessar("mesa p/ 4 as 20h") == "mesa para num as num h"


def test_remove_emojis():
    assert preprocessar("oi 😀🦐 tudo bem? 🌊") == "oi tudo bem"


def test_remove_pontuacao():
    assert preprocessar("Olá!!! Tem moqueca?? (sem coco), ok...") == "ola tem moqueca sem coco ok"


def test_colapsa_espacos():
    assert preprocessar("  quero \t reservar \n  mesa  ") == "quero reservar mesa"


def test_texto_vazio():
    assert preprocessar("") == ""


def test_so_simbolos_vira_vazio():
    assert preprocessar("?!... 😀") == ""


def test_mantem_stopwords():
    resultado = preprocessar("a moqueca de peixe o camarao").split()
    assert "a" in resultado
    assert "de" in resultado
    assert "o" in resultado
