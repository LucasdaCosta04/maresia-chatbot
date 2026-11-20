"""Testes da API Flask (app.py)."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import app as modulo_app
from app import create_app
from chatbot.config import FUSO_HORARIO, MAX_CARACTERES_MENSAGEM
from chatbot.dialogo import carregar_base, mensagem_boas_vindas
from chatbot.modelo import carregar_dataset, treinar_modelo

# Quarta-feira, 18/11/2026, 18:00: sabado seguinte = 21/11/2026.
AGORA = datetime(2026, 11, 18, 18, 0, tzinfo=ZoneInfo(FUSO_HORARIO))
CAMPOS_RESPOSTA = {
    "resposta", "intencao", "tipo", "confianca", "margem", "alternativas",
    "herdou_contexto", "encaminhado", "falhas_seguidas", "sessao",
    "decisao", "encaminhar_humano",
}
# Campos extras do painel "Como a Maresia entendeu" (retrocompativeis).
CAMPOS_PAINEL = {
    "texto_original", "texto_normalizado", "tokens", "entidades", "limiar",
    "margem_minima", "probabilidades", "contexto", "modelo",
}


@pytest.fixture(scope="module")
def modelo():
    return treinar_modelo(*carregar_dataset())


@pytest.fixture
def cliente(modelo):
    app = create_app(modelo=modelo, agora=lambda: AGORA)
    app.testing = True
    return app.test_client()


def _enviar(cliente, mensagem, sessao=None, rota="/api/mensagem"):
    corpo = {"mensagem": mensagem}
    if sessao is not None:
        corpo["sessao"] = sessao
    return cliente.post(rota, json=corpo)


# --- /api/saude ---------------------------------------------------------------

def test_saude(cliente):
    resposta = cliente.get("/api/saude")
    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert {k: dados[k] for k in ("status", "modelo_carregado", "sessoes_ativas")} == {
        "status": "ok", "modelo_carregado": True, "sessoes_ativas": 0,
    }
    assert dados["limiar"] == 0.45
    assert dados["margem_minima"] == 0.15
    assert dados["modelo"]["carregado"] is True
    assert "reserva" in dados["modelo"]["intencoes"]


def test_saude_conta_sessoes(cliente):
    _enviar(cliente, "oi")
    _enviar(cliente, "oi")
    assert cliente.get("/api/saude").get_json()["sessoes_ativas"] == 2


# --- /api/mensagem --------------------------------------------------------------

def test_mensagem_aceita(cliente):
    resposta = _enviar(cliente, "que horas vocês abrem no sábado?")
    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert set(dados) == CAMPOS_RESPOSTA | CAMPOS_PAINEL
    assert dados["tipo"] == "aceita"
    assert dados["decisao"] == "aceita"
    assert dados["intencao"] == "horario_localizacao"
    assert dados["resposta"].startswith("No sábado (21/11)")
    assert 0 < dados["confianca"] <= 1
    assert dados["margem"] is not None
    assert len(dados["alternativas"]) == 3
    assert dados["alternativas"][0]["intencao"] == "horario_localizacao"
    assert dados["herdou_contexto"] is False
    assert dados["encaminhado"] is False
    assert dados["encaminhar_humano"] is False
    assert dados["sessao"]


def test_mensagem_campos_do_painel(cliente):
    dados = _enviar(cliente, "Quero reservar mesa p/ 4 no sábado às 20h").get_json()
    assert dados["texto_original"] == "Quero reservar mesa p/ 4 no sábado às 20h"
    assert dados["texto_normalizado"] == "quero reservar mesa para num no sabado as num h"
    assert dados["tokens"] == dados["texto_normalizado"].split()
    assert dados["entidades"]["pessoas"] == 4
    assert dados["entidades"]["data"] == "2026-11-21"
    assert dados["entidades"]["horario"] == "20:00"
    assert dados["limiar"] == 0.45 and dados["margem_minima"] == 0.15
    probs = dados["probabilidades"]
    assert max(probs, key=probs.get) == dados["alternativas"][0]["intencao"]
    assert {"assunto", "etapa_reserva", "slots", "falhas_seguidas", "encaminhado",
            "herdou_contexto"} <= set(dados["contexto"])
    assert dados["modelo"]["tipo"]


def test_alias_api_chat(cliente):
    resposta = _enviar(cliente, "que horas vocês abrem no sábado?", rota="/api/chat")
    assert resposta.status_code == 200
    assert resposta.get_json()["intencao"] == "horario_localizacao"


def test_regra_sem_classificador_tem_alternativas_vazias(cliente):
    dados = _enviar(cliente, "oi").get_json()
    assert dados["tipo"] == "regra"
    assert dados["confianca"] is None
    assert dados["margem"] is None
    assert dados["alternativas"] == []


def test_sessao_nova_e_reaproveitada(cliente):
    primeira = _enviar(cliente, "quero reservar uma mesa para 4 sábado às 20h").get_json()
    sessao = primeira["sessao"]
    assert sessao
    assert primeira["intencao"] == "reserva"
    assert "Em nome de quem" in primeira["resposta"]

    # Mesma sessao: a reserva continua (o nome completa os slots).
    segunda = _enviar(cliente, "em nome de Ana", sessao=sessao).get_json()
    assert segunda["sessao"] == sessao
    assert "Confere os dados da reserva" in segunda["resposta"]
    assert "sábado, 21 de novembro de 2026" in segunda["resposta"]


def test_heranca_de_contexto_pela_api(cliente):
    sessao = _enviar(cliente, "que horas vocês abrem no sábado?").get_json()["sessao"]
    dados = _enviar(cliente, "e no domingo?", sessao=sessao).get_json()
    assert dados["herdou_contexto"] is True


def test_sessao_desconhecida_gera_nova(cliente):
    dados = _enviar(cliente, "oi", sessao="nao-existe").get_json()
    assert dados["sessao"] != "nao-existe"


def test_sessoes_diferentes_nao_se_misturam(cliente):
    a = _enviar(cliente, "quero reservar uma mesa para 4 sábado às 20h").get_json()["sessao"]
    b = _enviar(cliente, "em nome de Ana").get_json()
    assert b["sessao"] != a
    assert "Confere os dados" not in b["resposta"]


# --- Validacao (400) ------------------------------------------------------------

@pytest.mark.parametrize("corpo", [{"mensagem": ""}, {"mensagem": "   "}, {"mensagem": 123}])
def test_mensagem_vazia_ou_invalida(cliente, corpo):
    resposta = cliente.post("/api/mensagem", json=corpo)
    assert resposta.status_code == 400
    assert "mensagem" in resposta.get_json()["erro"]


def test_mensagem_ausente(cliente):
    resposta = cliente.post("/api/mensagem", json={"sessao": "x"})
    assert resposta.status_code == 400


def test_mensagem_longa_demais(cliente):
    resposta = _enviar(cliente, "a" * (MAX_CARACTERES_MENSAGEM + 1))
    assert resposta.status_code == 400
    assert str(MAX_CARACTERES_MENSAGEM) in resposta.get_json()["erro"]


def test_mensagem_no_limite_e_aceita(cliente):
    assert _enviar(cliente, "a" * MAX_CARACTERES_MENSAGEM).status_code == 200


@pytest.mark.parametrize(
    "dados, tipo",
    [("{isso nao e json", "application/json"), ("[1, 2]", "application/json"),
     ("mensagem=oi", "application/x-www-form-urlencoded")],
)
def test_json_invalido(cliente, dados, tipo):
    resposta = cliente.post("/api/mensagem", data=dados, content_type=tipo)
    assert resposta.status_code == 400
    assert "JSON" in resposta.get_json()["erro"]


# --- /api/reiniciar -------------------------------------------------------------

def test_reiniciar_limpa_o_estado(cliente):
    sessao = _enviar(cliente, "quero reservar uma mesa para 4 sábado às 20h").get_json()["sessao"]

    dados = cliente.post("/api/reiniciar", json={"sessao": sessao}).get_json()
    assert dados["sessao"] == sessao
    assert dados["resposta"] == mensagem_boas_vindas(carregar_base())

    # Sem a reserva em andamento, o nome sozinho nao completa nada.
    depois = _enviar(cliente, "em nome de Ana", sessao=sessao).get_json()
    assert "Confere os dados" not in depois["resposta"]


def test_reiniciar_sem_sessao_cria_uma(cliente):
    resposta = cliente.post("/api/reiniciar", json={})
    assert resposta.status_code == 200
    assert resposta.get_json()["sessao"]


def test_reiniciar_sem_corpo(cliente):
    assert cliente.post("/api/reiniciar").status_code == 200


# --- Sem modelo (503) -------------------------------------------------------------

def test_sem_modelo_responde_503(monkeypatch):
    def sem_arquivo():
        raise FileNotFoundError("Modelo nao encontrado. Rode python treinar.py")

    monkeypatch.setattr(modulo_app, "carregar_modelo", sem_arquivo)
    cliente = create_app().test_client()

    assert cliente.get("/api/saude").get_json()["modelo_carregado"] is False
    resposta = _enviar(cliente, "oi")
    assert resposta.status_code == 503
    assert "python treinar.py" in resposta.get_json()["erro"]
    # Reiniciar nao depende do modelo.
    assert cliente.post("/api/reiniciar", json={}).status_code == 200


# --- Erros e pagina inicial --------------------------------------------------------

def test_404_em_json(cliente):
    resposta = cliente.get("/nao/existe")
    assert resposta.status_code == 404
    assert resposta.is_json
    assert resposta.get_json()["erro"] == "Rota não encontrada."


def test_405_em_json(cliente):
    resposta = cliente.get("/api/mensagem")
    assert resposta.status_code == 405
    assert resposta.is_json
    assert "Método não permitido" in resposta.get_json()["erro"]


def test_pagina_inicial(cliente):
    resposta = cliente.get("/")
    assert resposta.status_code == 200
    texto = resposta.get_data(as_text=True)
    if (Path(modulo_app.__file__).parent / "templates" / "index.html").exists():
        assert "Como a Maresia entendeu" in texto
        assert "/static/script.js" in texto
    else:
        assert "interface web ainda não foi criada" in texto
        assert "POST /api/mensagem" in texto


# --- Interface web ---------------------------------------------------------------

def test_interface_html(cliente):
    resposta = cliente.get("/")
    assert resposta.status_code == 200
    assert resposta.mimetype == "text/html"
    texto = resposta.get_data(as_text=True)
    assert "Tempero Açoriano" in texto
    assert "Como a Maresia entendeu" in texto


@pytest.mark.parametrize("arquivo", ["styles.css", "script.js"])
def test_arquivos_estaticos(cliente, arquivo):
    resposta = cliente.get(f"/static/{arquivo}")
    try:
        assert resposta.status_code == 200
        assert resposta.get_data()  # nao vazio
    finally:
        resposta.close()


def test_api_chat_chaves_originais_e_explicabilidade(cliente):
    resposta = _enviar(cliente, "Quero reservar mesa p/ 4 no sábado às 20h", rota="/api/chat")
    assert resposta.status_code == 200
    dados = resposta.get_json()

    # Retrocompatibilidade: todas as chaves originais continuam presentes.
    assert CAMPOS_RESPOSTA <= set(dados)

    campos_explicabilidade = {
        "texto_original", "texto_normalizado", "entidades",
        "limiar", "probabilidades", "contexto",
    }
    assert campos_explicabilidade <= set(dados)
    assert dados["texto_original"] == "Quero reservar mesa p/ 4 no sábado às 20h"
    assert isinstance(dados["texto_normalizado"], str) and dados["texto_normalizado"]
    assert isinstance(dados["entidades"], dict)
    assert isinstance(dados["limiar"], float)
    assert isinstance(dados["probabilidades"], dict) and dados["probabilidades"]
    assert abs(sum(dados["probabilidades"].values()) - 1) < 1e-3
    assert isinstance(dados["contexto"], dict)
