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
from chatbot.entidades import extrair_entidades
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


def test_aceita_outra_intencao_responde_a_intencao(gerente, estado):
    resposta = gerente.responder("que horas vocês abrem?", estado)
    assert resposta.tipo == "aceita"
    assert resposta.texto.startswith("Nosso horário de funcionamento:")


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
    assert resposta.texto.startswith("Nosso horário de funcionamento:")
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
    # Encaminhado: o fluxo termina, sem perguntar "para quantas pessoas?".
    assert estado.etapa_reserva is None
    assert MENSAGENS_RESERVA["pergunta_pessoas"] not in r.texto
    assert "até 10 pessoas" in r.texto


@pytest.mark.parametrize(
    "mensagem", ["preciso reservar com quanta antecedência?", "até quando posso reservar?"]
)
def test_pergunta_de_antecedencia_responde_a_regra_sem_abrir_reserva(reserva, estado, mensagem):
    r = reserva.responder(mensagem, estado)
    assert r.texto.startswith("A reserva precisa ser feita com pelo menos 1 hora de antecedência")
    assert "30 dias" in r.texto
    assert estado.etapa_reserva is None


@pytest.mark.parametrize(
    "mensagem", ["quantas pessoas no máximo posso reservar?", "qual o limite de pessoas pra reserva?"]
)
def test_pergunta_de_limite_de_pessoas_responde_a_regra(reserva, estado, mensagem):
    r = reserva.responder(mensagem, estado)
    assert r.texto.startswith("Pelo chat eu faço reservas de 1 a 10 pessoas.")
    assert estado.etapa_reserva is None


def test_grupo_grande_no_meio_da_reserva_encerra_o_fluxo(reserva, estado):
    r = _conversa(reserva, estado, "quero reservar uma mesa", "15 pessoas")
    assert REGRAS["mensagem_acima_limite"] in r.texto
    assert estado.etapa_reserva is None


def test_depois_do_grupo_grande_da_para_reservar_ate_dez(reserva, estado):
    r = _conversa(reserva, estado, "dá pra reservar pra 15 pessoas?", "quero reservar para 8 pessoas")
    assert estado.slots["pessoas"] == 8
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
    assert r.texto.startswith("Opções sem glúten:")
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


# --- Respostas com entidades --------------------------------------------------
# Usa o mesmo AGORA (quarta 18/11/2026): sabado = 21/11, domingo = 22/11,
# segunda = 23/11. Lula a Dore leva moluscos, ovos e trigo/gluten na base.

PRATOS = {prato["id"]: prato for prato in BASE["cardapio"]}
AVISO_ALERGENICOS = BASE["alergenicos"]["aviso_padrao"]


def test_horario_de_um_dia(reserva, estado):
    r = reserva.responder("que horas vocês abrem no sábado?", estado)
    assert r.intencao == "horario_localizacao"
    assert r.herdou_contexto is False
    sabado = BASE["funcionamento"]["dias"]["sabado"]
    assert r.texto == (
        f"No sábado (21/11) abrimos no almoço das {sabado['almoco']['abre']} às "
        f"{sabado['almoco']['fecha']} e no jantar das {sabado['jantar']['abre']} às "
        f"{sabado['jantar']['fecha']}."
    )
    assert estado.ultima_data == "2026-11-21"


def test_horario_sem_data_responde_a_semana(reserva, estado):
    r = reserva.responder("que horas vocês abrem?", estado)
    assert r.texto.startswith("Nosso horário de funcionamento:")
    assert estado.ultima_data is None


def test_prato_contem_alergenico(reserva, estado):
    r = reserva.responder("o bolinho de siri tem glúten?", estado)
    assert r.intencao == "cardapio_alergenicos"
    assert r.texto.startswith("Sim, Bolinho de Siri (12 unidades) contém trigo / glúten.")
    assert AVISO_ALERGENICOS in r.texto
    assert estado.ultimo_prato == "bolinho_siri"


def test_prato_nao_contem_alergenico(reserva, estado):
    r = reserva.responder("a moqueca de peixe tem lactose?", estado)
    assert r.texto.startswith("Não, Moqueca de Peixe não contém leite e derivados.")


def test_prato_pode_conter_alergenico(reserva, estado):
    # Caldo de Peixe: crustaceos so em pode_conter.
    assert "crustaceos" in PRATOS["caldo_peixe"]["pode_conter"]
    r = reserva.responder("o caldo de peixe tem camarão?", estado)
    assert "pode conter traços" in r.texto


def test_so_prato_descreve_o_prato(reserva, estado):
    r = reserva.responder("o que tem na lula à dorê?", estado)
    lula = PRATOS["lula_a_dore"]
    assert r.texto.startswith(f"{lula['nome']}: {lula['descricao']}")
    assert "Alergênicos: moluscos, ovos e trigo / glúten." in r.texto
    assert estado.ultimo_prato == "lula_a_dore"


