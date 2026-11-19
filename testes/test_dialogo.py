"""Testes do gerenciador de dialogo (regras, decisoes e encaminhamento)."""

import random

import pytest

import chatbot.dialogo as dialogo
from chatbot.config import MAX_FALHAS_SEGUIDAS
from chatbot.dialogo import (
    MENSAGENS_REGRAS,
    EstadoConversa,
    GerenciadorDialogo,
    Resposta,
    carregar_base,
)
from chatbot.modelo import Decisao, carregar_dataset, treinar_modelo

BASE = carregar_base()
RESPOSTAS = {item["intencao"]: item["respostas_fixas"] for item in BASE["intencoes"]}


@pytest.fixture(scope="module")
def modelo():
    return treinar_modelo(*carregar_dataset())


@pytest.fixture
def gerente(modelo):
    return GerenciadorDialogo(modelo, BASE, random.Random(0))


@pytest.fixture
def estado():
    return EstadoConversa()


def _decisoes_fixas(monkeypatch, *decisoes):
    """Faz o classificar() do dialogo devolver as decisoes dadas, em ordem."""
    fila = list(decisoes)
    monkeypatch.setattr(dialogo, "classificar", lambda modelo, texto: fila.pop(0))


def _decisao(tipo, intencao=None, candidatas=()):
    return Decisao(tipo, intencao, 0.5, list(candidatas), {})


# --- EstadoConversa -----------------------------------------------------------

def test_estado_reiniciar():
    estado = EstadoConversa(3, "reserva", ["reserva", "horario_localizacao"], {"pessoas": 4}, True)
    estado.reiniciar()
    assert estado == EstadoConversa()


# --- Regras prioritarias ------------------------------------------------------

@pytest.mark.parametrize(
    "mensagem",
    [
        "quero falar com um atendente",
        "Posso falar com um humano?",
        "chama o gerente",
        "quero falar com uma pessoa",
        "tem alguma pessoa de verdade ai?",
    ],
)
def test_regra_atendente(gerente, estado, mensagem):
    estado.falhas_seguidas = 1
    resposta = gerente.responder(mensagem, estado)
    assert resposta.tipo == "encaminhamento"
    assert resposta.texto in BASE["encaminhamento_humano"]
    assert estado.encaminhado is True
    assert estado.falhas_seguidas == 0


def test_mesa_para_uma_pessoa_nao_e_atendente(gerente, estado):
    resposta = gerente.responder("quero reservar mesa para uma pessoa", estado)
    assert resposta.tipo != "encaminhamento"


@pytest.mark.parametrize("mensagem", ["cancelar", "Cancela!", "deixa pra lá", "esquece", "esquece isso"])
def test_regra_cancelar_limpa_slots_e_esclarecimento(gerente, estado, mensagem):
    estado.slots = {"pessoas": 4}
    estado.esclarecimento = ["reserva", "horario_localizacao"]
    estado.falhas_seguidas = 1
    resposta = gerente.responder(mensagem, estado)
    assert resposta.tipo == "regra"
    assert resposta.texto == MENSAGENS_REGRAS["cancelar"]
    assert estado.slots == {}
    assert estado.esclarecimento is None
    assert estado.falhas_seguidas == 0


def test_cancelar_reserva_vai_para_o_classificador(gerente, estado):
    resposta = gerente.responder("quero cancelar minha reserva de sabado", estado)
    assert resposta.tipo == "aceita"
    assert resposta.intencao == "reserva"


@pytest.mark.parametrize("mensagem", ["ajuda", "Me ajuda", "o que vc faz?", "como funciona?", "menu"])
def test_regra_ajuda(gerente, estado, mensagem):
    resposta = gerente.responder(mensagem, estado)
    assert resposta.tipo == "regra"
    assert "cardápio e alergênicos" in resposta.texto
    assert "reservas" in resposta.texto
    assert "horário e localização" in resposta.texto


@pytest.mark.parametrize(
    "mensagem", ["oi", "Olá!", "bom dia", "Boa tarde!!", "boa noite", "e aí", "oi tudo bem?"]
)
def test_regra_saudacao(gerente, estado, mensagem):
    estado.falhas_seguidas = 1
    resposta = gerente.responder(mensagem, estado)
    assert resposta.tipo == "regra"
    assert resposta.texto.startswith("Olá! Eu sou a Maresia")
    assert estado.falhas_seguidas == 0


