"""Testes do arquivo dados/casos_teste.csv via scripts/checar_casos_teste.py."""

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "checar_casos_teste.py"
_spec = importlib.util.spec_from_file_location("checar_casos_teste", _SCRIPT)
checar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checar)


@pytest.fixture(scope="module")
def casos():
    return checar.ler_casos()


def test_estrutura_e_distribuicao_validas(casos):
    cabecalho, linhas = casos
    assert checar.validar(cabecalho, linhas) == []


def test_sem_copias_nem_quase_copias_do_treino(casos):
    _, linhas = casos
    ids = [caso["id"] for caso in linhas]
    mensagens = [caso["mensagem"] for caso in linhas]
    erros, similares = checar.checar_copias(ids, mensagens, checar.ler_frases_treino())
    assert erros == []
    assert len(similares) == checar.TOTAL_CASOS


def test_validar_detecta_categoria_tipo_e_intencao_invalidas(casos):
    cabecalho, linhas = casos
    alterados = [dict(caso) for caso in linhas]
    alterados[0].update(
        categoria="inventada", tipo_esperado="aceita|chute", intencao_esperada="pagamento"
    )
    erros = checar.validar(cabecalho, alterados)
    assert any("categoria invalida" in e for e in erros)
    assert any("tipo_esperado invalido" in e for e in erros)
    assert any("intencao_esperada invalida" in e for e in erros)


def test_validar_detecta_id_repetido_e_total_errado(casos):
    cabecalho, linhas = casos
    alterados = [dict(caso) for caso in linhas[:-1]]
    alterados[1]["id"] = alterados[0]["id"]
    erros = checar.validar(cabecalho, alterados)
    assert any("ids repetidos" in e for e in erros)
    assert any(f"esperado {checar.TOTAL_CASOS} casos" in e for e in erros)


def test_checar_copias_detecta_copia_normalizada():
    treino = ["Vocês abrem no domingo?", "qual o endereço"]
    erros, _ = checar.checar_copias(["T01"], ["voces abrem no DOMINGO"], treino)
    assert erros and "copia normalizada" in erros[0]