def test_lista_de_pratos_sem_gluten(reserva, estado):
    r = reserva.responder("tem opção sem glúten?", estado)
    sem_gluten = [p["nome"] for p in BASE["cardapio"] if p["sem_gluten"]]
    com_gluten = [p["nome"] for p in BASE["cardapio"] if not p["sem_gluten"]]
    assert r.texto.startswith("Opções sem glúten:")
    assert all(nome in r.texto for nome in sem_gluten)
    assert not any(nome in r.texto for nome in com_gluten)


def test_lista_de_pratos_veganos_nao_vira_um_prato_so(reserva, estado):
    r = reserva.responder("tem prato vegano?", estado)
    assert r.texto.startswith("Opções veganas:")
    assert "Manjar de Coco" in r.texto
    assert "Moqueca de Banana-da-Terra com Palmito" in r.texto


def test_prato_com_restricao(reserva, estado):
    r = reserva.responder("o pudim é sem lactose?", estado)
    assert r.texto.startswith("Não, Pudim de Leite não é uma opção sem lactose.")


def test_alergenico_sem_pista_lista_pratos_com_ele(reserva, estado):
    r = reserva.responder("tem camarão?", estado)
    assert r.texto.startswith("Pratos que levam crustáceos:")


def test_alergia_lista_pratos_sem_ele(reserva, estado):
    r = reserva.responder("sou alérgico a camarão", estado)
    assert r.texto.startswith("Pratos sem crustáceos:")
    # "Pode conter" tambem fica de fora, por seguranca.
    assert PRATOS["caldo_peixe"]["nome"] not in r.texto


@pytest.mark.parametrize(
    "mensagem",
    [
        "quais pratos não têm camarão?",
        "quero pratos que não levam camarão",
        "tem algum prato que não contém camarão?",
        "me mostra os pratos que não tenham siri",
        "pratos livres de crustáceos",
    ],
)
def test_negacao_lista_pratos_sem_o_alergenico(reserva, estado, mensagem):
    r = reserva.responder(mensagem, estado)
    assert r.texto.startswith("Pratos sem crustáceos:")
    assert PRATOS["bolinho_siri"]["nome"] not in r.texto
    assert PRATOS["camarao_na_moranga"]["nome"] not in r.texto


def _sem_os_alergenicos(ids):
    """Nomes dos pratos sem nenhum dos alergenicos, nem como "pode conter"."""
    return [
        p["nome"] for p in BASE["cardapio"]
        if not set(ids) & (set(p["alergenicos"]) | set(p.get("pode_conter", [])))
    ]


def test_ver_cardapio_lista_todos_os_pratos_por_categoria(reserva, estado):
    r = reserva.responder("quero ver o cardápio", estado)
    assert r.intencao == "cardapio_alergenicos"
    assert r.texto.startswith("Este é o nosso cardápio:")
    linhas = r.texto.split("\n")
    # Cada prato numa linha propria, com recuo, nome e preco.
    for prato in BASE["cardapio"]:
        assert any(
            linha.startswith("   • " + prato["nome"] + " – R$ ") for linha in linhas
        ), prato["nome"]
    # Titulo de cada categoria numa linha sozinha, sem recuo, antes dos pratos.
    for titulo in ("Entradas:", "Pratos principais:", "Sobremesas:"):
        assert titulo in linhas
    i = linhas.index("Sobremesas:")
    assert linhas[i + 1] == "   • Pudim de Leite – R$ 18,90"


def test_pergunta_vaga_sobre_comida_mantem_resposta_fixa(reserva, estado):
    r = reserva.responder("as comidas são gostosas?", estado)
    assert r.texto in RESPOSTAS["cardapio_alergenicos"]


def test_pratos_principais_sem_frutos_do_mar(reserva, estado):
    r = reserva.responder(
        "quero pratos principais, mas sem frutos do mar, pois sou alérgico", estado
    )
    esperados = [
        p["nome"] for p in BASE["cardapio"]
        if p["categoria"] == "prato_principal"
        and p["nome"] in _sem_os_alergenicos(["crustaceos", "moluscos"])
    ]
    assert esperados == ["Moqueca de Banana-da-Terra com Palmito"]
    assert r.texto.startswith(
        "Pratos principais sem frutos do mar:\n"
        "   • Moqueca de Banana-da-Terra com Palmito – R$ 89,90\n\n"
    )
    assert "crustáceos e moluscos" in r.texto
    assert AVISO_ALERGENICOS in r.texto


