"""Testes do gerenciador de dialogo (regras, decisoes e encaminhamento)."""

import random
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import chatbot.dialogo as dialogo
from chatbot.config import FUSO_HORARIO, MAX_FALHAS_SEGUIDAS
from chatbot.dialogo import (
    MENSAGENS_REGRAS,
    MENSAGENS_RESERVA,
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
    assert resposta.confianca is not None
    assert estado.falhas_seguidas == 0
    assert estado.assunto_anterior == "reserva"


def test_aceita_outra_intencao_usa_resposta_fixa(gerente, estado):
    resposta = gerente.responder("que horas vocês abrem?", estado)
    assert resposta.tipo == "aceita"
    assert resposta.texto in RESPOSTAS["horario_localizacao"]


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


# --- Fluxo de reserva ---------------------------------------------------------
# "Agora" fixo: quarta-feira, 18/11/2026, 18:00 em Sao Paulo. O sabado
# seguinte e 21/11/2026 e a segunda seguinte, 23/11/2026.

AGORA = datetime(2026, 11, 18, 18, 0, tzinfo=ZoneInfo(FUSO_HORARIO))
REGRAS = BASE["reserva"]


@pytest.fixture
def reserva(modelo):
    return GerenciadorDialogo(modelo, BASE, random.Random(0), agora=lambda: AGORA)


def _conversa(gerente, estado, *mensagens):
    """Envia as mensagens em ordem e devolve a ultima resposta."""
    resposta = None
    for mensagem in mensagens:
        resposta = gerente.responder(mensagem, estado)
    return resposta


def test_agora_fixo_e_uma_quarta():
    assert AGORA.weekday() == 2


def test_reserva_completa_passo_a_passo(reserva, estado):
    r = reserva.responder("quero reservar uma mesa", estado)
    assert estado.etapa_reserva == "coletando"
    assert r.texto.endswith(MENSAGENS_RESERVA["pergunta_pessoas"])

    r = reserva.responder("4", estado)
    assert estado.slots == {"pessoas": 4}
    assert r.texto == MENSAGENS_RESERVA["pergunta_data"]

    r = reserva.responder("sábado", estado)
    assert estado.slots["data"] == "2026-11-21"
    assert r.texto.startswith("Qual horário")
    assert "No sábado aceitamos reservas das 11:30 às 14:30 e das 18:30 às 22:30." in r.texto

    r = reserva.responder("20h", estado)
    assert estado.slots["horario"] == "20:00"
    assert r.texto == MENSAGENS_RESERVA["pergunta_nome"]

    r = reserva.responder("Murilo", estado)
    assert estado.slots["nome"] == "Murilo"
    assert estado.etapa_reserva == "confirmando"
    assert "4 pessoas" in r.texto
    assert "sábado, 21 de novembro de 2026" in r.texto
    assert "20:00" in r.texto
    assert "Murilo" in r.texto
    assert "sim/não" in r.texto


def test_reserva_com_varios_slots_numa_mensagem(reserva, estado):
    r = reserva.responder("quero reservar uma mesa para 4 sábado às 20h", estado)
    assert r.intencao == "reserva"
    assert estado.etapa_reserva == "coletando"
    assert estado.slots == {"pessoas": 4, "data": "2026-11-21", "horario": "20:00"}
    assert r.texto == MENSAGENS_RESERVA["pergunta_nome"]


def test_respostas_curtas_por_extenso_e_sem_marcador(reserva, estado):
    _conversa(reserva, estado, "quero reservar uma mesa", "quatro", "sexta")
    assert estado.slots["pessoas"] == 4
    reserva.responder("às 8", estado)  # 08:00 nao e horario de reserva; 20:00 e
    assert estado.slots["horario"] == "20:00"


def test_palavra_solta_nao_vira_nome_fora_de_hora(reserva, estado):
    _conversa(reserva, estado, "quero reservar uma mesa", "Carlos")
    assert "nome" not in estado.slots


def test_segunda_feira_recusada(reserva, estado):
    r = _conversa(reserva, estado, "quero reservar uma mesa para 2", "segunda")
    assert "segunda-feira o restaurante fica fechado" in r.texto
    assert "data" not in estado.slots
    assert r.texto.endswith(MENSAGENS_RESERVA["pergunta_data"])


def test_onze_pessoas_oferece_atendente(reserva, estado):
    r = reserva.responder("quero reservar uma mesa para 11 pessoas", estado)
    assert REGRAS["mensagem_acima_limite"] in r.texto
    assert BASE["restaurante"]["whatsapp"] in r.texto
    assert "pessoas" not in estado.slots
    assert estado.encaminhado is True
    assert estado.etapa_reserva == "coletando"


def test_dez_pessoas_e_aceito(reserva, estado):
    reserva.responder("quero reservar uma mesa para 10 pessoas", estado)
    assert estado.slots["pessoas"] == 10


@pytest.mark.parametrize("horario", ["16h", "23h", "11h"])
def test_horario_fora_do_funcionamento(reserva, estado, horario):
    r = _conversa(reserva, estado, "quero reservar uma mesa para 2 no sábado", horario)
    assert "fora do nosso período de reservas" in r.texto
    assert "horario" not in estado.slots


def test_ultimo_horario_de_reserva_e_aceito(reserva, estado):
    # Sabado fecha 23:30; ultima reserva 60 min antes, as 22:30.
    _conversa(reserva, estado, "quero reservar uma mesa para 2 no sábado", "22h30")
    assert estado.slots["horario"] == "22:30"


def test_data_no_passado(reserva, estado):
    r = _conversa(reserva, estado, "quero reservar uma mesa para 2", "10/11/2026")
    assert r.texto.startswith(MENSAGENS_RESERVA["passado"])
    assert "data" not in estado.slots


def test_data_alem_da_janela(reserva, estado):
    # 25/12 esta a 37 dias; a janela da base e de 30 dias (ate 18/12).
    r = _conversa(reserva, estado, "quero reservar uma mesa para 2", "25/12")
    assert f"até {REGRAS['antecedencia_maxima_dias']} dias" in r.texto
    assert "18 de dezembro de 2026" in r.texto
    assert "data" not in estado.slots


def test_menos_de_uma_hora_de_antecedencia(reserva, estado):
    r = _conversa(reserva, estado, "quero reservar uma mesa para 2 hoje", "18h30")
    assert "pelo menos 1 hora de antecedência" in r.texto
    assert "horario" not in estado.slots
    reserva.responder("19h30", estado)
    assert estado.slots["horario"] == "19:30"


@pytest.mark.parametrize("mensagem", ["cancelar", "quero cancelar a reserva", "desisti"])
def test_cancelar_no_meio_do_fluxo(reserva, estado, mensagem):
    _conversa(reserva, estado, "quero reservar uma mesa para 4 sábado")
    r = reserva.responder(mensagem, estado)
    assert r.texto == MENSAGENS_REGRAS["cancelar"]
    assert estado.slots == {}
    assert estado.etapa_reserva is None


def test_pergunta_de_cardapio_no_meio_da_reserva(reserva, estado):
    _conversa(reserva, estado, "quero reservar uma mesa para 4 sábado")
    slots_antes = dict(estado.slots)
    r = reserva.responder("vocês têm prato sem glúten?", estado)
    assert r.intencao == "cardapio_alergenicos"
    assert any(texto in r.texto for texto in RESPOSTAS["cardapio_alergenicos"])
    assert "Sobre a sua reserva: Qual horário" in r.texto
    assert estado.slots == slots_antes
    assert estado.etapa_reserva == "coletando"
    reserva.responder("20h", estado)
    assert estado.slots["horario"] == "20:00"


def test_fallback_no_meio_da_reserva_repete_a_pergunta(reserva, estado):
    _conversa(reserva, estado, "quero reservar uma mesa")
    r = reserva.responder("asdfgh", estado)
    assert r.tipo == "fallback"
    assert r.texto.endswith(MENSAGENS_RESERVA["pergunta_pessoas"])
    assert estado.falhas_seguidas == 1
    assert estado.slots == {}


def test_confirmacao_sim_registra_simulacao(reserva, estado):
    _conversa(reserva, estado, "quero reservar uma mesa para 4 sábado às 20h", "em nome de Ana")
    assert estado.etapa_reserva == "confirmando"
    r = reserva.responder("sim", estado)
    assert "SIMULAÇÃO" in r.texto
    assert "Nenhuma reserva foi gravada" in r.texto
    assert "Ana" in r.texto
    assert estado.slots == {}
    assert estado.etapa_reserva is None


def test_confirmacao_nao_volta_a_coletar(reserva, estado):
    _conversa(reserva, estado, "quero reservar uma mesa para 4 sábado às 20h", "em nome de Ana")
    r = reserva.responder("não", estado)
    assert r.texto == MENSAGENS_RESERVA["o_que_alterar"]
    assert estado.etapa_reserva == "coletando"

    r = reserva.responder("o horário", estado)
    assert "horario" not in estado.slots
    assert r.texto.startswith("Qual horário")

    r = reserva.responder("21h", estado)
    assert estado.etapa_reserva == "confirmando"
    assert "21:00" in r.texto
    assert estado.slots["nome"] == "Ana"


def test_nao_com_correcao_volta_ao_resumo(reserva, estado):
    _conversa(reserva, estado, "quero reservar uma mesa para 4 sábado às 20h", "em nome de Ana")
    r = reserva.responder("não, muda pra 21h", estado)
    assert estado.etapa_reserva == "confirmando"
    assert estado.slots["horario"] == "21:00"
    assert "21:00" in r.texto


def test_cancelar_reserva_existente_responde_a_politica(reserva, estado):
    r = reserva.responder("quero cancelar minha reserva de sabado", estado)
    assert r.texto == REGRAS["politica_cancelamento"]
    assert estado.etapa_reserva is None


def test_reiniciar_limpa_a_reserva():
    estado = EstadoConversa(slots={"pessoas": 2}, etapa_reserva="confirmando")
    estado.reiniciar()
    assert estado == EstadoConversa()
