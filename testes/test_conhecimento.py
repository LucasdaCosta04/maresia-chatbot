import random
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from chatbot.config import FUSO_HORARIO
from chatbot.conhecimento import responder_horario_localizacao
from chatbot.dialogo import EstadoConversa, GerenciadorDialogo, carregar_base

BASE = carregar_base()
FUSO = ZoneInfo(FUSO_HORARIO)

QUARTA_MEIO_DIA = datetime(2026, 11, 18, 12, 0, tzinfo=FUSO)
QUARTA_TARDE = datetime(2026, 11, 18, 16, 0, tzinfo=FUSO)
QUARTA_FIM_JANTAR = datetime(2026, 11, 18, 22, 10, tzinfo=FUSO)
DOMINGO_NOITE = datetime(2026, 11, 22, 20, 0, tzinfo=FUSO)
SEGUNDA_MEIO_DIA = datetime(2026, 11, 23, 12, 0, tzinfo=FUSO)
SEXTA_MANHA = datetime(2026, 11, 20, 9, 0, tzinfo=FUSO)


def responder(mensagem, agora=QUARTA_MEIO_DIA):
    return responder_horario_localizacao(mensagem, BASE, agora)


# --- Aberto agora ---------------------------------------------------------------


def test_aberto_diz_ate_que_horas():
    texto = responder("vocês estão abertos agora?", QUARTA_MEIO_DIA)
    assert "abertos agora" in texto
    assert "15:00" in texto
    assert "14:30" in texto  # ultimo pedido, 30 min antes


def test_aberto_depois_do_ultimo_pedido():
    texto = responder("ainda dá tempo de jantar?", QUARTA_FIM_JANTAR)
    assert "22:30" in texto
    assert "22:00" in texto
    assert "não recebe pedidos" in texto


def test_entre_turnos_diz_quando_reabre():
    texto = responder("funciona agora?", QUARTA_TARDE)
    assert "fechados" in texto
    assert "18:30" in texto
    assert "jantar" in texto


def test_antes_de_abrir_diz_horario_de_hoje():
    texto = responder("ta aberto agora?", SEXTA_MANHA)
    assert "11:30" in texto
    assert "almoço" in texto


def test_segunda_fechado_indica_terca():
    texto = responder("estão funcionando agora?", SEGUNDA_MEIO_DIA)
    assert texto.startswith("Agora estamos fechados.")
    assert "terça-feira (24/11)" in texto
    assert "11:30" in texto


def test_domingo_a_noite_pula_a_segunda():
    texto = responder("ainda está aberto?", DOMINGO_NOITE)
    assert "fechados" in texto
    assert "terça-feira (24/11)" in texto
    assert "segunda" not in texto


# --- Endereco, como chegar, estacionamento --------------------------------------


def test_endereco_usa_a_base():
    texto = responder("Me passa a localização de vocês")
    assert "Rua das Rendeiras Açorianas, 120" in texto
    assert "Santo Antônio de Lisboa" in texto
    assert "Igreja Nossa Senhora das Necessidades" in texto


def test_como_chegar_meio_citado():
    texto = responder("vou de bike, como faço?")
    assert texto == "De bicicleta: " + BASE["restaurante"]["como_chegar"]["bicicleta"]


def test_como_chegar_sem_meio_lista_todos():
    texto = responder("como chego aí?")
    for meio in ("De carro", "De aplicativo", "De bicicleta", "A pé"):
        assert meio in texto


def test_estacionamento():
    texto = responder("dá pra estacionar perto?")
    assert "20 vagas" in texto
    assert "gratuito" in texto
    assert "costuma lotar" in texto


# --- Varios subtemas e nenhum ----------------------------------------------------


def test_dois_subtemas_na_ordem_da_mensagem():
    texto = responder("onde fica o restaurante e tem estacionamento?")
    assert texto.index("Rendeiras") < texto.index("20 vagas")

    texto = responder("tem estacionamento? e onde fica?")
    assert texto.index("20 vagas") < texto.index("Rendeiras")


@pytest.mark.parametrize("mensagem", ["qual o horário de vocês?", "", "abre quando?"])
def test_sem_subtema_devolve_none(mensagem):
    assert responder(mensagem) is None


# --- Gancho no GerenciadorDialogo ------------------------------------------------


@pytest.fixture
def gerenciador():
    return GerenciadorDialogo(None, BASE, random.Random(0), agora=lambda: QUARTA_MEIO_DIA)


def test_dialogo_sem_data_com_subtema_usa_conhecimento(gerenciador):
    texto = gerenciador._responder_intencao(
        "horario_localizacao", EstadoConversa(), "tem estacionamento?"
    )
    assert "20 vagas" in texto


def test_dialogo_sem_data_sem_subtema_mantem_respostas_fixas(gerenciador):
    texto = gerenciador._responder_intencao(
        "horario_localizacao", EstadoConversa(), "qual o horário de vocês?"
    )
    assert texto in gerenciador.respostas_fixas["horario_localizacao"]


def test_dialogo_com_data_mantem_horario_do_dia(gerenciador):
    estado = EstadoConversa()
    texto = gerenciador._responder_intencao("horario_localizacao", estado, "e no sábado?")
    assert texto.startswith("No sábado (21/11)")
    assert estado.ultima_data == "2026-11-21"