def test_sem_frutos_do_mar_exclui_crustaceos_e_moluscos_de_todas_as_categorias(reserva, estado):
    r = reserva.responder("quais pratos sem frutos do mar?", estado)
    permitidos = _sem_os_alergenicos(["crustaceos", "moluscos"])
    proibidos = [p["nome"] for p in BASE["cardapio"] if p["nome"] not in permitidos]
    assert r.texto.startswith("Pratos sem frutos do mar:\n\nPratos principais:\n")
    assert all(nome in r.texto for nome in permitidos)
    assert not any(nome in r.texto for nome in proibidos)


def test_varios_alergenicos_geram_uma_lista_so(reserva, estado):
    r = reserva.responder("sou alérgico a camarão e peixe, o que posso comer?", estado)
    permitidos = _sem_os_alergenicos(["crustaceos", "peixes"])
    proibidos = [p["nome"] for p in BASE["cardapio"] if p["nome"] not in permitidos]
    assert r.texto.startswith("Pratos sem crustáceos e peixes:")
    assert r.texto.count("Pratos sem") == 1
    assert all(nome in r.texto for nome in permitidos)
    assert not any(nome in r.texto for nome in proibidos)


def test_categoria_sozinha_lista_a_categoria(reserva, estado):
    r = reserva.responder("quais as sobremesas?", estado)
    sobremesas = [p["nome"] for p in BASE["cardapio"] if p["categoria"] == "sobremesa"]
    assert r.texto.startswith("Sobremesas:")
    assert all(nome in r.texto for nome in sobremesas)
    assert "Pudim de Leite – R$ 18,90" in r.texto


def test_categoria_com_restricao_concorda_no_feminino(reserva, estado):
    r = reserva.responder("tem sobremesa vegana?", estado)
    assert r.texto.startswith("Sobremesas veganas:\n   • Manjar de Coco – R$ 17,90\n\n")


def test_categoria_com_restricao_sem_resultado(reserva, estado):
    r = reserva.responder("tem entrada vegana?", estado)
    assert r.texto.startswith("No momento não temos entradas veganas.")


# --- Classificador: perguntas claras que caiam em fora_escopo (dataset v1.5) -------


@pytest.mark.parametrize(
    "mensagem, intencao",
    [
        ("qual o horário de sábado?", "horario_localizacao"),
        ("horario", "horario_localizacao"),
        ("me manda o menu", "cardapio_alergenicos"),
        ("o que vc recomenda?", "cardapio_alergenicos"),
        ("com quanto tempo antes tenho que reservar?", "reserva"),
    ],
)
def test_perguntas_do_dominio_sao_aceitas(reserva, estado, mensagem, intencao):
    r = reserva.responder(mensagem, estado)
    assert r.tipo == "aceita"
    assert r.intencao == intencao


@pytest.mark.parametrize(
    "mensagem",
    [
        "qual o horário de funcionamento do detran",
        "qual o horário do banco hoje",
        "me recomenda uma série",
        "horário de verão",
    ],
)
def test_mesmas_palavras_em_outro_sentido_continuam_fora_do_escopo(reserva, estado, mensagem):
    r = reserva.responder(mensagem, estado)
    assert r.intencao == "fora_escopo"


# --- Filtro por preco ---------------------------------------------------------------


def _nomes_ate(valor):
    return [p["nome"] for p in BASE["cardapio"] if p["preco"] <= valor]


def test_ate_x_reais_lista_so_os_pratos_na_faixa(reserva, estado):
    r = reserva.responder("tem algo até 50 reais?", estado)
    assert r.intencao == "cardapio_alergenicos"
    assert r.texto.startswith("Pratos até R$ 50,00:")
    assert all(nome in r.texto for nome in _nomes_ate(50))
    assert not any(p["nome"] in r.texto for p in BASE["cardapio"] if p["preco"] > 50)


def test_lista_com_faixa_vem_do_mais_barato_ao_mais_caro(reserva, estado):
    r = reserva.responder("tem algo até 50 reais?", estado)
    assert r.texto.index("Manjar de Coco") < r.texto.index("Pudim de Leite") < r.texto.index("Cocada de Forno")


def test_faixa_entre_dois_valores(reserva, estado):
    r = reserva.responder("pratos entre 100 e 150 reais", estado)
    assert r.texto.startswith("Pratos entre R$ 100,00 e R$ 150,00:")
    assert all(
        p["nome"] in r.texto for p in BASE["cardapio"] if 100 <= p["preco"] <= 150
    )
    assert PRATOS["sequencia_camarao_tradicional"]["nome"] not in r.texto


def test_faixa_sem_resultado_indica_o_mais_barato(reserva, estado):
    r = reserva.responder("tem algo até 15 reais?", estado)
    barato = min(BASE["cardapio"], key=lambda p: p["preco"])
    assert r.texto.startswith("No momento não temos pratos até R$ 15,00.")
    assert barato["nome"] in r.texto


