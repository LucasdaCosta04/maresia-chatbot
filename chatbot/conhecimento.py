"""Respostas de horario_localizacao sem data, a partir da base de conhecimento.

responder_horario_localizacao identifica o subtema da mensagem (endereco,
como chegar, estacionamento, aberto agora, horario geral) por palavras-chave gerais sobre o
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
        r"\b(?:endereco|onde (?:voces )?(?:fica\w*|e|esta\w*)|localiza\w*|mapa|local|cep"
        r"|(?:fica|e|esta|ficam) (?:perto|longe)|praia|bairro|regiao)\b"
    ),
    "como_chegar": re.compile(
        r"\b(?:cheg\w*|caminho|carro|aplicativo|app|uber|taxi|bicicleta|bike|a pe|caminhando)\b"
    ),
    "estacionamento": re.compile(r"\b(?:estacion\w*|vagas?)\b"),
    # "e e pago?" depois de "tem estacionamento?" (campo gratuito da base). Com
    # "estacionamento" na mesma mensagem, a resposta completa ja diz isso.
    "estacionamento_custo": re.compile(r"\b(?:pago|paga|pagar|gratuito|gratis|cobra\w*)\b"),
    "aberto_agora": re.compile(
        r"\b(?:agora|abert[oa] hoje|ainda da tempo|ainda (?:esta |estao |ta |tao )?abert[oa]s?"
        r"|(?:esta|estao|ta|tao) (?:abert[oa]s?|funcionando))\b"
    ),
    # Horario da semana inteira ("qual o horario de funcionamento?"). Com
    # aberto_agora na mesma mensagem, vale so aberto_agora (ver _subtemas).
    "horario_geral": re.compile(
        r"\b(?:horarios?|funcionamento|funcion(?:a|am)|abre|abrem|fecha|fecham"
        r"|que horas|que dias|atendimento|expediente)\b"
    ),
}

# Feriados e datas especiais: o horario geral acrescenta a observacao da base.
RE_FERIADO = re.compile(r"\b(?:feriados?|natal|ano novo|reveillon|carnaval|vespera)\b")

# Nomes curtos dos dias, na ordem de date.weekday().
_NOMES_CURTOS_DIAS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")

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
    "estacionamento_gratuito": "O estacionamento é gratuito, com {vagas} vagas. {observacao}",
    "estacionamento_pago": "O estacionamento é pago. {observacao}",
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
    "horario_geral": (
        "Nosso horário de funcionamento: {grupos}. "
        "A cozinha recebe o último pedido {antes} minutos antes de fechar."
    ),
    "grupo_aberto": "{dias}, {turnos}",
    "grupo_fechado": "{dias}, fechado",
    "turno_geral": "{turno} das {abre} às {fecha}",
}


def _subtemas(texto: str) -> list[str]:
    """Subtemas presentes no texto, na ordem em que aparecem."""
    posicoes = []
    for nome, padrao in SUBTEMAS.items():
        achado = padrao.search(texto)
        if achado:
            posicoes.append((achado.start(), nome))
    nomes = [nome for _, nome in sorted(posicoes)]
    if "aberto_agora" in nomes and "horario_geral" in nomes:
        nomes.remove("horario_geral")
    if "estacionamento" in nomes and "estacionamento_custo" in nomes:
        nomes.remove("estacionamento_custo")
    return nomes


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


def _estacionamento_custo(restaurante: dict) -> str:
    """Se o estacionamento e gratuito (campo gratuito da base)."""
    estacionamento = restaurante["estacionamento"]
    chave = "estacionamento_gratuito" if estacionamento["gratuito"] else "estacionamento_pago"
    return MENSAGENS_CONHECIMENTO[chave].format(**estacionamento)


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


def _horario_geral(texto: str, base: dict) -> str:
    """Horario da semana, juntando dias seguidos com o mesmo horario."""
    dias = base["funcionamento"]["dias"]
    grupos: list[tuple[list[int], dict | None]] = []
    for indice, chave in enumerate(_CHAVES_DIAS):
        info = dias[chave]
        horario = {t: info[t] for t in _TURNOS if info["aberto"] and info.get(t)} or None
        if grupos and grupos[-1][1] == horario:
            grupos[-1][0].append(indice)
        else:
            grupos.append(([indice], horario))

    partes = []
    for indices, horario in grupos:
        nome_dias = _nome_grupo_dias(indices)
        if horario is None:
            partes.append(MENSAGENS_CONHECIMENTO["grupo_fechado"].format(dias=nome_dias))
            continue
        turnos = " e ".join(
            MENSAGENS_CONHECIMENTO["turno_geral"].format(
                turno=_NOMES_TURNOS[t], abre=horario[t]["abre"], fecha=horario[t]["fecha"]
            )
            for t in horario
        )
        partes.append(MENSAGENS_CONHECIMENTO["grupo_aberto"].format(dias=nome_dias, turnos=turnos))

    resposta = MENSAGENS_CONHECIMENTO["horario_geral"].format(
        grupos="; ".join(partes), antes=base["funcionamento"]["ultimo_pedido_minutos_antes"]
    )
    if RE_FERIADO.search(texto):
        resposta += " " + base["funcionamento"]["observacao_feriados"]
    return resposta


def _nome_grupo_dias(indices: list[int]) -> str:
    """[1, 2, 3] -> 'Terça a quinta'; [4, 5] -> 'Sexta e sábado'; [0] -> 'Segunda'."""
    nomes = [_NOMES_CURTOS_DIAS[i] for i in indices]
    if len(nomes) == 1:
        texto = nomes[0]
    elif len(nomes) == 2:
        texto = f"{nomes[0]} e {nomes[1]}"
    else:
        texto = f"{nomes[0]} a {nomes[-1]}"
    return texto[0].upper() + texto[1:]


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
        "estacionamento_custo": lambda: _estacionamento_custo(restaurante),
        "aberto_agora": lambda: _aberto_agora(base, agora),
        "horario_geral": lambda: _horario_geral(texto, base),
    }
    return " ".join(partes[subtema]() for subtema in subtemas)
