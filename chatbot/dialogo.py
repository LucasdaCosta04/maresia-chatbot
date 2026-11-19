"""Gerenciador de dialogo da Maresia.

Para cada mensagem, nesta ordem:
1. regras prioritarias (atendente, cancelar, ajuda, saudacao/despedida),
   avaliadas sobre o texto pre-processado, antes do classificador;
2. se ha uma reserva em andamento, a mensagem e lida como resposta ao passo
   atual (slots via extrair_entidades, confirmacao sim/nao);
3. classificador de intencoes + politica de decisao (modelo.classificar);
4. tratamento da decisao: aceita, esclarecimento, abstencao ou fallback,
   com encaminhamento humano depois de MAX_FALHAS_SEGUIDAS falhas.

Os textos de fallback, esclarecimento, encaminhamento humano, as respostas
de cada intencao, o funcionamento e as regras de reserva vem da base de
conhecimento (CAMINHO_BASE). Os textos que nao existem na base ficam em
MENSAGENS_REGRAS e MENSAGENS_RESERVA.
"""

import json
import random
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from chatbot.config import (
    CAMINHO_BASE,
    FUSO_HORARIO,
    INTENCAO_FORA_ESCOPO,
    MAX_FALHAS_SEGUIDAS,
)
from chatbot.entidades import extrair_entidades
from chatbot.modelo import Decisao, classificar
from chatbot.preprocessamento import preprocessar

# Nome de cada intencao como o cliente le (usado no esclarecimento e na ajuda).
NOMES_INTENCOES = {
    "cardapio_alergenicos": "cardápio e alergênicos",
    "reserva": "reservas",
    "horario_localizacao": "horário e localização",
}

# Textos das regras prioritarias (a base nao tem mensagens para elas).
MENSAGENS_REGRAS = {
    "cancelar": "Tudo bem, cancelei o que estávamos fazendo. Posso te ajudar com outra coisa?",
    "ajuda": (
        "Sou a Maresia, assistente virtual do {restaurante}. Posso te ajudar com:\n"
        "• {assunto_1}: pratos, preços, opções sem glúten ou lactose e alergênicos;\n"
        "• {assunto_2}: fazer, alterar ou cancelar uma reserva;\n"
        "• {assunto_3}: dias e horários de funcionamento, endereço e como chegar.\n"
        "É só perguntar! 🌊"
    ),
    "saudacao": (
        "Olá! Eu sou a Maresia, assistente virtual do {restaurante}. "
        "Posso ajudar com {assunto_1}, {assunto_2} ou {assunto_3}. Em que posso ajudar? 🌊"
    ),
    "despedida": "Eu que agradeço! Até mais e bom apetite. 🌊",
}

# Textos do fluxo de reserva (a base so tem as regras e as politicas).
MENSAGENS_RESERVA = {
    "inicio": "Vamos reservar sua mesa! 🌊",
    "pergunta_pessoas": "Para quantas pessoas é a reserva?",
    "pergunta_data": 'Para qual dia? Pode ser, por exemplo, "sábado" ou "25/11".',
    "pergunta_horario": "Qual horário você prefere? {janelas}",
    "pergunta_nome": "Em nome de quem fica a reserva?",
    "resumo": (
        "Confere os dados da reserva:\n"
        "• Pessoas: {pessoas}\n"
        "• Data: {data}\n"
        "• Horário: {horario}\n"
        "• Nome: {nome}\n"
        "Posso confirmar? (sim/não)"
    ),
    "confirmar_de_novo": "Posso confirmar a reserva? Responda sim ou não.",
    "registrada": (
        "Prontinho, {nome}! Reserva registrada para {pessoas} em {data}, às {horario}. 🌊\n"
        "{politica_atraso}\n"
        "⚠️ Atenção: isto é uma SIMULAÇÃO do projeto acadêmico. "
        "Nenhuma reserva foi gravada de verdade."
    ),
    "o_que_alterar": "Sem problemas! O que você quer alterar: pessoas, data, horário ou nome?",
    "nao_entendi": "Não entendi.",
    "nao_tenho_certeza": "Não tenho certeza do que você quis dizer.",
    "lembrete": "Sobre a sua reserva: {pergunta}",
    # Erros de validacao
    "fechado": "{No_dia} o restaurante fica fechado.",
    "passado": "Essa data já passou.",
    "alem_janela": "Aceitamos reservas com até {dias} dias de antecedência, ou seja, até {limite}.",
    "pessoas_minimo": "A reserva precisa ser para pelo menos {minimo}.",
    "acima_limite": "{mensagem} Fale com a nossa equipe pelo WhatsApp {whatsapp} ou pelo telefone {telefone}.",
    "horario_fora": "Esse horário está fora do nosso período de reservas. {janelas}",
    "antecedencia": "A reserva precisa ser feita com pelo menos {horas} de antecedência.",
}

# Textos das respostas com entidades (horario de um dia e cardapio). Os
# dados (horarios, pratos, alergenicos, avisos) vem da base.
MENSAGENS_CONSULTA = {
    "dia_fechado": "{No_dia} ({data}) o restaurante fica fechado.",
    "dia_aberto": "{No_dia} ({data}) abrimos {turnos}.",
    "turno": "no {turno} das {abre} às {fecha}",
    "prato": "{nome}: {descricao} Serve {serve}. Preço: {preco}.",
    "prato_alergenicos": "Alergênicos: {lista}.",
    "prato_sem_alergenicos": "Não leva nenhum dos alergênicos que controlamos.",
    "prato_pode_conter": "Pode conter traços de: {lista}.",
    "contem": "Sim, {prato} contém {alergenico}.",
    "pode_conter": "{Prato} não leva {alergenico} na receita, mas pode conter traços (contaminação cruzada).",
    "nao_contem": "Não, {prato} não contém {alergenico}.",
    "restricao_sim": "Sim, {prato} é uma opção {restricao}.",
    "restricao_nao": "Não, {prato} não é uma opção {restricao}.",
    "lista_restricao": "Opções {restricao}: {pratos}.",
    "lista_sem_alergenico": "Pratos sem {alergenico}: {pratos}.",
    "lista_com_alergenico": "Pratos que levam {alergenico}: {pratos}.",
    "lista_vazia": "No momento não temos pratos {criterio}.",
    "prato_ambiguo": "Temos {opcoes}. Sobre qual você quer saber?",
}

# Restricoes de extrair_entidades -> como aparecem no texto ("opcao vegana").
_NOMES_RESTRICOES = {
    "vegetariano": "vegetariana",
    "vegano": "vegana",
    "sem_gluten": "sem glúten",
    "sem_lactose": "sem lactose",
}
_NOMES_TURNOS = {"almoco": "almoço", "jantar": "jantar"}