def test_mais_barato_de_cada_categoria(reserva, estado):
    r = reserva.responder("qual o prato mais barato?", estado)
    assert r.texto.startswith("O mais barato de cada categoria:")
    assert "Caldo de Peixe – R$ 24,90" in r.texto
    assert "Moqueca de Banana-da-Terra com Palmito – R$ 89,90" in r.texto
    assert "Tainha Escalada" not in r.texto


def test_mais_cara_de_uma_categoria_concorda_no_feminino(reserva, estado):
    r = reserva.responder("qual a sobremesa mais cara?", estado)
    assert r.texto == "Sobremesas (a mais cara):\n   • Cocada de Forno – R$ 19,90"


def test_preco_combina_com_alergia(reserva, estado):
    r = reserva.responder("qual o prato mais barato sem frutos do mar?", estado)
    assert r.texto.startswith("Pratos sem frutos do mar (o mais barato de cada categoria):")
    assert "Caldo de Peixe" not in r.texto  # pode conter crustaceos


def test_preco_herda_a_categoria_da_lista_anterior(reserva, estado):
    r = _conversa(reserva, estado, "quero pratos principais", "e até 120 reais?")
    assert r.herdou_contexto
    assert r.texto.startswith("Pratos principais até R$ 120,00:")
    assert "Salada da Casa" not in r.texto


def test_filtro_novo_herda_a_faixa_de_preco(reserva, estado):
    r = _conversa(reserva, estado, "tem algo até 50 reais?", "e sem glúten?")
    assert r.texto.startswith("Opções sem glúten até R$ 50,00:")


def test_preco_de_um_prato_continua_a_descricao(reserva, estado):
    r = reserva.responder("quanto custa o pudim?", estado)
    assert r.texto.startswith("Pudim de Leite:")


# --- Porcao ("prato para 2 pessoas") ------------------------------------------------


@pytest.mark.parametrize("mensagem", ["tem prato para 2 pessoas?", "qual prato serve duas pessoas"])
def test_prato_para_n_pessoas_lista_a_porcao_sem_abrir_reserva(reserva, estado, mensagem):
    r = reserva.responder(mensagem, estado)
    assert r.intencao == "cardapio_alergenicos"
    assert r.texto.startswith("Pratos que servem 2 pessoas:")
    assert estado.etapa_reserva is None
    dois = [p["nome"] for p in BASE["cardapio"] if p["serve_pessoas"] == 2]
    um = [p["nome"] for p in BASE["cardapio"] if p["serve_pessoas"] == 1]
    assert all(nome in r.texto for nome in dois)
    assert not any(nome in r.texto for nome in um)


def test_prato_individual_lista_os_que_servem_uma_pessoa(reserva, estado):
    r = reserva.responder("tem prato individual?", estado)
    assert r.texto.startswith("Pratos que servem 1 pessoa:")


def test_porcao_inexistente(reserva, estado):
    r = reserva.responder("tem porção pra 4 pessoas?", estado)
    assert r.texto == "No momento não temos pratos que sirvam 4 pessoas. Nossos pratos servem 1 ou 2 pessoas."


def test_prato_citado_com_numero_de_pessoas_responde_a_porcao_dele(reserva, estado):
    r = reserva.responder("o pudim serve 2 pessoas?", estado)
    assert r.texto == "Pudim de Leite serve 1 pessoa."
    assert estado.etapa_reserva is None


def test_reserva_com_numero_de_pessoas_continua_reserva(reserva, estado):
    r = reserva.responder("quero reservar mesa para 2 pessoas", estado)
    assert r.intencao == "reserva"
    assert estado.slots["pessoas"] == 2


# --- Fora do cardapio -------------------------------------------------------------


@pytest.mark.parametrize("mensagem", ["tem cerveja?", "vocês servem vinho?", "tem bebida?"])
def test_bebidas_indicam_a_equipe(reserva, estado, mensagem):
    r = reserva.responder(mensagem, estado)
    assert r.texto.startswith("Ainda não tenho aqui as informações de bebidas.")
    assert BASE["restaurante"]["whatsapp"] in r.texto


@pytest.mark.parametrize(
    "mensagem, termo", [("tem pizza?", "pizza"), ("tem lasanha?", "lasanha"), ("tem sorvete?", "sorvete")]
)
def test_item_fora_do_cardapio_diz_que_nao_encontrou(reserva, estado, mensagem, termo):
    r = reserva.responder(mensagem, estado)
    assert r.texto.startswith(f"Não encontrei “{termo}” no nosso cardápio.")


def test_item_do_cardapio_continua_respondido(reserva, estado):
    r = reserva.responder("tem lula?", estado)
    assert r.texto.startswith("Lula à Dorê:")


# --- Continuacao de horario/localizacao sem data -----------------------------------


