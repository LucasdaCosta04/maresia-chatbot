"""Parametros ajustaveis da Maresia (limiares, caminhos e fuso horario)."""

from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent

LIMIAR_CONFIANCA = 0.45
MARGEM_MINIMA = 0.15
MAX_FALHAS_SEGUIDAS = 2
CAMINHO_BASE = _RAIZ / "dados" / "base_conhecimento.json"
CAMINHO_MODELO = _RAIZ / "modelos"
FUSO_HORARIO = "America/Sao_Paulo"
