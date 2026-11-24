"""Testes da extracao de entidades (chatbot/entidades.py).

Referencia fixa: segunda-feira, 16/11/2026, 10:00 (America/Sao_Paulo).
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from chatbot.entidades import extrair_entidades

REF = datetime(2026, 11, 16, 10, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
CHAVES = {
    "pratos", "pratos_ambiguos", "alergenicos", "grupos_alergenicos", "restricoes",
    "categorias", "preco", "pessoas", "data", "dia_semana", "horario", "horario_ambiguo",
    "periodo", "nome",
}


def extrair(texto):
    return extrair_entidades(texto, referencia=REF)


# --- estrutura -------------------------------------------------------------

def test_frase_sem_entidades_devolve_todas_as_chaves_vazias():
    r = extrair("oi, tudo bem?")
    assert set(r) == CHAVES
    assert r == {
        "pratos": [], "pratos_ambiguos": {}, "alergenicos": [], "grupos_alergenicos": [],
        "restricoes": [], "categorias": [], "preco": None, "pessoas": None, "data": None,
        "dia_semana": None, "horario": None,
        "horario_ambiguo": None, "periodo": None, "nome": None,
    }


def test_texto_vazio():
    assert set(extrair("")) == CHAVES


def test_referencia_padrao_funciona():
    r = extrair_entidades("hoje")
    assert r["data"] is not None


# --- pratos ----------------------------------------------------------------

def test_prato_simples_sem_acento():
    assert extrair("vcs tem tainha escalada?")["pratos"] == ["tainha_escalada"]


def test_sinonimo_mais_longo_vence():
    r = extrair("quero a sequência completa")
    assert r["pratos"] == ["sequencia_camarao_completa"]
    assert r["pratos_ambiguos"] == {}


def test_moqueca_generica_e_ambigua():
    r = extrair("Vocês têm MOQUECA?")
    assert r["pratos"] == []
    assert r["pratos_ambiguos"] == {"moqueca": ["moqueca_peixe", "moqueca_banana_palmito"]}


def test_moqueca_especifica_nao_e_ambigua():
    r = extrair("a moqueca de peixe leva leite de coco?")
    assert r["pratos"] == ["moqueca_peixe"]
    assert r["pratos_ambiguos"] == {}


def test_sequencia_generica_e_ambigua():
    r = extrair("quanto custa a sequencia?")
    assert r["pratos_ambiguos"] == {
        "sequencia": ["sequencia_camarao_tradicional", "sequencia_camarao_completa"]
    }


def test_varios_pratos_em_ordem():
    r = extrair("quero lula a dorê, pudim e cocada")
    assert r["pratos"] == ["lula_a_dore", "pudim_leite", "cocada_forno"]


# --- alergenicos e restricoes ----------------------------------------------

def test_alergenicos_por_sinonimo():
    r = extrair("tenho alergia a camarão e amendoim")
    assert r["alergenicos"] == ["crustaceos", "amendoim"]


def test_termo_de_prato_com_pista_de_alergia_vira_alergenico():
    r = extrair("sou alérgico a lula")
    assert r["alergenicos"] == ["moluscos"]
    assert r["pratos"] == []


def test_termo_de_prato_sem_pista_vira_prato():
    r = extrair("tem lula?")
    assert r["pratos"] == ["lula_a_dore"]
    assert r["alergenicos"] == []


def test_alergenico_dentro_do_nome_do_prato_nao_conta():
    r = extrair("o pudim de leite tem ovo?")
    assert r["pratos"] == ["pudim_leite"]
    assert r["alergenicos"] == ["ovos"]


@pytest.mark.parametrize("texto, esperado", [
    ("sou celíaco", ["sem_gluten"]),
    ("tem algo sem gluten?", ["sem_gluten"]),
    ("sou intolerante a lactose", ["sem_lactose"]),
    ("sou vegetariana", ["vegetariano"]),
    ("tem prato vegano?", ["vegano"]),
])
def test_restricoes(texto, esperado):
    assert extrair(texto)["restricoes"] == esperado


# --- pessoas ---------------------------------------------------------------

@pytest.mark.parametrize("texto, esperado", [
    ("reserva para 4 pessoas", 4),
    ("mesa pra 6", 6),
    ("somos em cinco", 5),
    ("pra dois, por favor", 2),
    ("eu e minha esposa", 2),
    ("é pra um casal", 2),
    ("eu e mais três amigos", 4),
    ("2 adultos e 1 criança", 3),
    ("mesa p/ dez", 10),
])
def test_pessoas(texto, esperado):
    assert extrair(texto)["pessoas"] == esperado


def test_horario_e_dia_nao_viram_pessoas():
    r = extrair("reserva pra 20h dia 20")
    assert r["pessoas"] is None


# --- data ------------------------------------------------------------------

@pytest.mark.parametrize("texto, data, dia", [
    ("hoje", "2026-11-16", "segunda"),
    ("hj", "2026-11-16", "segunda"),
    ("amanha", "2026-11-17", "terca"),
    ("depois de amanhã", "2026-11-18", "quarta"),
    ("sábado", "2026-11-21", "sabado"),
    ("sexta-feira", "2026-11-20", "sexta"),
    ("segunda", "2026-11-16", "segunda"),
    ("segunda que vem", "2026-11-23", "segunda"),
    ("sábado que vem", "2026-11-21", "sabado"),
    ("25/12", "2026-12-25", "sexta"),
    ("10/01", "2027-01-10", "domingo"),
    ("05/03/2027", "2027-03-05", "sexta"),
    ("dia 20", "2026-11-20", "sexta"),
    ("dia 10", "2026-12-10", "quinta"),
    ("20 de dezembro", "2026-12-20", "domingo"),
])
def test_datas(texto, data, dia):
    r = extrair(texto)
    assert (r["data"], r["dia_semana"]) == (data, dia)


def test_data_invalida():
    assert extrair("31/02")["data"] is None


# --- horario e periodo -----------------------------------------------------

@pytest.mark.parametrize("texto, esperado", [
    ("às 20h", "20:00"),
    ("20:30", "20:30"),
    ("lá pelas 20h30", "20:30"),
    ("às 8 da noite", "20:00"),
    ("8 e meia da noite", "20:30"),
    ("meio-dia", "12:00"),
    ("meio dia e meia", "12:30"),
    ("às 08:00", "08:00"),
    ("pro jantar às 8", "20:00"),
    ("almoço à uma", "13:00"),
    ("almoço às 11h30", "11:30"),
    ("hj às oito da noite", "20:00"),
])
def test_horarios(texto, esperado):
    r = extrair(texto)
    assert r["horario"] == esperado
    assert r["horario_ambiguo"] is None


@pytest.mark.parametrize("texto, ambiguo", [
    ("às 8", "08:00|20:00"),
    ("8 e meia", "08:30|20:30"),
    ("pode ser 9h?", "09:00|21:00"),
])
def test_horario_ambiguo(texto, ambiguo):
    r = extrair(texto)
    assert r["horario"] is None
    assert r["horario_ambiguo"] == ambiguo


@pytest.mark.parametrize("texto, esperado", [
    ("reserva pro almoço", "almoco"),
    ("pro jantar", "jantar"),
    ("hoje à noite", "jantar"),
    ("quero reservar", None),
])
def test_periodo(texto, esperado):
    assert extrair(texto)["periodo"] == esperado


# --- nome ------------------------------------------------------------------

@pytest.mark.parametrize("texto, esperado", [
    ("em nome de ana", "Ana"),
    ("meu nome é JOÃO SILVA", "João Silva"),
    ("reserva pro Carlos", "Carlos"),
    ("me chamo maria da silva e sou vegana", "Maria da Silva"),
])
def test_nome(texto, esperado):
    assert extrair(texto)["nome"] == esperado


@pytest.mark.parametrize("texto", [
    "reserva pra sábado",
    "reserva pro jantar",
    "mesa pra 4",
    "reserva pra minha esposa e eu",
])
def test_nome_falso_positivo(texto):
    assert extrair(texto)["nome"] is None


# --- grupos de alergenicos e categorias --------------------------------------

def test_frutos_do_mar_vira_grupo_com_os_ids_da_base():
    r = extrair("quero pratos sem frutos do mar, sou alérgico")
    assert r["grupos_alergenicos"] == ["frutos do mar"]
    assert r["alergenicos"] == ["crustaceos", "moluscos"]
    assert r["pratos"] == []


def test_prato_com_frutos_do_mar_no_nome_continua_prato():
    r = extrair("o risoto de frutos do mar tem glúten?")
    assert r["pratos"] == ["risoto_frutos_mar"]
    assert r["grupos_alergenicos"] == []
    assert r["alergenicos"] == ["trigo_gluten"]


@pytest.mark.parametrize(
    "texto, categorias",
    [
        ("quero pratos principais", ["prato_principal"]),
        ("quais as entradas?", ["entrada"]),
        ("tem sobremesa vegana?", ["sobremesa"]),
        ("tem algum doce sem lactose?", ["sobremesa"]),
        ("entradas e sobremesas", ["entrada", "sobremesa"]),
        ("quero reservar uma mesa", []),
    ],
)
def test_categorias(texto, categorias):
    assert extrair(texto)["categorias"] == categorias


# --- preco -----------------------------------------------------------------

@pytest.mark.parametrize(
    "texto, preco",
    [
        ("tem algo até 50 reais?", {"min": None, "max": 50.0, "ordem": None}),
        ("prato abaixo de R$ 30", {"min": None, "max": 30.0, "ordem": None}),
        ("até R$49,90", {"min": None, "max": 49.9, "ordem": None}),
        ("pratos acima de 100 reais", {"min": 100.0, "max": None, "ordem": None}),
        ("entre 100 e 50 reais", {"min": 50.0, "max": 100.0, "ordem": None}),
        ("qual o prato mais barato?", {"min": None, "max": None, "ordem": "barato"}),
        ("qual a sobremesa mais cara?", {"min": None, "max": None, "ordem": "caro"}),
    ],
)
def test_preco(texto, preco):
    assert extrair(texto)["preco"] == preco


@pytest.mark.parametrize(
    "texto",
    ["reserva para até 10 pessoas", "abre até as 20h?", "mais de 10 pessoas", "quanto custa o pudim?"],
)
def test_numero_sem_faixa_de_preco_nao_vira_preco(texto):
    assert extrair(texto)["preco"] is None


# --- frase completa --------------------------------------------------------

def test_frase_completa():
    r = extrair("mesa pra 4 sábado às 20h em nome de Ana, sou celíaca")
    assert r == {
        "pratos": [],
        "pratos_ambiguos": {},
        "alergenicos": ["trigo_gluten"],
        "grupos_alergenicos": [],
        "restricoes": ["sem_gluten"],
        "categorias": [],
        "preco": None,
        "pessoas": 4,
        "data": "2026-11-21",
        "dia_semana": "sabado",
        "horario": "20:00",
        "horario_ambiguo": None,
        "periodo": None,
        "nome": "Ana",
    }