def test_e_pago_depois_de_estacionamento(reserva, estado):
    r = _conversa(reserva, estado, "tem estacionamento?", "e é pago?")
    assert r.herdou_contexto
    assert r.texto.startswith("O estacionamento é gratuito")


def test_e_o_endereco_depois_de_estacionamento(reserva, estado):
    r = _conversa(reserva, estado, "tem estacionamento?", "e o endereço?")
    assert r.herdou_contexto
    assert "Rendeiras" in r.texto


# --- Contato --------------------------------------------------------------------


@pytest.mark.parametrize(
    "mensagem", ["qual o telefone de vcs?", "tem whatsapp?", "me passa o zap", "posso ligar pra reservar?"]
)
def test_contato_responde_telefone_e_whatsapp(reserva, estado, mensagem):
    r = reserva.responder(mensagem, estado)
    assert r.tipo == "regra"
    assert BASE["restaurante"]["whatsapp"] in r.texto
    assert BASE["restaurante"]["telefone"] in r.texto


def test_contato_no_meio_da_reserva_lembra_o_passo(reserva, estado):
    r = _conversa(reserva, estado, "quero reservar uma mesa", "qual o telefone?")
    assert BASE["restaurante"]["telefone"] in r.texto
    assert estado.etapa_reserva is not None
    assert "pessoas" in r.texto


# --- Esclarecimento de data solta respondido com outra data ---------------------


def test_esclarecimento_respondido_com_outra_data_usa_a_nova(reserva, estado):
    r = _conversa(reserva, estado, "e domingo?", "e segunda?")
    assert r.intencao == "horario_localizacao"
    assert r.texto == "Na segunda-feira (23/11) o restaurante fica fechado."
    assert estado.ultima_data == "2026-11-23"


def test_esclarecimento_reserva_com_outra_data_mantem_o_horario(reserva, estado):
    _conversa(reserva, estado, "domingo às 20h", "quero reservar pra sábado")
    assert estado.slots["data"] == "2026-11-21"
    assert estado.slots["horario"] == "20:00"


def test_esclarecimento_sem_data_nova_usa_a_data_solta(reserva, estado):
    r = _conversa(reserva, estado, "domingo", "horário")
    assert r.texto.startswith("No domingo (22/11)")


# --- Alergenico liberado ("mas como peixe") ---------------------------------------


@pytest.mark.parametrize(
    "mensagem, titulo",
    [
        ("sou alergico a camarao mas como peixe, quais pratos posso comer?", "Pratos sem crustáceos:"),
        ("sou alérgico a camarão, peixe eu como", "Pratos sem crustáceos:"),
        ("sou alérgico a camarão, mas não tenho alergia a peixe", "Pratos sem crustáceos:"),
        ("sou alérgico a ovo, mas leite tudo bem", "Pratos sem ovos:"),
    ],
)
def test_alergenico_liberado_sai_do_filtro(reserva, estado, mensagem, titulo):
    r = reserva.responder(mensagem, estado)
    assert r.texto.startswith(titulo)


@pytest.mark.parametrize(
    "mensagem",
    [
        "sou alérgico a camarão e peixe, o que posso comer?",
        "sou alérgico a camarão e peixe, o que eu posso comer?",
        "sou alérgico a camarão e peixe, como vocês preparam?",
        "sou alérgico a camarão e não como peixe",
        "não como camarão nem peixe",
    ],
)
def test_sem_liberacao_explicita_os_dois_continuam_evitados(reserva, estado, mensagem):
    r = reserva.responder(mensagem, estado)
    assert r.texto.startswith("Pratos sem crustáceos e peixes:")


# --- Titulo das listas --------------------------------------------------------------


@pytest.mark.parametrize(
    "mensagem, titulo",
    [
        ("tem prato sem frutos do mar e sem glúten?", "Pratos sem glúten e sem frutos do mar:"),
        ("tem sobremesa vegana sem amendoim?", "Sobremesas veganas e sem amendoim:"),
        ("pratos sem crustáceos", "Pratos sem crustáceos:"),
    ],
)
def test_titulo_da_lista_com_restricao_e_alergenico(reserva, estado, mensagem, titulo):
    r = reserva.responder(mensagem, estado)
    assert r.texto.startswith(titulo)


# --- Heranca dos filtros do cardapio ---------------------------------------------


def test_alergia_continua_valendo_na_continuacao(reserva, estado):
    r = _conversa(reserva, estado, "sou alérgico a frutos do mar", "e de sobremesa?")
    assert r.herdou_contexto
    assert r.texto.startswith("Sobremesas sem frutos do mar:")

    r = reserva.responder("e entrada?", estado)
    assert r.texto.startswith("No momento não temos entradas sem frutos do mar.")
    assert PRATOS["ostras_in_natura"]["nome"] not in r.texto
    assert PRATOS["bolinho_siri"]["nome"] not in r.texto