# Indices das mensagens de encaminhamento_humano na base: a 1a fala de
# "nao estou conseguindo te ajudar" (falhas); a 2a, de "vou te passar para
# um atendente" (pedido explicito).
_ENCAMINHAR_POR_FALHAS = 0
_ENCAMINHAR_POR_PEDIDO = 1

# Ordem em que os slots da reserva sao pedidos.
SLOTS_RESERVA = ("pessoas", "data", "horario", "nome")

# Chaves de funcionamento.dias na base, na ordem de date.weekday().
_CHAVES_DIAS = ("segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo")
_NOMES_DIAS = (
    "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
    "sexta-feira", "sábado", "domingo",
)
_NOMES_MESES = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
    "agosto", "setembro", "outubro", "novembro", "dezembro",
)
_TURNOS = ("almoco", "jantar")

# --- Regras prioritarias ------------------------------------------------------
# Todas rodam sobre o texto de preprocessar(): minusculas, sem acento, sem
# pontuacao e com abreviacoes expandidas ("pra" -> "para", "vc" -> "voce").

# a) Atendente: pode aparecer em qualquer parte da mensagem. "pessoa" so
# conta em "falar com (uma) pessoa" ou "pessoa real", para nao casar com
# "mesa para uma pessoa".
_RE_ATENDENTE = re.compile(
    r"\b(?:atendentes?|humanos?|gerentes?)\b"
    r"|\bfalar com (?:uma |alguma |um )?(?:pessoa|alguem)\b"
    r"|\bpessoa (?:de verdade|real)\b"
)

# Palavras de cortesia que podem acompanhar um comando curto.
_EXTRAS = r"(?:por favor|isso|tudo|entao|ai|ok|ah|pode|maresia|tudo bem|tudo bom)"

# b) Cancelar e c) Ajuda: so quando a mensagem e o proprio comando (com
# cortesias em volta). O dataset tem frases como "quero cancelar minha
# reserva" (reserva) e "me ajuda com um erro no meu codigo" (fora_escopo),
# que precisam ir para o classificador.
_RE_CANCELAR = re.compile(
    rf"^(?:{_EXTRAS} )*(?:cancelar|cancela|deixa para la|esquece)(?: {_EXTRAS})*$"
)
# Durante uma reserva em andamento, a unica coisa a cancelar e ela mesma:
# "quero cancelar a reserva" ou "desisti" tambem encerram o fluxo.
_RE_CANCELAR_NO_FLUXO = re.compile(r"\b(?:cancelar|cancela|cancele|desisto|desisti)\b")
_RE_AJUDA = re.compile(
    rf"^(?:{_EXTRAS} )*(?:ajuda|me ajuda|preciso de ajuda|o que voces? faz(?:em)?"
    rf"|como funciona|como voce funciona|menu)(?: {_EXTRAS})*$"
)

# d) Saudacao e despedida: so quando a mensagem e apenas isso. Assim
# "oi, quero reservar uma mesa" vai para o classificador.
_SAUDACOES = r"(?:oi|ola|bom dia|boa tarde|boa noite|e ai)"
_DESPEDIDAS = r"(?:tchau|obrigad[oa]|muito obrigad[oa]|valeu|ate mais|ate logo)"
_RE_SAUDACAO = re.compile(rf"^{_SAUDACOES}(?: (?:{_SAUDACOES}|{_EXTRAS}))*$")
_RE_DESPEDIDA = re.compile(rf"^{_DESPEDIDAS}(?: (?:{_DESPEDIDAS}|{_EXTRAS}))*$")

# --- Reserva ------------------------------------------------------------------

# Confirmacao do resumo: a mensagem inteira e um "sim".
_RE_SIM = re.compile(
    r"^(?:sim|s|confirmo|confirma|confirmar|pode|pode sim|pode confirmar|isso|isso mesmo"
    r"|ok|claro|certo|fechado|beleza|perfeito)(?: (?:sim|por favor|pode|confirmo|obrigado|obrigada))*$"
)
# Negacao: a mensagem comeca com "nao" (pode vir junto uma correcao).
_RE_NAO = re.compile(r"^(?:nao|n)\b")
# Qual slot o cliente quer alterar ("quero mudar o horario").
_RE_SLOT_ALTERAR = {
    "pessoas": re.compile(r"\b(?:pessoas?|quantidade|numero de pessoas)\b"),
    "data": re.compile(r"\b(?:data|dia)\b"),
    "horario": re.compile(r"\b(?:horario|hora)\b"),
    "nome": re.compile(r"\bnome\b"),
}
_RE_VERBO_ALTERAR = re.compile(r"\b(?:alter\w*|mud\w*|troc\w*|corrig\w*|errad[oa])\b")
# Resposta curta de uma palavra so ("4", "quatro", "20"): sem a palavra
# "pessoas" ou "h", extrair_entidades nao sabe o que ela e. "num" e como o
# preprocessar() deixa um numero em algarismos.
_RE_SO_NUMERO = re.compile(r"^(?:num|[a-z]+)$")
# Resposta que parece um nome proprio: 1 a 4 palavras so com letras.
_RE_PARECE_NOME = re.compile(r"^[^\W\d_]+(?:[ '-][^\W\d_]+){0,3}$")
# Pedidos sobre uma reserva ja existente: respondidos com a politica da base,
# sem abrir o fluxo de uma reserva nova.
_RE_POLITICAS = (
    ("politica_cancelamento", re.compile(r"\b(?:cancel\w*|desmarc\w*|desist\w*)\b")),
    ("politica_alteracao", re.compile(
        r"\b(?:alter\w*|mudar|muda|remarc\w*|antecip\w*|adia\w*|troc\w*)\b"
    )),
    ("politica_atraso", re.compile(r"\b(?:atras\w*|toleranc\w*)\b")),
)


# --- Heranca de contexto ------------------------------------------------------

# Mensagem curta o bastante para ser continuacao do turno anterior.
MAX_PALAVRAS_HERANCA = 6
# Pronome que aponta para o prato do turno anterior ("ele tem gluten?").
_RE_PRONOME = re.compile(
    r"\b(?:ele|ela|eles|elas|esse|essa|esses|essas|este|isso|isto"
    r"|dele|dela|nele|nela|desse|dessa|nesse|nessa|disso|nisso)\b"
)
# Pista de que o cliente quer EVITAR o alergenico ("sou alergico a camarao",
# "sem lactose"). Sem ela, "tem camarao?" lista os pratos que levam camarao.
_RE_EVITAR = re.compile(
    r"\b(?:sem|alergi\w*|alergic\w*|intoleran\w*|nao (?:como|posso|pode)|evit\w*|restric\w*)\b"
)


