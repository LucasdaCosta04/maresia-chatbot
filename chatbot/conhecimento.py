"""Respostas de horario_localizacao sem data, a partir da base de conhecimento.

responder_horario_localizacao identifica o subtema da mensagem (endereco,
como chegar, estacionamento, aberto agora) por palavras-chave gerais sobre o
texto pre-processado e monta a resposta so com dados da base. Sem subtema
reconhecido devolve None, e o dialogo mantem as respostas_fixas.

O horario de um dia e as conversoes de hora vem de chatbot.dialogo, para as
regras de funcionamento ficarem num lugar so.
"""

import re
from datetime import date, datetime, timedelta

from chatbot.dialogo import (
    _CHAVES_DIAS,
    _NOMES_TURNOS,
    _TURNOS,
    GerenciadorDialogo,
    _hhmm,
    _minutos,
)
from chatbot.preprocessamento import preprocessar

# Palavras-chave de cada subtema, sobre o texto pre-processado (minusculas,
# sem acento, abreviacoes expandidas).
SUBTEMAS = {
    "endereco": re.compile(
        r"\b(?:endereco|onde (?:voces )?(?:fica\w*|e|esta\w*)|localiza\w*|mapa|local)\b"
    ),
    "como_chegar": re.compile(
        r"\b(?:cheg\w*|caminho|carro|aplicativo|app|uber|taxi|bicicleta|bike|a pe|caminhando)\b"
    ),
    "estacionamento": re.compile(r"\b(?:estacion\w*|vagas?)\b"),
    "aberto_agora": re.compile(
        r"\b(?:agora|abert[oa] hoje|ainda da tempo|ainda (?:esta |estao |ta |tao )?abert[oa]s?)\b"
    ),
}

# Meios de transporte de como_chegar na base -> palavras-chave.
MEIOS_TRANSPORTE = {
    "carro": re.compile(r"\bcarro\b"),
    "aplicativo": re.compile(r"\b(?:aplicativo|app|uber|taxi)\b"),
    "bicicleta": re.compile(r"\b(?:bicicleta|bike)\b"),
    "a_pe": re.compile(r"\b(?:a pe|caminhando)\b"),
}
NOMES_MEIOS = {
    "carro": "De carro",
    "aplicativo": "De aplicativo ou táxi",
    "bicicleta": "De bicicleta",
    "a_pe": "A pé",
}

MENSAGENS_CONHECIMENTO = {
    "endereco": "Ficamos na {logradouro}, {numero}, {bairro}, {cidade}/{uf} (CEP {cep}). {referencia}",
    "meio": "{meio}: {texto}",
    "estacionamento": (
        "Temos estacionamento {tipo}, com {vagas} vagas ({vagas_pcd} para PcD e "
        "{vagas_idosos} para idosos). {motos} {bicicletario} {observacao}"
    ),
    "aberto": (
        "Sim, estamos abertos agora! O {turno} vai até as {fecha} "
        "(último pedido às {ultimo_pedido})."
    ),
    "aberto_sem_pedido": (
        "Estamos abertos até as {fecha}, mas o último pedido do {turno} "
        "é às {ultimo_pedido}, então a cozinha já não recebe pedidos."
    ),
    "reabre_hoje": "Agora estamos fechados. Hoje abrimos às {abre}, no {turno}.",
    "fechado": "Agora estamos fechados. {proximo}",
}


def _subtemas(texto: str) -> list[str]:
    """Subtemas presentes no texto, na ordem em que aparecem."""
    posicoes = []
    for nome, padrao in SUBTEMAS.items():
        achado = padrao.search(texto)
        if achado:
            posicoes.append((achado.start(), nome))
    return [nome for _, nome in sorted(posicoes)]


def _endereco(restaurante: dict) -> str:
    """Endereco completo e ponto de referencia."""
    return MENSAGENS_CONHECIMENTO["endereco"].format(
        referencia=restaurante["ponto_referencia"], **restaurante["endereco"]
    )


def _como_chegar(texto: str, restaurante: dict) -> str:
    """Meio de transporte citado na mensagem; sem nenhum citado, todos."""
    meios = [meio for meio, padrao in MEIOS_TRANSPORTE.items() if padrao.search(texto)]
    meios = meios or list(MEIOS_TRANSPORTE)
    return " ".join(
        MENSAGENS_CONHECIMENTO["meio"].format(
            meio=NOMES_MEIOS[meio], texto=restaurante["como_chegar"][meio]
        )
        for meio in meios
    )


def _estacionamento(restaurante: dict) -> str:
    """Dados do estacionamento."""
    return MENSAGENS_CONHECIMENTO["estacionamento"].format(**restaurante["estacionamento"])


def _aberto_agora(base: dict, agora: datetime) -> str:
    """Se esta aberto agora (e ate quando), quando reabre hoje ou o proximo dia aberto."""
    dias = base["funcionamento"]["dias"]
    antes_ultimo_pedido = base["funcionamento"]["ultimo_pedido_minutos_antes"]
    hoje = dias[_CHAVES_DIAS[agora.weekday()]]
    minutos = agora.hour * 60 + agora.minute
    turnos = [t for t in _TURNOS if hoje["aberto"] and hoje.get(t)]
    for turno in turnos:
        abre, fecha = _minutos(hoje[turno]["abre"]), _minutos(hoje[turno]["fecha"])
        if abre <= minutos < fecha:
            ultimo = fecha - antes_ultimo_pedido
            chave = "aberto" if minutos < ultimo else "aberto_sem_pedido"
            return MENSAGENS_CONHECIMENTO[chave].format(
                turno=_NOMES_TURNOS[turno], fecha=_hhmm(fecha), ultimo_pedido=_hhmm(ultimo)
            )
        if minutos < abre:
            return MENSAGENS_CONHECIMENTO["reabre_hoje"].format(
                abre=_hhmm(abre), turno=_NOMES_TURNOS[turno]
            )
    return MENSAGENS_CONHECIMENTO["fechado"].format(
        proximo=GerenciadorDialogo(None, base)._horario_do_dia(_proximo_dia_aberto(dias, agora.date()))
    )


def _proximo_dia_aberto(dias: dict, hoje: date) -> date:
    """Primeiro dia aberto depois de hoje (no maximo uma semana a frente)."""
    for avanco in range(1, 8):
        dia = hoje + timedelta(days=avanco)
        if dias[_CHAVES_DIAS[dia.weekday()]]["aberto"]:
            return dia
    raise ValueError("A base nao tem nenhum dia aberto.")


def responder_horario_localizacao(mensagem: str, base: dict, agora: datetime) -> str | None:
    """Resposta de horario_localizacao por subtema; None se nenhum foi reconhecido."""
    texto = preprocessar(mensagem or "")
    subtemas = _subtemas(texto)
    if not subtemas:
        return None
    restaurante = base["restaurante"]
    partes = {
        "endereco": lambda: _endereco(restaurante),
        "como_chegar": lambda: _como_chegar(texto, restaurante),
        "estacionamento": lambda: _estacionamento(restaurante),
        "aberto_agora": lambda: _aberto_agora(base, agora),
    }
    return " ".join(partes[subtema]() for subtema in subtemas)