def test_categoria_continua_valendo_com_alergia_nova(reserva, estado):
    r = _conversa(reserva, estado, "quero pratos principais", "sem frutos do mar")
    assert r.texto.startswith(
        "Pratos principais sem frutos do mar:\n"
        "   • Moqueca de Banana-da-Terra com Palmito – R$ 89,90\n\n"
    )


def test_restricoes_se_acumulam(reserva, estado):
    r = _conversa(reserva, estado, "tem prato sem glúten?", "e sem lactose também?")
    assert r.texto.startswith("Opções sem glúten e sem lactose:")
    assert PRATOS["sirigado_grelhado"]["nome"] not in r.texto  # sem gluten, mas com leite


def test_restricao_nova_filtra_a_categoria_anterior(reserva, estado):
    r = _conversa(reserva, estado, "o que tem de sobremesa?", "e vegano?")
    assert r.texto.startswith("Sobremesas veganas:\n   • Manjar de Coco – R$ 17,90\n\n")


def test_e_alergenico_mantem_o_sentido_de_evitar(reserva, estado):
    r = _conversa(reserva, estado, "sou alérgico a camarão", "e amendoim?")
    assert r.texto.startswith("Pratos sem crustáceos e amendoim:")
    assert PRATOS["cocada_forno"]["nome"] not in r.texto  # pode conter amendoim


def test_e_alergenico_depois_de_um_prato_fala_do_prato(reserva, estado):
    r = _conversa(reserva, estado, "a moqueca de peixe tem glúten?", "e camarão?")
    assert r.herdou_contexto
    assert r.texto.startswith("Moqueca de Peixe não leva crustáceos na receita, mas pode conter traços")


def test_cardapio_completo_seguido_de_filtro(reserva, estado):
    r = _conversa(reserva, estado, "quero ver o cardápio", "e sem glúten?")
    assert r.texto.startswith("Opções sem glúten:")


def test_outra_intencao_nao_herda_filtros(reserva, estado):
    r = _conversa(reserva, estado, "sou alérgico a camarão", "quero reservar uma mesa")
    assert r.intencao == "reserva"
    assert not r.herdou_contexto


def test_prato_ambiguo_pergunta_qual(reserva, estado):
    r = reserva.responder("tem moqueca?", estado)
    assert "Moqueca de Peixe" in r.texto
    assert "Moqueca de Banana-da-Terra com Palmito" in r.texto
    assert r.texto.endswith("Sobre qual você quer saber?")


# --- Heranca de contexto ------------------------------------------------------

def test_herda_horario_para_outro_dia(reserva, estado):
    reserva.responder("que horas vocês abrem no sábado?", estado)
    r = reserva.responder("e no domingo?", estado)
    assert r.herdou_contexto is True
    assert r.intencao == "horario_localizacao"
    domingo = BASE["funcionamento"]["dias"]["domingo"]
    assert r.texto == (
        f"No domingo (22/11) abrimos no almoço das {domingo['almoco']['abre']} às "
        f"{domingo['almoco']['fecha']}."
    )
    assert estado.ultima_data == "2026-11-22"
    assert estado.falhas_seguidas == 0


def test_herda_horario_segunda_fechado(reserva, estado):
    reserva.responder("que horas vocês abrem no sábado?", estado)
    r = reserva.responder("e na segunda?", estado)
    assert r.herdou_contexto is True
    assert r.texto == "Na segunda-feira (23/11) o restaurante fica fechado."


def test_herda_prato_com_pronome(reserva, estado):
    reserva.responder("o que tem na lula à dorê?", estado)
    r = reserva.responder("ele tem glúten?", estado)
    assert r.herdou_contexto is True
    assert r.intencao == "cardapio_alergenicos"
    assert r.texto.startswith("Sim, Lula à Dorê contém trigo / glúten.")

    r = reserva.responder("e esse tem lactose?", estado)
    assert r.herdou_contexto is True
    assert r.texto.startswith("Não, Lula à Dorê não contém leite e derivados.")


def test_herda_zera_falhas(reserva, estado):
    reserva.responder("que horas vocês abrem no sábado?", estado)
    estado.falhas_seguidas = 1
    reserva.responder("e no domingo?", estado)
    assert estado.falhas_seguidas == 0


def test_pronome_sem_prato_anterior_nao_herda(reserva, estado):
    r = reserva.responder("ele tem glúten?", estado)
    assert r.herdou_contexto is False
    assert estado.ultimo_prato is None


def test_pronome_depois_de_horario_nao_herda(reserva, estado):
    # Assunto anterior e horario: alergenico nao e entidade util para ele.
    reserva.responder("que horas vocês abrem no sábado?", estado)
    r = reserva.responder("ele tem glúten?", estado)
    assert r.herdou_contexto is False