@dataclass
class EstadoConversa:
    """Estado de uma conversa entre uma mensagem e outra.

    falhas_seguidas: mensagens seguidas sem entender (fallback).
    assunto_anterior: intencao da ultima resposta aceita.
    esclarecimento: intencoes candidatas aguardando o cliente escolher.
    slots: dados da reserva em andamento (pessoas, data, horario, nome).
    encaminhado: se a conversa ja foi encaminhada para um atendente.
    etapa_reserva: None (sem reserva), "coletando" ou "confirmando".
    ultimo_prato: id do ultimo prato usado numa resposta aceita.
    ultima_data: ultima data (ISO) usada numa resposta aceita.
    """

    falhas_seguidas: int = 0
    assunto_anterior: str | None = None
    esclarecimento: list[str] | None = None
    slots: dict = field(default_factory=dict)
    encaminhado: bool = False
    etapa_reserva: str | None = None
    ultimo_prato: str | None = None
    ultima_data: str | None = None

    def reiniciar(self) -> None:
        """Volta o estado ao inicio da conversa."""
        self.falhas_seguidas = 0
        self.assunto_anterior = None
        self.esclarecimento = None
        self.slots = {}
        self.encaminhado = False
        self.etapa_reserva = None
        self.ultimo_prato = None
        self.ultima_data = None

    def encerrar_reserva(self) -> None:
        """Descarta a reserva em andamento (slots e etapa)."""
        self.slots = {}
        self.etapa_reserva = None


@dataclass
class Resposta:
    """Resposta da Maresia a uma mensagem.

    tipo: "regra", "aceita", "esclarecimento", "abstencao", "fallback",
    "encaminhamento" ou "reserva" (passo do fluxo de reserva).
    herdou_contexto: a mensagem foi respondida herdando o assunto (e a
    entidade que faltava) do turno anterior.
    """

    texto: str
    intencao: str | None
    tipo: str
    confianca: float | None = None
    herdou_contexto: bool = False
    # Probabilidades do classificador ({intencao: prob}); vazio quando a
    # mensagem foi resolvida sem ele (regras, slots da reserva).
    probabilidades: dict[str, float] = field(default_factory=dict)


def carregar_base(caminho=CAMINHO_BASE) -> dict:
    """Le a base de conhecimento (JSON em UTF-8)."""
    with open(caminho, encoding="utf-8") as arquivo:
        return json.load(arquivo)


def _campos_texto(base: dict) -> dict:
    """Campos usados nos textos de ajuda e saudacao (restaurante e assuntos)."""
    assuntos = list(NOMES_INTENCOES.values())
    return {
        "restaurante": base["restaurante"]["nome"],
        "assunto_1": assuntos[0],
        "assunto_2": assuntos[1],
        "assunto_3": assuntos[2],
    }


def mensagem_boas_vindas(base: dict | None = None) -> str:
    """Texto de boas-vindas: a mesma saudacao da regra prioritaria."""
    base = base if base is not None else carregar_base()
    return MENSAGENS_REGRAS["saudacao"].format(**_campos_texto(base))


def _agora_real() -> datetime:
    """Data e hora atuais no FUSO_HORARIO do config."""
    return datetime.now(ZoneInfo(FUSO_HORARIO))


def _minutos(hhmm: str) -> int:
    """'20:30' -> 1230 (minutos desde a meia-noite)."""
    hora, minuto = hhmm.split(":")
    return int(hora) * 60 + int(minuto)


def _hhmm(minutos: int) -> str:
    """1230 -> '20:30'."""
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def _data_por_extenso(dia: date) -> str:
    """date(2026, 11, 21) -> 'sábado, 21 de novembro de 2026'."""
    return (
        f"{_NOMES_DIAS[dia.weekday()]}, {dia.day} de "
        f"{_NOMES_MESES[dia.month - 1]} de {dia.year}"
    )


def _no_dia(dia: date) -> str:
    """Artigo + dia da semana: 'na segunda-feira', 'no sábado'."""
    artigo = "no" if dia.weekday() >= 5 else "na"
    return f"{artigo} {_NOMES_DIAS[dia.weekday()]}"


def _plural(n: int, singular: str, plural: str) -> str:
    """1 -> '1 pessoa'; 4 -> '4 pessoas'."""
    return f"{n} {singular if n == 1 else plural}"


def _juntar(itens: list[str]) -> str:
    """['a', 'b', 'c'] -> 'a, b e c'."""
    if len(itens) <= 1:
        return "".join(itens)
    return ", ".join(itens[:-1]) + " e " + itens[-1]


def _unicos(itens: list) -> list:
    """Remove repetidos mantendo a ordem."""
    return list(dict.fromkeys(itens))