@pytest.mark.parametrize("mensagem", ["tchau", "obrigado!", "obg", "valeu", "até mais", "obrigada, tchau"])
def test_regra_despedida(gerente, estado, mensagem):
    resposta = gerente.responder(mensagem, estado)
    assert resposta.tipo == "regra"
    assert resposta.texto == MENSAGENS_REGRAS["despedida"]


def test_saudacao_com_pedido_vai_para_o_classificador(gerente, estado):
    resposta = gerente.responder("oi, quero reservar uma mesa", estado)
    assert resposta.tipo == "aceita"
    assert resposta.intencao == "reserva"


# --- Decisoes do classificador ------------------------------------------------

def test_aceita_zera_contador_e_define_assunto(gerente, estado):
    estado.falhas_seguidas = 1
    resposta = gerente.responder("quero reservar uma mesa para 4 pessoas", estado)
    assert isinstance(resposta, Resposta)
    assert resposta.tipo == "aceita"
    assert resposta.intencao == "reserva"
    assert resposta.texto in RESPOSTAS["reserva"]
    assert resposta.confianca is not None
    assert estado.falhas_seguidas == 0
    assert estado.assunto_anterior == "reserva"


def test_duas_mensagens_sem_sentido_levam_ao_encaminhamento(gerente, estado):
    primeira = gerente.responder("asdfgh", estado)
    assert primeira.tipo == "fallback"
    assert primeira.texto in BASE["fallback"]
    assert estado.falhas_seguidas == 1

    segunda = gerente.responder("qwerty zxcv", estado)
    assert MAX_FALHAS_SEGUIDAS == 2
    assert segunda.tipo == "encaminhamento"
    assert segunda.texto in BASE["encaminhamento_humano"]
    assert estado.encaminhado is True
    assert estado.falhas_seguidas == 0


def test_abstencao_responde_fora_do_escopo(gerente, estado):
    resposta = gerente.responder("qual a previsão do tempo amanhã?", estado)
    assert resposta.tipo == "abstencao"
    assert resposta.texto in RESPOSTAS["fora_escopo"]


def test_abstencao_nao_conta_como_falha(gerente, estado, monkeypatch):
    _decisoes_fixas(
        monkeypatch,
        _decisao("fallback", "reserva"),
        _decisao("abstencao", "fora_escopo"),
        _decisao("fallback", "reserva"),
    )
    assert gerente.responder("msg 1", estado).tipo == "fallback"
    assert estado.falhas_seguidas == 1

    assert gerente.responder("msg 2", estado).tipo == "abstencao"
    assert estado.falhas_seguidas == 0

    # Se a abstencao contasse, esta seria a 2a falha e encaminharia.
    assert gerente.responder("msg 3", estado).tipo == "fallback"
    assert estado.encaminhado is False


def test_esclarecimento_resolvido_no_turno_seguinte(gerente, estado, monkeypatch):
    _decisoes_fixas(
        monkeypatch,
        _decisao("esclarecimento", "reserva", ["reserva", "horario_localizacao"]),
        _decisao("aceita", "horario_localizacao"),
    )
    pergunta = gerente.responder("msg ambigua", estado)
    assert pergunta.tipo == "esclarecimento"
    assert "reservas" in pergunta.texto
    assert "horário e localização" in pergunta.texto
    assert "{" not in pergunta.texto
    assert estado.esclarecimento == ["reserva", "horario_localizacao"]

    resposta = gerente.responder("sobre o horario", estado)
    assert resposta.tipo == "aceita"
    assert resposta.intencao == "horario_localizacao"
    assert resposta.texto in RESPOSTAS["horario_localizacao"]
    assert estado.esclarecimento is None
    assert estado.assunto_anterior == "horario_localizacao"


def test_esclarecimento_nao_conta_como_falha(gerente, estado, monkeypatch):
    _decisoes_fixas(
        monkeypatch,
        _decisao("fallback"),
        _decisao("esclarecimento", "reserva", ["reserva", "cardapio_alergenicos"]),
    )
    gerente.responder("msg 1", estado)
    gerente.responder("msg 2", estado)
    assert estado.falhas_seguidas == 1
    assert estado.encaminhado is False


def test_regra_tem_prioridade_sobre_o_classificador(gerente, estado, monkeypatch):
    def nao_deve_ser_chamado(modelo, texto):
        raise AssertionError("classificar nao deveria ser chamado")

    monkeypatch.setattr(dialogo, "classificar", nao_deve_ser_chamado)
    assert gerente.responder("oi", estado).tipo == "regra"