def test_outro_assunto_claro_nao_herda(reserva, estado):
    reserva.responder("que horas vocês abrem no sábado?", estado)
    r = reserva.responder("quero reservar uma mesa", estado)
    assert r.herdou_contexto is False
    assert r.intencao == "reserva"
    assert estado.etapa_reserva == "coletando"


def test_classificador_com_outra_intencao_impede_heranca(reserva, estado, monkeypatch):
    reserva.responder("que horas vocês abrem no sábado?", estado)
    monkeypatch.setattr(
        dialogo, "classificar", lambda modelo, texto: _decisao("aceita", "cardapio_alergenicos")
    )
    r = reserva.responder("e no domingo?", estado)
    assert r.herdou_contexto is False
    assert r.intencao == "cardapio_alergenicos"


def test_heranca_vence_fallback_e_esclarecimento(reserva, estado, monkeypatch):
    reserva.responder("que horas vocês abrem no sábado?", estado)
    for decisao in (_decisao("fallback"), _decisao("esclarecimento", "reserva", ["reserva", "horario_localizacao"])):
        monkeypatch.setattr(dialogo, "classificar", lambda modelo, texto, d=decisao: d)
        r = reserva.responder("e no domingo?", estado)
        assert r.herdou_contexto is True
        assert r.texto.startswith("No domingo (22/11)")


def test_mensagem_longa_nao_herda(reserva, estado, monkeypatch):
    reserva.responder("que horas vocês abrem no sábado?", estado)
    monkeypatch.setattr(dialogo, "classificar", lambda modelo, texto: _decisao("fallback"))
    r = reserva.responder("e se a gente for no domingo bem cedo mesmo?", estado)
    assert r.herdou_contexto is False


def test_so_data_sem_assunto_anterior_nao_herda(reserva, estado):
    r = reserva.responder("e no domingo?", estado)
    assert r.herdou_contexto is False


def test_reiniciar_limpa_a_memoria():
    estado = EstadoConversa(ultimo_prato="lula_a_dore", ultima_data="2026-11-21")
    estado.reiniciar()
    assert estado == EstadoConversa()


# --- Pedidos multiplos ----------------------------------------------------------

T14 = "quero reservar uma mesa para sábado e também saber se vocês têm prato sem glúten"


def test_t14_pergunta_por_onde_comecar(reserva, estado):
    r = reserva.responder(T14, estado)
    assert r.tipo == "esclarecimento"
    assert r.texto.endswith("Por qual começamos?")
    assert "1) reservas" in r.texto
    assert "2) cardápio e alergênicos" in r.texto
    assert r.probabilidades
    assert estado.esclarecimento == ["reserva", "cardapio_alergenicos"]
    assert estado.etapa_reserva is None


def test_t14_resolvido_com_a_reserva(reserva, estado):
    reserva.responder(T14, estado)
    r = reserva.responder("a reserva", estado)
    assert r.tipo == "aceita"
    assert r.intencao == "reserva"
    assert estado.esclarecimento is None
    assert estado.etapa_reserva == "coletando"
    assert r.texto.endswith(MENSAGENS_RESERVA["pergunta_pessoas"])


def test_t14_resolvido_com_o_cardapio(reserva, estado):
    reserva.responder(T14, estado)
    r = reserva.responder("sobre o cardápio", estado)
    assert r.intencao == "cardapio_alergenicos"
    assert estado.esclarecimento is None
    assert estado.etapa_reserva is None


def test_tres_pedidos_resolvidos_no_turno_seguinte(reserva, estado):
    r = reserva.responder("que horas vocês abrem? tem prato vegano? quero reservar uma mesa", estado)
    assert "3) reservas" in r.texto
    assert estado.esclarecimento == ["horario_localizacao", "cardapio_alergenicos", "reserva"]
    r = reserva.responder("que horas vocês abrem no sábado?", estado)
    assert r.intencao == "horario_localizacao"
    assert estado.esclarecimento is None


def test_pedido_multiplo_nao_conta_como_falha(reserva, estado):
    estado.falhas_seguidas = 1
    reserva.responder(T14, estado)
    assert estado.falhas_seguidas == 1
    assert estado.encaminhado is False


def test_no_meio_da_reserva_e_preenchimento_de_slots(reserva, estado):
    reserva.responder("quero reservar uma mesa", estado)
    r = reserva.responder("para 4 pessoas e no sábado", estado)
    assert r.tipo == "reserva"
    assert estado.slots == {"pessoas": 4, "data": "2026-11-21"}
    assert estado.esclarecimento is None
    assert r.texto.startswith("Qual horário")