class GerenciadorDialogo:
    """Decide a resposta de cada mensagem e atualiza o EstadoConversa."""

    def __init__(
        self,
        modelo,
        base: dict | None = None,
        aleatorio: random.Random | None = None,
        agora: Callable[[], datetime] | None = None,
    ):
        """modelo: pipeline treinado; base: base de conhecimento (carregada
        de CAMINHO_BASE se omitida); aleatorio: gerador para sortear entre
        as variacoes de cada mensagem; agora: funcao que devolve o datetime
        atual no FUSO_HORARIO (padrao: relogio real). Os dois ultimos
        permitem resultados fixos nos testes.
        """
        self.modelo = modelo
        self.base = base if base is not None else carregar_base()
        self.aleatorio = aleatorio or random.Random()
        self.agora = agora or _agora_real
        self.respostas_fixas = {
            item["intencao"]: item["respostas_fixas"] for item in self.base["intencoes"]
        }
        self.regras_reserva = self.base["reserva"]
        self.funcionamento = self.base["funcionamento"]["dias"]
        self.pratos = {prato["id"]: prato for prato in self.base["cardapio"]}
        self.alergenicos = self.base["alergenicos"]["itens"]
        self._campos_texto = _campos_texto(self.base)

    # --- Entrada principal ----------------------------------------------------

    def responder(self, mensagem: str, estado: EstadoConversa) -> Resposta:
        """Responde a mensagem: regras, depois reserva em andamento, depois o modelo."""
        texto = preprocessar(mensagem)
        resposta = self._aplicar_regras(texto, estado)
        if resposta is not None:
            return resposta
        if estado.etapa_reserva is not None:
            return self._continuar_reserva(mensagem, texto, estado)
        decisao = self._ajustar_decisao(classificar(self.modelo, mensagem), mensagem)
        resposta = self._herdar_contexto(mensagem, texto, decisao, estado)
        if resposta is None:
            resposta = self._tratar_decisao(decisao, estado, mensagem)
        resposta.probabilidades = decisao.probabilidades
        return resposta

    # --- Heranca de contexto --------------------------------------------------

    def _herdar_contexto(
        self, mensagem: str, texto: str, decisao: Decisao, estado: EstadoConversa
    ) -> Resposta | None:
        """Responde uma continuacao curta ("e no domingo?", "ele tem gluten?")
        com o assunto do turno anterior, completando a entidade que falta
        com a memoria do estado. Devolve None quando nao ha heranca.

        Herda quando TODAS valem:
        a) existe assunto_anterior;
        b) a mensagem e curta e traz uma entidade util para esse assunto,
           mas nao o objeto principal (a data, no horario; o prato, com um
           pronome apontando para ultimo_prato, no cardapio);
        c) o classificador nao aceitou outra intencao (ex.: "quero
           reservar uma mesa" depois de uma pergunta de horario nao herda).
        """
        assunto = estado.assunto_anterior
        if assunto is None:
            return None
        if len(texto.split()) > MAX_PALAVRAS_HERANCA:
            return None
        if decisao.tipo == "aceita" and decisao.intencao != assunto:
            return None

        entidades = extrair_entidades(mensagem, self.agora())
        if assunto == "horario_localizacao":
            # So a data muda; o "que horas abrem" vem do turno anterior.
            if not entidades["data"]:
                return None
        elif assunto == "cardapio_alergenicos":
            # Alergenico/restricao + pronome, sem prato: o prato e o ultimo.
            tem_criterio = entidades["alergenicos"] or entidades["restricoes"]
            sem_prato = not entidades["pratos"] and not entidades["pratos_ambiguos"]
            if not (tem_criterio and sem_prato and _RE_PRONOME.search(texto) and estado.ultimo_prato):
                return None
            entidades["pratos"] = [estado.ultimo_prato]
        else:
            return None

        estado.falhas_seguidas = 0
        estado.esclarecimento = None
        texto_resposta = self._responder_intencao(assunto, estado, mensagem, entidades=entidades)
        return Resposta(texto_resposta, assunto, "aceita", decisao.confianca, herdou_contexto=True)

    # --- Regras prioritarias --------------------------------------------------

    def _aplicar_regras(self, texto: str, estado: EstadoConversa) -> Resposta | None:
        """Testa as regras na ordem: atendente, cancelar, ajuda, saudacao/despedida.

        Qualquer regra que case zera falhas_seguidas: a mensagem foi entendida.
        Com uma reserva em andamento, cancelar encerra o fluxo e as demais
        regras (ajuda, saudacao, despedida) lembram o passo pendente.
        """
        em_reserva = estado.etapa_reserva is not None

        if _RE_ATENDENTE.search(texto):
            estado.falhas_seguidas = 0
            estado.encaminhado = True
            return Resposta(self._encaminhamento(_ENCAMINHAR_POR_PEDIDO), None, "encaminhamento")

        if _RE_CANCELAR.match(texto) or (em_reserva and _RE_CANCELAR_NO_FLUXO.search(texto)):
            estado.falhas_seguidas = 0
            estado.encerrar_reserva()
            estado.esclarecimento = None
            return Resposta(MENSAGENS_REGRAS["cancelar"], None, "regra")

        for nome, regex in (
            ("ajuda", _RE_AJUDA),
            ("saudacao", _RE_SAUDACAO),
            ("despedida", _RE_DESPEDIDA),
        ):
            if regex.match(texto):
                estado.falhas_seguidas = 0
                texto_resposta = MENSAGENS_REGRAS[nome].format(**self._campos_texto)
                if em_reserva:
                    texto_resposta += "\n\n" + self._lembrete(estado)
                return Resposta(texto_resposta, None, "regra")
        return None

    # --- Classificador --------------------------------------------------------

    def _ajustar_decisao(self, decisao: Decisao, mensagem: str) -> Decisao:
        """Troca abstencao por fallback quando nenhuma palavra e conhecida.

        Texto sem nenhuma palavra do vocabulario de treino ("asdfgh") costuma
        cair em fora_escopo por exclusao, mas o modelo nao entendeu nada: e
        uma falha, nao uma recusa de assunto. Abstencoes com palavras
        conhecidas ("qual a previsao do tempo") continuam abstencoes.
        """
        if decisao.tipo == "abstencao" and not self._tem_palavra_conhecida(mensagem):
            return Decisao("fallback", decisao.intencao, decisao.confianca, [], decisao.probabilidades)
        return decisao

    def _tem_palavra_conhecida(self, mensagem: str) -> bool:
        """Diz se alguma palavra da mensagem esta no vocabulario de palavras do modelo."""
        try:
            vetorizadores = dict(self.modelo.named_steps["vetorizadores"].transformer_list)
            vocabulario = vetorizadores["palavras"].vocabulary_
        except (AttributeError, KeyError):
            return True  # modelo sem o vetorizador esperado: nao ajusta nada
        return any(palavra in vocabulario for palavra in preprocessar(mensagem).split())

    def _tratar_decisao(self, decisao: Decisao, estado: EstadoConversa, mensagem: str) -> Resposta:
        """Transforma a Decisao do modelo em Resposta e atualiza o estado."""
        pendente = estado.esclarecimento

        if decisao.tipo == "aceita":
            # Aceita: entendeu. Se havia esclarecimento pendente, esta
            # resposta o resolve (seja uma das candidatas ou outro assunto).
            estado.falhas_seguidas = 0
            estado.esclarecimento = None
            estado.assunto_anterior = decisao.intencao
            texto = self._responder_intencao(decisao.intencao, estado, mensagem, resolveu=pendente)
            return Resposta(texto, decisao.intencao, "aceita", decisao.confianca)

        if decisao.tipo == "esclarecimento":
            # Duvida entre duas intencoes de dominio: pergunta em vez de chutar.
            # Nao conta como falha nem zera o contador.
            estado.esclarecimento = list(decisao.candidatas)
            opcao_1, opcao_2 = (NOMES_INTENCOES.get(i, i) for i in decisao.candidatas)
            texto = self._sortear(self.base["esclarecimento"]).format(
                opcao_1=opcao_1, opcao_2=opcao_2
            )
            return Resposta(texto, None, "esclarecimento", decisao.confianca)

        # Abstencao e fallback encerram qualquer esclarecimento pendente.
        estado.esclarecimento = None

        if decisao.tipo == "abstencao":
            # O bot entendeu que o assunto e outro: nao e falha.
            estado.falhas_seguidas = 0
            texto = self._sortear(self.respostas_fixas[INTENCAO_FORA_ESCOPO])
            return Resposta(texto, INTENCAO_FORA_ESCOPO, "abstencao", decisao.confianca)

        # Fallback: nao entendeu. Na MAX_FALHAS_SEGUIDAS-esima falha seguida,
        # oferece um atendente humano e recomeca a contagem.
        resposta = self._registrar_falha(estado, decisao.confianca)
        if resposta is not None:
            return resposta
        return Resposta(self._sortear(self.base["fallback"]), None, "fallback", decisao.confianca)

    def _registrar_falha(self, estado: EstadoConversa, confianca: float | None) -> Resposta | None:
        """Conta uma falha; devolve o encaminhamento se chegou ao limite."""
        estado.falhas_seguidas += 1
        if estado.falhas_seguidas >= MAX_FALHAS_SEGUIDAS:
            estado.falhas_seguidas = 0
            estado.encaminhado = True
            return Resposta(
                self._encaminhamento(_ENCAMINHAR_POR_FALHAS), None, "encaminhamento", confianca
            )
        return None

    # --- Respostas ------------------------------------------------------------

    def _responder_intencao(
        self,
        intencao: str,
        estado: EstadoConversa,
        mensagem: str = "",
        resolveu: list[str] | None = None,
        entidades: dict | None = None,
    ) -> str:
        """Monta a resposta de uma intencao aceita.

        Ponto de extensao para respostas detalhadas por intencao. Hoje:
        - reserva: abre o fluxo de reserva (ou responde a politica, se a
          mensagem fala de cancelar/alterar/atrasar uma reserva existente);
        - horario_localizacao: com data, o horario daquele dia;
        - cardapio_alergenicos: com prato, alergenico ou restricao, consulta
          o cardapio da base;
        - sem entidades uteis: respostas_fixas da base.
        `resolveu` traz as candidatas do esclarecimento que esta resposta
        encerrou, se houver. `entidades` permite passar entidades ja
        completadas pela heranca de contexto (senao, sao extraidas da mensagem).
        """
        if intencao == "reserva":
            return self._iniciar_reserva(mensagem, estado)
        if entidades is None:
            entidades = extrair_entidades(mensagem, self.agora()) if mensagem else None

        if entidades and intencao == "horario_localizacao" and entidades["data"]:
            estado.ultima_data = entidades["data"]
            return self._horario_do_dia(date.fromisoformat(entidades["data"]))

        if entidades and intencao == "cardapio_alergenicos":
            texto = self._consultar_cardapio(mensagem, entidades, estado)
            if texto is not None:
                return texto
        return self._sortear(self.respostas_fixas[intencao])

    # --- Consultas a base (horario e cardapio) --------------------------------
    # Ficam aqui enquanto nao existe chatbot/conhecimento.py.

    def _horario_do_dia(self, dia: date) -> str:
        """Horario de funcionamento de um dia (ou que esta fechado)."""
        info = self.funcionamento[_CHAVES_DIAS[dia.weekday()]]
        no_dia = _no_dia(dia)
        campos = {"No_dia": no_dia[0].upper() + no_dia[1:], "data": dia.strftime("%d/%m")}
        if not info["aberto"]:
            return MENSAGENS_CONSULTA["dia_fechado"].format(**campos)
        turnos = " e ".join(
            MENSAGENS_CONSULTA["turno"].format(
                turno=_NOMES_TURNOS[turno], abre=info[turno]["abre"], fecha=info[turno]["fecha"]
            )
            for turno in _TURNOS if info.get(turno)
        )
        return MENSAGENS_CONSULTA["dia_aberto"].format(turnos=turnos, **campos)

    def _consultar_cardapio(self, mensagem: str, entidades: dict, estado: EstadoConversa) -> str | None:
        """Responde sobre o cardapio a partir das entidades; None se nao ha nenhuma util.

        - prato + restricao: o prato atende a restricao?
        - prato + alergenico: o prato contem o alergenico?
        - so prato: descricao, preco e alergenicos do prato;
        - so restricao: pratos compativeis;
        - so alergenico: pratos sem ele (se o cliente quer evitar) ou com ele.
        """
        pratos = [p for p in entidades["pratos"] if p in self.pratos]
        alergenicos = [a for a in entidades["alergenicos"] if a in self.alergenicos]
        restricoes = [r for r in entidades["restricoes"] if r in _NOMES_RESTRICOES]
        if restricoes:
            # "tem prato vegano?" casa com o sinonimo "prato vegano" de um prato
            # da base, mas e um pedido de lista: descarta o prato quando ele so
            # foi reconhecido por um sinonimo que contem a propria restricao.
            texto = preprocessar(mensagem)
            pratos = [p for p in pratos if not self._citado_so_pela_restricao(p, restricoes, texto)]

        if pratos:
            # O pronome so aponta para um prato quando a resposta fala de um so.
            estado.ultimo_prato = pratos[0] if len(pratos) == 1 else None
            partes = []
            for id_prato in pratos:
                # Restricao antes de alergenico: em "o pudim e sem lactose?" o
                # cliente pergunta pela restricao ("Nao, nao e sem lactose"),
                # nao se o prato contem leite.
                if restricoes:
                    partes += [self._prato_atende(id_prato, r) for r in restricoes]
                elif alergenicos:
                    partes += [self._prato_contem(id_prato, a) for a in alergenicos]
                else:
                    partes.append(self._descrever_prato(id_prato))
            return self._com_aviso(" ".join(partes), alergenicos)

        if entidades["pratos_ambiguos"]:
            nomes = []
            for candidatos in entidades["pratos_ambiguos"].values():
                nomes += [self.pratos[c]["nome"] for c in candidatos if c in self.pratos]
            return MENSAGENS_CONSULTA["prato_ambiguo"].format(opcoes=_juntar(_unicos(nomes)))

        if restricoes:
            partes = [self._listar_restricao(r) for r in restricoes]
            return self._com_aviso(" ".join(partes), [])

        if alergenicos:
            evitar = bool(_RE_EVITAR.search(preprocessar(mensagem)))
            partes = [self._listar_por_alergenico(a, evitar) for a in alergenicos]
            return self._com_aviso(" ".join(partes), alergenicos)
        return None

    def _citado_so_pela_restricao(self, id_prato: str, restricoes: list[str], texto: str) -> bool:
        """Diz se o prato so aparece na mensagem por um sinonimo que contem a restricao.

        "tem prato vegano" cita o prato pelo sinonimo "prato vegano" (pedido
        de lista); "a moqueca de banana e vegana" cita por "moqueca de banana".
        """
        prato = self.pratos[id_prato]
        raizes = [preprocessar(_NOMES_RESTRICOES[r])[:-1] for r in restricoes]  # "vegan", "sem glute"
        citados = [
            termo for termo in map(preprocessar, prato.get("sinonimos", []) + [prato["nome"]])
            if termo and re.search(rf"\b{re.escape(termo)}\b", texto)
        ]
        return bool(citados) and all(any(r in termo for r in raizes) for termo in citados)

    def _nome_alergenico(self, id_alergenico: str) -> str:
        """'trigo_gluten' -> 'trigo / glúten'."""
        return self.alergenicos[id_alergenico]["nome"].lower()

    def _prato_contem(self, id_prato: str, id_alergenico: str) -> str:
        """Diz se o prato contem, pode conter ou nao contem o alergenico."""
        prato = self.pratos[id_prato]
        campos = {"prato": prato["nome"], "Prato": prato["nome"],
                  "alergenico": self._nome_alergenico(id_alergenico)}
        if id_alergenico in prato["alergenicos"]:
            return MENSAGENS_CONSULTA["contem"].format(**campos)
        if id_alergenico in prato.get("pode_conter", []):
            return MENSAGENS_CONSULTA["pode_conter"].format(**campos)
        return MENSAGENS_CONSULTA["nao_contem"].format(**campos)

    def _prato_atende(self, id_prato: str, restricao: str) -> str:
        """Diz se o prato atende a restricao (campo booleano do prato na base)."""
        prato = self.pratos[id_prato]
        chave = "restricao_sim" if prato.get(restricao) else "restricao_nao"
        return MENSAGENS_CONSULTA[chave].format(
            prato=prato["nome"], restricao=_NOMES_RESTRICOES[restricao]
        )

    def _descrever_prato(self, id_prato: str) -> str:
        """Descricao, porcao, preco e alergenicos de um prato."""
        prato = self.pratos[id_prato]
        partes = [MENSAGENS_CONSULTA["prato"].format(
            nome=prato["nome"],
            descricao=prato["descricao"],
            serve=_plural(prato["serve_pessoas"], "pessoa", "pessoas"),
            preco=f"R$ {prato['preco']:.2f}".replace(".", ","),
        )]
        if prato["alergenicos"]:
            lista = _juntar([self._nome_alergenico(a) for a in prato["alergenicos"]])
            partes.append(MENSAGENS_CONSULTA["prato_alergenicos"].format(lista=lista))
        else:
            partes.append(MENSAGENS_CONSULTA["prato_sem_alergenicos"])
        if prato.get("pode_conter"):
            lista = _juntar([self._nome_alergenico(a) for a in prato["pode_conter"]])
            partes.append(MENSAGENS_CONSULTA["prato_pode_conter"].format(lista=lista))
        return " ".join(partes)

    def _listar_restricao(self, restricao: str) -> str:
        """Pratos que atendem a restricao (vegano, sem gluten...)."""
        nome = _NOMES_RESTRICOES[restricao]
        pratos = [p["nome"] for p in self.pratos.values() if p.get(restricao)]
        if not pratos:
            return MENSAGENS_CONSULTA["lista_vazia"].format(criterio=nome)
        return MENSAGENS_CONSULTA["lista_restricao"].format(
            restricao=nome + ("s" if nome.endswith("a") else ""), pratos=_juntar(pratos)
        )

    def _listar_por_alergenico(self, id_alergenico: str, evitar: bool) -> str:
        """Pratos sem o alergenico (evitar=True) ou que o levam (evitar=False).

        Para quem quer evitar, "pode conter" tambem fica de fora, por seguranca.
        """
        nome = self._nome_alergenico(id_alergenico)
        if evitar:
            pratos = [
                p["nome"] for p in self.pratos.values()
                if id_alergenico not in p["alergenicos"]
                and id_alergenico not in p.get("pode_conter", [])
            ]
            chave, criterio = "lista_sem_alergenico", f"sem {nome}"
        else:
            pratos = [p["nome"] for p in self.pratos.values() if id_alergenico in p["alergenicos"]]
            chave, criterio = "lista_com_alergenico", f"com {nome}"
        if not pratos:
            return MENSAGENS_CONSULTA["lista_vazia"].format(criterio=criterio)
        return MENSAGENS_CONSULTA[chave].format(alergenico=nome, pratos=_juntar(pratos))

    def _com_aviso(self, texto: str, alergenicos: list[str]) -> str:
        """Acrescenta as observacoes dos alergenicos citados e o aviso padrao da base."""
        observacoes = [
            self.alergenicos[a]["observacao"] for a in alergenicos
            if self.alergenicos[a].get("observacao")
        ]
        return " ".join([texto, *observacoes, self.base["alergenicos"]["aviso_padrao"]])

    def _encaminhamento(self, indice: int) -> str:
        """Mensagem de encaminhamento humano da base."""
        mensagens = self.base["encaminhamento_humano"]
        return mensagens[min(indice, len(mensagens) - 1)]

    def _sortear(self, opcoes: list[str]) -> str:
        """Escolhe uma das variacoes de uma mensagem."""
        return self.aleatorio.choice(opcoes)

    # --- Reserva: fluxo -------------------------------------------------------

    def _iniciar_reserva(self, mensagem: str, estado: EstadoConversa) -> str:
        """Abre o fluxo de reserva, ja aproveitando os slots da mensagem.

        Se a mensagem e sobre uma reserva existente (cancelar, alterar,
        atraso), responde a politica da base em vez de abrir uma reserva nova.
        """
        texto = preprocessar(mensagem)
        for chave, regex in _RE_POLITICAS:
            if regex.search(texto):
                return self.regras_reserva[chave]

        estado.etapa_reserva = "coletando"
        estado.slots = {}
        novos = self._extrair_slots(mensagem, estado)
        if novos:
            return self._preencher_slots(novos, estado)
        return MENSAGENS_RESERVA["inicio"] + " " + self._pergunta(estado)

    def _continuar_reserva(self, mensagem: str, texto: str, estado: EstadoConversa) -> Resposta:
        """Trata uma mensagem com a reserva em andamento (regras ja testadas).

        Ordem: "sim" na confirmacao; slots novos ou corrigidos (sem passar
        pelo classificador); "nao"/qual slot alterar; e, por fim, o
        classificador, para perguntas de outro assunto no meio da reserva.
        """
        if estado.etapa_reserva == "confirmando" and _RE_SIM.match(texto):
            estado.falhas_seguidas = 0
            return Resposta(self._registrar_reserva(estado), "reserva", "reserva")

        decisao = None
        novos = self._extrair_slots(mensagem, estado)
        if not novos and self._slot_pendente(estado) == "nome" and self._parece_nome(mensagem, texto):
            # Resposta curta como "Murilo": so vira nome se o classificador
            # nao reconhecer nela uma pergunta de outro assunto.
            decisao = self._ajustar_decisao(classificar(self.modelo, mensagem), mensagem)
            if not (decisao.tipo == "aceita" and decisao.intencao != "reserva"):
                novos = {"nome": self._formatar_nome(mensagem)}
        if novos:
            estado.falhas_seguidas = 0
            return Resposta(self._preencher_slots(novos, estado), "reserva", "reserva")

        alterar = self._slot_a_alterar(texto, estado)
        if alterar is not None:
            estado.falhas_seguidas = 0
            return Resposta(alterar, "reserva", "reserva")

        if decisao is None:
            decisao = self._ajustar_decisao(classificar(self.modelo, mensagem), mensagem)
        resposta = self._decisao_no_meio_da_reserva(decisao, estado, mensagem)
        resposta.probabilidades = decisao.probabilidades
        return resposta

    def _decisao_no_meio_da_reserva(
        self, decisao: Decisao, estado: EstadoConversa, mensagem: str
    ) -> Resposta:
        """Responde o classificador sem perder os slots e lembra o passo pendente."""
        lembrete = self._lembrete(estado)

        if decisao.tipo == "aceita":
            estado.falhas_seguidas = 0
            if decisao.intencao == "reserva":
                # Continua falando da reserva: so repete o passo pendente.
                return Resposta(self._pergunta(estado), "reserva", "reserva", decisao.confianca)
            estado.assunto_anterior = decisao.intencao
            texto = self._responder_intencao(decisao.intencao, estado, mensagem)
            return Resposta(texto + "\n\n" + lembrete, decisao.intencao, "aceita", decisao.confianca)

        if decisao.tipo == "abstencao":
            estado.falhas_seguidas = 0
            texto = self._sortear(self.respostas_fixas[INTENCAO_FORA_ESCOPO])
            return Resposta(
                texto + "\n\n" + lembrete, INTENCAO_FORA_ESCOPO, "abstencao", decisao.confianca
            )

        if decisao.tipo == "esclarecimento":
            # No meio da reserva nao abrimos outra pergunta: so repetimos o
            # passo pendente. Nao conta como falha.
            texto = MENSAGENS_RESERVA["nao_tenho_certeza"] + " " + self._pergunta(estado)
            return Resposta(texto, None, "esclarecimento", decisao.confianca)

        # Fallback: conta como falha e repete a pergunta do slot pendente.
        resposta = self._registrar_falha(estado, decisao.confianca)
        if resposta is not None:
            return resposta
        texto = MENSAGENS_RESERVA["nao_entendi"] + " " + self._pergunta(estado)
        return Resposta(texto, None, "fallback", decisao.confianca)

    def _slot_a_alterar(self, texto: str, estado: EstadoConversa) -> str | None:
        """Trata "nao" no resumo e pedidos como "quero mudar o horario".

        Devolve o texto da resposta ou None se a mensagem nao e isso.
        """
        confirmando = estado.etapa_reserva == "confirmando"
        todos_preenchidos = all(slot in estado.slots for slot in SLOTS_RESERVA)
        negou = confirmando and _RE_NAO.match(texto)
        # Depois do "nao", a etapa volta para "coletando" com todos os slots
        # preenchidos: a resposta a "o que quer alterar?" pode ser so "o horario".
        # No resumo, sem "nao", exige um verbo de mudanca, para "qual o horario
        # de domingo?" nao apagar o horario da reserva.
        respondendo_alteracao = not confirmando and todos_preenchidos
        pediu_mudanca = confirmando and _RE_VERBO_ALTERAR.search(texto)
        if not (negou or respondendo_alteracao or pediu_mudanca):
            return None
        for slot, regex in _RE_SLOT_ALTERAR.items():
            if regex.search(texto):
                estado.slots.pop(slot, None)
                estado.etapa_reserva = "coletando"
                return self._pergunta(estado)
        if negou:
            estado.etapa_reserva = "coletando"
            return MENSAGENS_RESERVA["o_que_alterar"]
        return None

    def _preencher_slots(self, novos: dict, estado: EstadoConversa) -> str:
        """Grava os slots novos, valida e pergunta o proximo (ou mostra o resumo)."""
        estado.slots.update(novos)
        erro = self._validar(estado)
        if erro is not None:
            # O slot invalido foi apagado: volta a coletar (mesmo se estava
            # no resumo, corrigindo um dado).
            estado.etapa_reserva = "coletando"
            return erro + " " + self._pergunta(estado)
        if self._slot_pendente(estado) is None:
            estado.etapa_reserva = "confirmando"
            return self._resumo(estado)
        estado.etapa_reserva = "coletando"
        return self._pergunta(estado)

    def _registrar_reserva(self, estado: EstadoConversa) -> str:
        """Confirma a reserva (simulada: nada e gravado) e encerra o fluxo."""
        campos = self._campos_reserva(estado)
        texto = MENSAGENS_RESERVA["registrada"].format(
            politica_atraso=self.regras_reserva["politica_atraso"], **campos
        )
        estado.encerrar_reserva()
        return texto

    # --- Reserva: extracao ----------------------------------------------------

    def _extrair_slots(self, mensagem: str, estado: EstadoConversa) -> dict:
        """Extrai da mensagem os slots da reserva com extrair_entidades.

        Respostas curtas so com um numero ("4", "quatro", "20") sao lidas
        de acordo com o slot que esta sendo pedido.
        """
        agora = self.agora()
        entidades = extrair_entidades(mensagem, agora)
        pendente = self._slot_pendente(estado)

        if not any(entidades[k] for k in ("pessoas", "data", "horario", "horario_ambiguo", "nome")):
            if _RE_SO_NUMERO.match(preprocessar(mensagem)) and pendente in ("pessoas", "horario"):
                # Da a extrair_entidades o contexto da pergunta feita e so
                # aproveita o slot perguntado ("mesa para Carlos" nao vira nome).
                contexto = "mesa para" if pendente == "pessoas" else "as"
                com_contexto = extrair_entidades(f"{contexto} {mensagem}", agora)
                for chave in ("pessoas",) if pendente == "pessoas" else ("horario", "horario_ambiguo"):
                    entidades[chave] = com_contexto[chave]

        novos = {}
        for slot in ("pessoas", "data", "nome"):
            if entidades[slot]:
                novos[slot] = entidades[slot]
        if entidades["horario"]:
            novos["horario"] = entidades["horario"]
        elif entidades["horario_ambiguo"]:
            data = novos.get("data") or estado.slots.get("data")
            novos["horario"] = self._resolver_horario_ambiguo(entidades["horario_ambiguo"], data)
        return novos

    def _resolver_horario_ambiguo(self, ambiguo: str, data_iso: str | None) -> str:
        """'08:00|20:00' -> a opcao que cai num horario de reserva.

        Com a data conhecida, usa o funcionamento daquele dia; sem ela, o de
        qualquer dia aberto. Se nenhuma servir, fica com a da tarde/noite.
        """
        opcoes = ambiguo.split("|")
        if data_iso:
            dias = [_CHAVES_DIAS[date.fromisoformat(data_iso).weekday()]]
        else:
            dias = list(_CHAVES_DIAS)
        for opcao in opcoes:
            if any(self._horario_permitido(dia, opcao) for dia in dias):
                return opcao
        return opcoes[-1]

    def _parece_nome(self, mensagem: str, texto: str) -> bool:
        """Mensagem curta, so com letras, que pode ser um nome ("Murilo")."""
        return bool(_RE_PARECE_NOME.match(mensagem.strip())) and not (
            _RE_SIM.match(texto) or _RE_NAO.match(texto)
        )

    @staticmethod
    def _formatar_nome(mensagem: str) -> str:
        """'ana paula' -> 'Ana Paula'."""
        return " ".join(p[:1].upper() + p[1:].lower() for p in mensagem.split())

    # --- Reserva: validacao ---------------------------------------------------

    def _validar(self, estado: EstadoConversa) -> str | None:
        """Valida os slots preenchidos; no 1o erro, apaga o slot e devolve o motivo.

        Ordem: pessoas, data (dia fechado, passado, janela), horario
        (funcionamento do dia) e antecedencia minima.
        """
        slots, regras = estado.slots, self.regras_reserva
        agora = self.agora()
        hoje = agora.date()

        pessoas = slots.get("pessoas")
        if pessoas is not None:
            if pessoas < regras["min_pessoas"]:
                slots.pop("pessoas")
                return MENSAGENS_RESERVA["pessoas_minimo"].format(
                    minimo=_plural(regras["min_pessoas"], "pessoa", "pessoas")
                )
            if pessoas > regras["max_pessoas"]:
                # Acima do limite do bot: nao reserva e oferece um atendente.
                slots.pop("pessoas")
                estado.encaminhado = True
                restaurante = self.base["restaurante"]
                return MENSAGENS_RESERVA["acima_limite"].format(
                    mensagem=regras["mensagem_acima_limite"],
                    whatsapp=restaurante["whatsapp"],
                    telefone=restaurante["telefone"],
                )

        data = date.fromisoformat(slots["data"]) if "data" in slots else None
        if data is not None:
            limite = hoje + timedelta(days=regras["antecedencia_maxima_dias"])
            erro = None
            if not self.funcionamento[_CHAVES_DIAS[data.weekday()]]["aberto"]:
                no_dia = _no_dia(data)
                erro = MENSAGENS_RESERVA["fechado"].format(No_dia=no_dia[0].upper() + no_dia[1:])
            elif data < hoje:
                erro = MENSAGENS_RESERVA["passado"]
            elif data > limite:
                erro = MENSAGENS_RESERVA["alem_janela"].format(
                    dias=regras["antecedencia_maxima_dias"], limite=_data_por_extenso(limite)
                )
            if erro is not None:
                slots.pop("data")
                return erro

        horario = slots.get("horario")
        if data is not None and horario is not None:
            if not self._horario_permitido(_CHAVES_DIAS[data.weekday()], horario):
                slots.pop("horario")
                return MENSAGENS_RESERVA["horario_fora"].format(janelas=self._janelas_texto(data))
            momento = datetime.combine(
                data, datetime.strptime(horario, "%H:%M").time(), tzinfo=agora.tzinfo
            )
            horas = regras["antecedencia_minima_horas"]
            if momento - agora < timedelta(hours=horas):
                slots.pop("horario")
                return MENSAGENS_RESERVA["antecedencia"].format(
                    horas=_plural(horas, "hora", "horas")
                )
        return None

    def _janelas_reserva(self, chave_dia: str) -> list[tuple[int, int]]:
        """Faixas de horario de reserva do dia, em minutos: [(abre, ultima), ...].

        Regra da base (reserva.janela): do horario de abertura de cada turno
        ate ultima_reserva_minutos_antes_fechar antes do fechamento.
        """
        dia = self.funcionamento[chave_dia]
        if not dia["aberto"]:
            return []
        antes = self.regras_reserva["janela"]["ultima_reserva_minutos_antes_fechar"]
        janelas = []
        for turno in _TURNOS:
            if dia.get(turno):
                janelas.append((_minutos(dia[turno]["abre"]), _minutos(dia[turno]["fecha"]) - antes))
        return janelas

    def _horario_permitido(self, chave_dia: str, horario: str) -> bool:
        """Diz se o horario cai numa faixa de reserva daquele dia."""
        minutos = _minutos(horario)
        return any(inicio <= minutos <= fim for inicio, fim in self._janelas_reserva(chave_dia))

    def _janelas_texto(self, dia: date) -> str:
        """'No sábado aceitamos reservas das 11:30 às 14:30 e das 18:30 às 22:30.'"""
        faixas = " e ".join(
            f"das {_hhmm(inicio)} às {_hhmm(fim)}"
            for inicio, fim in self._janelas_reserva(_CHAVES_DIAS[dia.weekday()])
        )
        no_dia = _no_dia(dia)
        return f"{no_dia[0].upper() + no_dia[1:]} aceitamos reservas {faixas}."

    # --- Reserva: textos ------------------------------------------------------

    @staticmethod
    def _slot_pendente(estado: EstadoConversa) -> str | None:
        """Primeiro slot que falta, na ordem de SLOTS_RESERVA."""
        for slot in SLOTS_RESERVA:
            if slot not in estado.slots:
                return slot
        return None

    def _pergunta(self, estado: EstadoConversa) -> str:
        """Pergunta do passo atual: o slot que falta ou a confirmacao."""
        slot = self._slot_pendente(estado)
        if slot is None:
            if estado.etapa_reserva == "confirmando":
                return MENSAGENS_RESERVA["confirmar_de_novo"]
            return MENSAGENS_RESERVA["o_que_alterar"]
        if slot == "horario":
            janelas = ""
            if "data" in estado.slots:
                janelas = self._janelas_texto(date.fromisoformat(estado.slots["data"]))
            return MENSAGENS_RESERVA["pergunta_horario"].format(janelas=janelas).strip()
        return MENSAGENS_RESERVA[f"pergunta_{slot}"]

    def _lembrete(self, estado: EstadoConversa) -> str:
        """Lembra o cliente do passo pendente da reserva."""
        return MENSAGENS_RESERVA["lembrete"].format(pergunta=self._pergunta(estado))

    def _campos_reserva(self, estado: EstadoConversa) -> dict:
        """Slots formatados para o resumo e a confirmacao."""
        slots = estado.slots
        return {
            "pessoas": _plural(slots["pessoas"], "pessoa", "pessoas"),
            "data": _data_por_extenso(date.fromisoformat(slots["data"])),
            "horario": slots["horario"],
            "nome": slots["nome"],
        }

    def _resumo(self, estado: EstadoConversa) -> str:
        """Resumo da reserva pedindo confirmacao."""
        return MENSAGENS_RESERVA["resumo"].format(**self._campos_reserva(estado))