# --- Data solta -----------------------------------------------------------------
# AGORA: quarta 18/11/2026 18:00. Amanha = quinta 19/11; sabado = 21/11;
# segunda = 23/11.

ESCLARECIMENTO_DATA = ["reserva", "horario_localizacao"]


@pytest.mark.parametrize(
    "mensagem",
    ["Sábado", "amanhã à noite", "dia 25", "hoje", "25/12", "sábado que vem",
     "depois de amanhã de manhã", "sexta-feira", "sábado às 20h", "no almoço de domingo"],
)
def test_so_data_verdadeiro(reserva, mensagem):
    assert reserva._so_data(mensagem, extrair_entidades(mensagem, AGORA)) is True


@pytest.mark.parametrize(
    "mensagem",
    ["sábado vocês abrem?", "quero reservar sábado", "tem moqueca no sábado?", "oi", "asdfgh", "dia"],
)
def test_so_data_falso(reserva, mensagem):
    assert reserva._so_data(mensagem, extrair_entidades(mensagem, AGORA)) is False


def test_sabado_solto_pergunta_reserva_ou_horario(reserva, estado):
    r = reserva.responder("Sábado", estado)
    assert r.tipo == "esclarecimento"
    assert "reserva para sábado, 21 de novembro de 2026" in r.texto
    assert "horário de funcionamento nesse dia" in r.texto
    assert estado.esclarecimento == ESCLARECIMENTO_DATA
    assert estado.ultima_data == "2026-11-21"
    assert estado.etapa_reserva is None


def test_data_solta_escolhendo_reserva_preenche_a_data(reserva, estado):
    reserva.responder("Sábado", estado)
    r = reserva.responder("reserva", estado)
    assert r.intencao == "reserva"
    assert estado.etapa_reserva == "coletando"
    assert estado.slots == {"data": "2026-11-21"}
    assert r.texto.endswith(MENSAGENS_RESERVA["pergunta_pessoas"])
    assert estado.esclarecimento is None
    assert estado.data_solta is None


def test_data_solta_com_horario_preenche_os_dois_slots(reserva, estado):
    r = reserva.responder("sábado às 20h", estado)
    assert ", às 20:00, ou saber" in r.texto
    reserva.responder("mesa", estado)
    assert estado.slots == {"data": "2026-11-21", "horario": "20:00"}


def test_amanha_a_noite_escolhendo_horario(reserva, estado):
    r = reserva.responder("amanhã à noite", estado)
    assert r.tipo == "esclarecimento"
    assert "quinta-feira, 19 de novembro de 2026" in r.texto
    r = reserva.responder("horário", estado)
    assert r.intencao == "horario_localizacao"
    assert r.texto.startswith("Na quinta-feira (19/11) abrimos")
    assert estado.esclarecimento is None
    assert estado.assunto_anterior == "horario_localizacao"


def test_segunda_solta_escolhendo_horario_informa_fechado(reserva, estado):
    r = reserva.responder("segunda", estado)
    assert r.tipo == "esclarecimento"
    r = reserva.responder("horário", estado)
    assert r.texto == "Na segunda-feira (23/11) o restaurante fica fechado."


def test_data_solta_resolvida_pelo_classificador(reserva, estado):
    reserva.responder("Sábado", estado)
    r = reserva.responder("que horas vocês abrem?", estado)
    assert r.texto.startswith("No sábado (21/11) abrimos")


@pytest.mark.parametrize("palavra, intencao", [("reservar", "reserva"), ("abre?", "horario_localizacao"),
                                               ("funcionamento", "horario_localizacao")])
def test_palavras_chave_resolvem_o_esclarecimento(reserva, estado, palavra, intencao):
    reserva.responder("Sábado", estado)
    assert reserva.responder(palavra, estado).intencao == intencao


def test_heranca_continua_valendo_com_assunto_anterior(reserva, estado):
    reserva.responder("que horas abrem sábado?", estado)
    r = reserva.responder("e no domingo?", estado)
    assert r.tipo == "aceita"
    assert r.herdou_contexto is True
    assert r.texto.startswith("No domingo (22/11)")
    assert estado.esclarecimento is None


def test_durante_reserva_data_preenche_o_slot(reserva, estado):
    reserva.responder("quero reservar uma mesa", estado)
    r = reserva.responder("sábado", estado)
    assert r.tipo == "reserva"
    assert estado.slots == {"data": "2026-11-21"}
    assert estado.esclarecimento is None


def test_fallback_descarta_a_data_solta(reserva, estado):
    reserva.responder("Sábado", estado)
    reserva.responder("asdfgh", estado)
    assert estado.esclarecimento is None
    assert estado.data_solta is None
    # Sem o pendente, "reserva" e so uma reserva nova, sem data.
    reserva.responder("quero reservar uma mesa", estado)
    assert "data" not in estado.slots
