"""Gerenciador de dialogo da Maresia.

Para cada mensagem, nesta ordem:
1. regras prioritarias (atendente, cancelar, ajuda, saudacao/despedida),
   avaliadas sobre o texto pre-processado, antes do classificador;
2. se ha uma reserva em andamento, a mensagem e lida como resposta ao passo
   atual (slots via extrair_entidades, confirmacao sim/nao);
3. pedidos multiplos (modelo.detectar_pedidos_multiplos): assuntos
   diferentes na mesma mensagem viram "por qual comecamos?";
4. classificador de intencoes + politica de decisao (modelo.classificar),
   com heranca de contexto do turno anterior;
5. tratamento da decisao: aceita, esclarecimento, abstencao ou fallback,
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
from chatbot.modelo import Decisao, classificar, detectar_pedidos_multiplos
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
    "contato": "Você pode falar com a gente pelo WhatsApp {whatsapp} ou pelo telefone {telefone}.",
    "pedidos_multiplos": "Você pediu mais de uma coisa: {assuntos}. Por qual começamos?",
}

# Textos do fluxo de reserva (a base so tem as regras e as politicas).
MENSAGENS_RESERVA = {
    "inicio": "Vamos reservar sua mesa! 🌊",
    "data_solta": (
        "Você quer fazer uma reserva para {data}{horario}, ou saber o nosso "
        "horário de funcionamento nesse dia?"
    ),
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
    "regra_antecedencia": (
        "A reserva precisa ser feita com pelo menos {minimo} de antecedência, e dá para "
        "reservar com até {maximo} de antecedência. {janela}"
    ),
    "regra_pessoas": (
        "Pelo chat eu faço reservas de {minimo} a {maximo} pessoas. Para grupos maiores, fale "
        "com a nossa equipe pelo WhatsApp {whatsapp} ou pelo telefone {telefone}."
    ),
    "acima_limite_alternativa": (
        "Se o grupo for de até {maximo} pessoas, eu reservo por aqui: é só me dizer, "
        "por exemplo, \"quero reservar para 8 pessoas\"."
    ),
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
    "prato_ambiguo": "Temos {opcoes}. Sobre qual você quer saber?",
    "cardapio_completo": (
        "Este é o nosso cardápio:\n\n{lista}\n\n"
        "Quer saber os ingredientes ou os alergênicos de algum prato? É só me dizer o nome."
    ),
    "titulo_categoria": "{categoria}:",
    "item_lista": "   • {nome} – {preco}",
    "lista_filtrada": "{titulo}:\n{lista}",
    "lista_filtrada_vazia": "No momento não temos {titulo}.",
    "grupo_considerado": "Considerei {grupo} como {itens}, e deixei de fora também os pratos que podem ter traços deles.",
    "grupo_peixe": "Se a alergia também for a peixe, me avise que eu refaço a lista.",
    "faixa_ate": "até {maximo}",
    "faixa_a_partir": "a partir de {minimo}",
    "faixa_entre": "entre {minimo} e {maximo}",
    "ordem_barato_m": "o mais barato",
    "ordem_barato_f": "a mais barata",
    "ordem_caro_m": "o mais caro",
    "ordem_caro_f": "a mais cara",
    "ordem_por_categoria": " de cada categoria",
    "preco_mais_barato": "O item mais barato do cardápio é {nome} – {preco}.",
    "porcao": "Pratos que servem {pessoas}:\n{lista}",
    "porcao_prato": "{prato} serve {serve}.",
    "porcao_vazia": "No momento não temos pratos que sirvam {pessoas}. Nossos pratos servem {opcoes}.",
    "nao_encontrado": (
        "Não encontrei {termo} no nosso cardápio. Se quiser, me peça \"cardápio\" "
        "que eu te mostro todos os pratos."
    ),
    "sem_bebidas": (
        "Ainda não tenho aqui as informações de bebidas. A nossa equipe te passa "
        "as opções pelo WhatsApp {whatsapp} ou pelo telefone {telefone}."
    ),
}

# Pergunta de porcao ("tem prato para 2 pessoas?"): fala de prato/porcao e
# nao de reserva/mesa. Sem esta regra, "2 pessoas" abria o fluxo de reserva.
_RE_PORCAO = re.compile(r"\b(?:pratos?|porcao|porcoes|serve|servem|individua\w*)\b")
_RE_INDIVIDUAL = re.compile(r"\bindividua\w*\b")
_RE_FALA_DE_RESERVA = re.compile(r"\b(?:reserv\w*|mesas?|lugar|lugares)\b")
# Bebidas: a base nao tem a carta de bebidas, entao a Maresia indica a equipe.
_RE_BEBIDAS = re.compile(
    r"\b(?:bebidas?|beber|vinhos?|cervejas?|chopp?|chope|caipirinhas?|drinks?|drinques?"
    r"|sucos?|refrigerantes?|refri|agua|cafe|cafezinho|coqueteis|coquetel|alcool\w*)\b"
)
# "tem pizza?", "voces servem rodizio?": o que o cliente procura, no texto
# original (com acento), para responder que nao esta no cardapio.
_RE_TERMO_PROCURADO = re.compile(
    r"^\s*(?:(?:voc[eê]s|vcs|vc)\s+)?(?:t[eê]m|servem|serve|vendem|vende|fazem|faz)\s+"
    r"(?:(?:algum|alguma|um|uma|o|a)\s+)?(?P<termo>[^?!.,;]+?)\s*[?!.]*\s*$",
    re.IGNORECASE,
)
_MAX_PALAVRAS_TERMO = 4

# Categorias do cardapio na ordem de exibicao: nome no plural e se o
# substantivo e feminino (para concordar "sobremesas veganas", "pratos veganos").
_CATEGORIAS_CARDAPIO = {
    "entrada": ("Entradas", True),
    "prato_principal": ("Pratos principais", False),
    "acompanhamento": ("Acompanhamentos", False),
    "salada": ("Saladas", True),
    "sobremesa": ("Sobremesas", True),
}
# Restricao -> adjetivo no plural (feminino, masculino).
_ADJETIVOS_RESTRICOES = {
    "vegetariano": ("vegetarianas", "vegetarianos"),
    "vegano": ("veganas", "veganos"),
    "sem_gluten": ("sem glúten", "sem glúten"),
    "sem_lactose": ("sem lactose", "sem lactose"),
}
# Alergenico que a restricao ja cobre: em "sem gluten" vale o campo
# sem_gluten do prato, como na lista de restricao.
_ALERGENICO_DA_RESTRICAO = {"sem_gluten": "trigo_gluten", "sem_lactose": "leite"}
# Pedido do cardapio sem criterio ("quero ver o cardapio", "o que voces servem").
# Oracoes de uma mensagem ja pre-processada (sem pontuacao), para achar o
# alergenico que o cliente LIBERA: "sou alergico a camarao mas como peixe".
_RE_SEPARA_ORACOES = re.compile(r"\b(?:mas|porem|so que|entretanto|contudo|e)\b")
_RE_PONTUACAO_ORACOES = re.compile(r"[,;.!?]")
# A liberacao vem no inicio da oracao ("como peixe") ou no fim ("peixe eu
# como", "leite tudo bem"). Perguntas ("o que posso comer", "quais pratos...")
# saem antes, para "camarao e peixe o que posso comer" nao liberar o peixe.
_RE_PERGUNTA_FINAL = re.compile(r"\b(?:o que|quais?|que pratos?|tem algum)\b.*$")
_RE_LIBERADO_INICIO = re.compile(
    r"^\s*(?:eu )?(?:como|posso comer|pode ter|pode levar"
    r"|nao tenho (?:alergia|problema) (?:a|ao|com|de))\b"
)
_RE_LIBERADO_FIM = re.compile(
    r"\b(?:eu )?(?:como|posso comer|pode|pode ter|tudo bem|sem problema|liberad[oa]s?)\s*$"
)
# Continuacao que fala do mesmo prato do turno anterior ("e camarao?").
_RE_CONTINUACAO = re.compile(r"^(?:e|tambem)\b")
_RE_VER_CARDAPIO = re.compile(
    r"\b(?:cardapio|menu|pratos|opcoes|o que (?:voces )?(?:tem|servem|serve|oferecem))\b"
)

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

# a2) Contato (telefone/WhatsApp da base): vale para qualquer intencao, porque
# "tem whatsapp?" nao tem cara de nenhuma das quatro.
_RE_CONTATO = re.compile(
    r"\b(?:telefones?|fone|celular|ligar|ligo|liga|ligacao|whats\w*|zap|zapzap|contatos?)\b"
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
    # Duvidas sobre as regras de uma reserva nova (montadas com os numeros
    # da base em _regra_reserva, nao abrem o fluxo).
    ("regra_antecedencia", re.compile(
        r"\b(?:antecedencia|com quanto tempo|quanto tempo antes|quantos dias antes"
        r"|ate quando (?:posso|da para|consigo) reservar)\b"
    )),
    ("regra_pessoas", re.compile(
        r"\b(?:quantas pessoas (?:no maximo|posso|da|pode|cabe\w*)|maximo de pessoas"
        r"|limite de pessoas|numero maximo)\b"
    )),
)


# --- Data solta ----------------------------------------------------------------
# Palavras que podem formar uma mensagem que e SO data/periodo ("sabado",
# "amanha a noite", "dia 25", "25/12", "sabado as 20h"), ja pre-processadas:
# numeros viram "num" e "25/12" vira "num num". Inclui conectivos curtos.
_PALAVRAS_DATA = frozenset(
    "hoje amanha depois dia num proximo proxima feira "
    "segunda terca quarta quinta sexta sabado domingo "
    "janeiro fevereiro marco abril maio junho julho agosto setembro outubro novembro dezembro "
    "manha tarde noite almoco jantar meio meia as h hs horas "
    "e no na o a de do da para".split()
)
_RE_QUE_VEM = re.compile(r"\bque vem\b")

# Resolucao do esclarecimento por palavra-chave, em respostas curtas.
_PALAVRAS_CHAVE_INTENCAO = (
    ("reserva", re.compile(r"\b(?:reserva|reservar|mesa)\b")),
    ("horario_localizacao", re.compile(r"\b(?:horario|abre|funcionamento)\b")),
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
# "sem lactose", "quais pratos nao tem camarao"). Sem ela, "tem camarao?"
# lista os pratos que levam camarao.
_NEGACOES_EVITAR = (
    r"nao (?:como|posso|pode|quero|tem|tenham?|levam?|leve|contem|contenham?"
    r"|possuem?|vem com|vao)"
)
_RE_EVITAR = re.compile(
    r"\b(?:sem|livres? de|alergi\w*|alergic\w*|intoleran\w*|" + _NEGACOES_EVITAR
    + r"|evit\w*|restric\w*)\b"
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
    ultima_data: ultima data (ISO) usada numa resposta aceita ou recebida
    solta ("Sabado").
    data_solta: {"data", "horario"} de uma data recebida sem assunto, enquanto
    o cliente nao escolhe entre reserva e horario (esclarecimento pendente).
    filtros_cardapio: filtros da ultima lista do cardapio (categorias,
    restricoes, alergenicos, grupos, evitar), para a continuacao herdar
    ("sou alergico a frutos do mar" -> "e entrada?"). None quando a ultima
    resposta do cardapio foi sobre um prato.
    """

    falhas_seguidas: int = 0
    assunto_anterior: str | None = None
    esclarecimento: list[str] | None = None
    slots: dict = field(default_factory=dict)
    encaminhado: bool = False
    etapa_reserva: str | None = None
    ultimo_prato: str | None = None
    ultima_data: str | None = None
    data_solta: dict | None = None
    filtros_cardapio: dict | None = None

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
        self.filtros_cardapio = None
        self.data_solta = None

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


def _filtros_vazios() -> dict:
    """Filtros do cardapio sem nenhum criterio (cardapio completo)."""
    return {
        "categorias": [], "restricoes": [], "alergenicos": [], "grupos": [], "evitar": False,
        "preco_min": None, "preco_max": None, "ordem": None,
    }


def _mesclar_filtros(anterior: dict, novo: dict) -> dict:
    """Soma os filtros de uma continuacao aos da lista anterior.

    - categoria nova substitui a anterior ("e de sobremesa?");
    - restricoes se acumulam ("e sem lactose tambem?");
    - alergenicos no mesmo sentido (evitar/procurar) se acumulam; em sentido
      diferente, os novos substituem ("tem camarao?" depois de "sem gluten");
    - sem alergenico novo, os anteriores continuam valendo (a alergia nao
      se perde em "e entrada?");
    - faixa de preco nova substitui a anterior; sem faixa nova, a anterior
      continua ("ate 50 reais" -> "e sem gluten?");
    - "mais barato"/"mais caro" vale so para a mensagem em que aparece.
    """
    tem_faixa_nova = novo.get("preco_min") is not None or novo.get("preco_max") is not None
    faixa = novo if tem_faixa_nova else anterior
    if novo["alergenicos"]:
        if anterior["alergenicos"] and anterior["evitar"] == novo["evitar"]:
            alergenicos = _unicos(anterior["alergenicos"] + novo["alergenicos"])
            grupos = _unicos(anterior["grupos"] + novo["grupos"])
        else:
            alergenicos, grupos = novo["alergenicos"], novo["grupos"]
        evitar = novo["evitar"]
    else:
        alergenicos, grupos, evitar = anterior["alergenicos"], anterior["grupos"], anterior["evitar"]
    return {
        "categorias": novo["categorias"] or anterior["categorias"],
        "restricoes": _unicos(anterior["restricoes"] + novo["restricoes"]),
        "alergenicos": alergenicos,
        "grupos": grupos,
        "evitar": evitar,
        "preco_min": faixa.get("preco_min"),
        "preco_max": faixa.get("preco_max"),
        "ordem": novo.get("ordem"),
    }


def _extremo_por_categoria(pratos: list[dict], ordem: str) -> list[dict]:
    """O prato mais barato (ordem "barato") ou mais caro ("caro") de cada categoria."""
    escolha = min if ordem == "barato" else max
    extremos = []
    for categoria in _CATEGORIAS_CARDAPIO:
        da_categoria = [p for p in pratos if p["categoria"] == categoria]
        if da_categoria:
            extremos.append(escolha(da_categoria, key=lambda p: p["preco"]))
    return extremos


def _preco(valor: float) -> str:
    """59.9 -> 'R$ 59,90'."""
    return f"R$ {valor:.2f}".replace(".", ",")


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
            # No meio da reserva, "4 pessoas e sabado" e preenchimento de
            # slots, nao pedido multiplo nem data solta: por isso vem antes.
            return self._continuar_reserva(mensagem, texto, estado)

        # Esclarecimento pendente respondido com uma palavra-chave ("reserva").
        escolhida = self._intencao_por_palavra_chave(texto, estado)
        if escolhida is not None:
            texto_resposta = self._resolver_esclarecimento(escolhida, estado, mensagem)
            return Resposta(texto_resposta, escolhida, "aceita")

        # "tem prato para 2 pessoas?": porcao do cardapio, nao reserva.
        texto_porcao = self._consultar_porcao(mensagem, texto)
        if texto_porcao is not None:
            estado.falhas_seguidas = 0
            estado.esclarecimento = None
            estado.assunto_anterior = "cardapio_alergenicos"
            estado.filtros_cardapio = _filtros_vazios()
            return Resposta(texto_porcao, "cardapio_alergenicos", "aceita")

        # "tem algo ate 50 reais?", "qual o prato mais barato?": filtro de
        # preco do cardapio, qualquer que seja a intencao do classificador.
        resposta_preco = self._consultar_preco(mensagem, texto, estado)
        if resposta_preco is not None:
            return resposta_preco

        multiplos = detectar_pedidos_multiplos(self.modelo, mensagem)
        if multiplos is not None:
            resposta = self._perguntar_por_onde_comecar(multiplos, estado)
            resposta.probabilidades = multiplos.probabilidades
            return resposta

        # Data solta ("Sabado"): so sem assunto anterior e sem esclarecimento
        # pendente. Com assunto anterior, a heranca de contexto trata.
        if estado.assunto_anterior is None and estado.esclarecimento is None:
            entidades = extrair_entidades(mensagem, self.agora())
            if self._so_data(texto, entidades):
                return self._esclarecer_data(estado, entidades)

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
           mas nao o objeto principal (a data, no horario; no cardapio, o
           prato, com um pronome ou um "e ..." apontando para ultimo_prato,
           ou os filtros da ultima lista, que se somam aos novos);
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
        herdar_filtros = False
        if assunto == "horario_localizacao":
            # Com data, so a data muda ("e no domingo?"). Sem data, herda se a
            # continuacao tem um subtema da base ("e e pago?", "e o endereco?").
            if not entidades["data"]:
                # Import local: chatbot.conhecimento importa deste modulo.
                from chatbot.conhecimento import responder_horario_localizacao

                if responder_horario_localizacao(mensagem, self.base, self.agora()) is None:
                    return None
        elif assunto == "cardapio_alergenicos":
            tem_criterio = entidades["alergenicos"] or entidades["restricoes"]
            sem_prato = not entidades["pratos"] and not entidades["pratos_ambiguos"]
            # A ultima resposta foi sobre um prato (filtros_cardapio None):
            # "ele tem gluten?" ou "e camarao?" falam desse prato.
            sobre_o_prato = _RE_PRONOME.search(texto) or (
                estado.filtros_cardapio is None and _RE_CONTINUACAO.match(texto)
            )
            if tem_criterio and sem_prato and estado.ultimo_prato and sobre_o_prato:
                entidades["pratos"] = [estado.ultimo_prato]
            elif (
                sem_prato
                and (tem_criterio or entidades["categorias"])
                and estado.filtros_cardapio is not None
            ):
                # A ultima resposta foi uma lista: os filtros dela se somam
                # aos novos ("sou alergico a frutos do mar" -> "e entrada?").
                herdar_filtros = True
            else:
                return None
        else:
            return None

        estado.falhas_seguidas = 0
        estado.esclarecimento = None
        texto_resposta = self._responder_intencao(
            assunto, estado, mensagem, entidades=entidades, herdar_filtros=herdar_filtros
        )
        return Resposta(texto_resposta, assunto, "aceita", decisao.confianca, herdou_contexto=True)

    # --- Regras prioritarias --------------------------------------------------

    def _aplicar_regras(self, texto: str, estado: EstadoConversa) -> Resposta | None:
        """Testa as regras na ordem: atendente, cancelar, contato, ajuda, saudacao/despedida.

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

        if _RE_CONTATO.search(texto):
            estado.falhas_seguidas = 0
            restaurante = self.base["restaurante"]
            texto_resposta = MENSAGENS_REGRAS["contato"].format(
                whatsapp=restaurante["whatsapp"], telefone=restaurante["telefone"]
            )
            if em_reserva:
                texto_resposta += "\n\n" + self._lembrete(estado)
            return Resposta(texto_resposta, None, "regra")

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

    # --- Data solta e resolucao do esclarecimento -----------------------------

    def _so_data(self, texto: str, entidades: dict) -> bool:
        """Diz se a mensagem e SO uma data/periodo ("Sabado", "amanha a noite").

        Exige uma data reconhecida por extrair_entidades e que, tirando as
        palavras de data, periodo, horario e conectivos curtos, nao sobre
        nenhuma palavra. Em "sabado voces abrem?" e "quero reservar sabado"
        sobram palavras: nao sao data solta.
        """
        if not entidades.get("data"):
            return False
        palavras = _RE_QUE_VEM.sub(" ", preprocessar(texto)).split()
        return bool(palavras) and all(p in _PALAVRAS_DATA for p in palavras)

    def _esclarecer_data(self, estado: EstadoConversa, entidades: dict) -> Resposta:
        """Data solta: guarda a data (e o horario) e pergunta se e reserva ou horario."""
        estado.ultima_data = entidades["data"]
        estado.data_solta = {"data": entidades["data"], "horario": entidades.get("horario")}
        estado.esclarecimento = ["reserva", "horario_localizacao"]
        horario = f", às {entidades['horario']}" if entidades.get("horario") else ""
        texto = MENSAGENS_RESERVA["data_solta"].format(
            data=_data_por_extenso(date.fromisoformat(entidades["data"])), horario=horario
        )
        return Resposta(texto, None, "esclarecimento")

    def _intencao_por_palavra_chave(self, texto: str, estado: EstadoConversa) -> str | None:
        """Resposta curta a um esclarecimento pendente, por palavra-chave.

        "reserva", "reservar", "mesa" -> reserva; "horario", "abre",
        "funcionamento" -> horario_localizacao. So vale se a intencao for uma
        das candidatas pendentes e se so uma delas casar.
        """
        if not estado.esclarecimento or len(texto.split()) > MAX_PALAVRAS_HERANCA:
            return None
        achadas = [
            intencao for intencao, regex in _PALAVRAS_CHAVE_INTENCAO
            if intencao in estado.esclarecimento and regex.search(texto)
        ]
        return achadas[0] if len(achadas) == 1 else None

    def _resolver_esclarecimento(self, intencao: str, estado: EstadoConversa, mensagem: str) -> str:
        """Responde a intencao escolhida/aceita e encerra o esclarecimento pendente.

        Se o pendente veio de uma data solta, a data volta a ser usada:
        a reserva comeca com o slot data (e horario) preenchido; o horario
        responde o funcionamento daquele dia. Se a resposta traz uma data
        propria ("e domingo?" -> esclarecimento -> "e segunda?"), vale a nova.
        """
        pendente = estado.esclarecimento
        data_solta = estado.data_solta if pendente else None
        if data_solta:
            novas = extrair_entidades(mensagem, self.agora())
            if novas["data"]:
                data_solta = {
                    "data": novas["data"],
                    "horario": novas.get("horario") or data_solta.get("horario"),
                }
        estado.falhas_seguidas = 0
        estado.esclarecimento = None
        estado.data_solta = None
        estado.assunto_anterior = intencao

        if data_solta and intencao == "reserva":
            return self._iniciar_reserva(mensagem, estado, slots_iniciais=data_solta)
        if data_solta and intencao == "horario_localizacao":
            estado.ultima_data = data_solta["data"]
            return self._horario_do_dia(date.fromisoformat(data_solta["data"]))
        return self._responder_intencao(intencao, estado, mensagem, resolveu=pendente)

    def _perguntar_por_onde_comecar(self, decisao: Decisao, estado: EstadoConversa) -> Resposta:
        """Mensagem com pedidos de assuntos diferentes: lista e pergunta por qual comecar.

        Reaproveita estado.esclarecimento (com 2 ou mais candidatas): no turno
        seguinte, a intencao aceita resolve o pendente, como no esclarecimento
        comum. Nao conta como falha nem zera o contador.
        """
        estado.esclarecimento = list(decisao.candidatas)
        estado.data_solta = None
        assuntos = "; ".join(
            f"{n}) {NOMES_INTENCOES.get(intencao, intencao)}"
            for n, intencao in enumerate(decisao.candidatas, start=1)
        )
        texto = MENSAGENS_REGRAS["pedidos_multiplos"].format(assuntos=assuntos)
        return Resposta(texto, None, "esclarecimento", decisao.confianca)

    def _tratar_decisao(self, decisao: Decisao, estado: EstadoConversa, mensagem: str) -> Resposta:
        """Transforma a Decisao do modelo em Resposta e atualiza o estado."""
        if decisao.tipo == "aceita":
            # Aceita: entendeu. Se havia esclarecimento pendente, esta
            # resposta o resolve (seja uma das candidatas ou outro assunto;
            # se veio de uma data solta, a data e reaproveitada).
            texto = self._resolver_esclarecimento(decisao.intencao, estado, mensagem)
            return Resposta(texto, decisao.intencao, "aceita", decisao.confianca)

        if decisao.tipo == "esclarecimento":
            # Duvida entre duas intencoes de dominio: pergunta em vez de chutar.
            # Nao conta como falha nem zera o contador.
            estado.esclarecimento = list(decisao.candidatas)
            estado.data_solta = None
            opcao_1, opcao_2 = (NOMES_INTENCOES.get(i, i) for i in decisao.candidatas)
            texto = self._sortear(self.base["esclarecimento"]).format(
                opcao_1=opcao_1, opcao_2=opcao_2
            )
            return Resposta(texto, None, "esclarecimento", decisao.confianca)

        # Abstencao e fallback encerram qualquer esclarecimento pendente
        # (inclusive o de uma data solta).
        estado.esclarecimento = None
        estado.data_solta = None

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
        herdar_filtros: bool = False,
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
        `herdar_filtros` soma aos filtros da mensagem os da ultima lista do
        cardapio (estado.filtros_cardapio).
        """
        if intencao == "reserva":
            return self._iniciar_reserva(mensagem, estado)
        if entidades is None:
            entidades = extrair_entidades(mensagem, self.agora()) if mensagem else None

        if entidades and intencao == "horario_localizacao" and entidades["data"]:
            estado.ultima_data = entidades["data"]
            return self._horario_do_dia(date.fromisoformat(entidades["data"]))

        if intencao == "horario_localizacao" and mensagem:
            # Import local: chatbot.conhecimento importa deste modulo.
            from chatbot.conhecimento import responder_horario_localizacao

            texto = responder_horario_localizacao(mensagem, self.base, self.agora())
            if texto is not None:
                return texto

        if entidades and intencao == "cardapio_alergenicos":
            texto = self._consultar_cardapio(mensagem, entidades, estado, herdar_filtros)
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

    def _consultar_cardapio(
        self, mensagem: str, entidades: dict, estado: EstadoConversa, herdar_filtros: bool = False
    ) -> str | None:
        """Responde sobre o cardapio a partir das entidades; None se nao ha nenhuma util.

        - prato + restricao: o prato atende a restricao?
        - prato + alergenico: o prato contem o alergenico?
        - so prato: descricao, preco e alergenicos do prato;
        - so restricao: pratos compativeis;
        - so alergenico: pratos sem ele (se o cliente quer evitar) ou com ele;
        - categoria, grupo ("frutos do mar") ou varios criterios juntos: uma
          lista so, com os pratos que passam em todos (_listar_filtrado);
        - pedido do cardapio sem criterio ("quero ver o cardapio"): o
          cardapio inteiro por categoria, com precos.
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
            estado.filtros_cardapio = None
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

        texto = preprocessar(mensagem)
        evitar = bool(_RE_EVITAR.search(texto))
        if evitar:
            liberados = self._alergenicos_liberados(mensagem)
            alergenicos = [a for a in alergenicos if a not in liberados]
        filtros = {
            "categorias": [c for c in entidades.get("categorias", []) if c in _CATEGORIAS_CARDAPIO],
            "restricoes": restricoes,
            "alergenicos": alergenicos,
            "grupos": entidades.get("grupos_alergenicos", []),
            "evitar": evitar,
            "preco_min": (entidades.get("preco") or {}).get("min"),
            "preco_max": (entidades.get("preco") or {}).get("max"),
            "ordem": (entidades.get("preco") or {}).get("ordem"),
        }
        if herdar_filtros and estado.filtros_cardapio is not None:
            # "e amendoim?" depois de "sou alergico a camarao": sem pista de
            # sentido, um "e ..." continua no sentido da lista anterior.
            if not filtros["evitar"] and _RE_CONTINUACAO.match(texto):
                filtros["evitar"] = estado.filtros_cardapio["evitar"]
            filtros = _mesclar_filtros(estado.filtros_cardapio, filtros)
        cobertos = {_ALERGENICO_DA_RESTRICAO.get(r) for r in filtros["restricoes"]}
        filtros["alergenicos"] = [a for a in filtros["alergenicos"] if a not in cobertos]

        tem_preco = (
            filtros["preco_min"] is not None or filtros["preco_max"] is not None or filtros["ordem"]
        )
        if filtros["restricoes"] or filtros["alergenicos"] or filtros["categorias"] or tem_preco:
            estado.filtros_cardapio = filtros
            return self._listar_filtrado(**filtros)
        if _RE_VER_CARDAPIO.search(texto):
            estado.filtros_cardapio = _filtros_vazios()
            return self._cardapio_completo()
        return self._fora_do_cardapio(mensagem, texto)

    def _consultar_preco(self, mensagem: str, texto: str, estado: EstadoConversa) -> Resposta | None:
        """Pergunta com faixa ou ordem de preco: lista do cardapio filtrada.

        Nao vale quando a mensagem fala de reserva/mesa nem quando cita um
        prato ("quanto custa o pudim?" segue o caminho normal). Continuacao
        curta de uma lista ("e ate 100 reais?") herda os filtros dela.
        """
        if _RE_FALA_DE_RESERVA.search(texto):
            return None
        entidades = extrair_entidades(mensagem, self.agora())
        if not entidades["preco"] or entidades["pratos"] or entidades["pratos_ambiguos"]:
            return None
        herdar = (
            estado.assunto_anterior == "cardapio_alergenicos"
            and estado.filtros_cardapio is not None
            and len(texto.split()) <= MAX_PALAVRAS_HERANCA
        )
        texto_resposta = self._consultar_cardapio(mensagem, entidades, estado, herdar)
        if texto_resposta is None:
            return None
        estado.falhas_seguidas = 0
        estado.esclarecimento = None
        estado.assunto_anterior = "cardapio_alergenicos"
        return Resposta(texto_resposta, "cardapio_alergenicos", "aceita", herdou_contexto=herdar)

    def _consultar_porcao(self, mensagem: str, texto: str) -> str | None:
        """Pratos que servem N pessoas ("tem prato para 2 pessoas?", "prato individual").

        So quando a mensagem fala de prato/porcao e de um numero de pessoas,
        e nao de reserva/mesa. Se cita pratos ("o pudim serve 2 pessoas?"),
        responde quantas pessoas cada um serve.
        """
        if not _RE_PORCAO.search(texto) or _RE_FALA_DE_RESERVA.search(texto):
            return None
        entidades = extrair_entidades(mensagem, self.agora())
        pessoas = 1 if _RE_INDIVIDUAL.search(texto) else entidades["pessoas"]
        if pessoas is None:
            return None
        citados = list(entidades["pratos"])
        for candidatos in entidades["pratos_ambiguos"].values():
            citados += candidatos
        citados = [p for p in _unicos(citados) if p in self.pratos]
        if citados:
            return " ".join(
                MENSAGENS_CONSULTA["porcao_prato"].format(
                    prato=self.pratos[p]["nome"],
                    serve=_plural(self.pratos[p]["serve_pessoas"], "pessoa", "pessoas"),
                )
                for p in citados
            )
        nome = _plural(pessoas, "pessoa", "pessoas")
        pratos = [p for p in self.pratos.values() if p["serve_pessoas"] == pessoas]
        if not pratos:
            porcoes = sorted({p["serve_pessoas"] for p in self.pratos.values()})
            opcoes = " ou ".join(str(n) for n in porcoes) + (" pessoa" if porcoes == [1] else " pessoas")
            return MENSAGENS_CONSULTA["porcao_vazia"].format(pessoas=nome, opcoes=opcoes)
        lista = "\n" + self._lista_por_categoria(pratos, com_titulos=True)
        return MENSAGENS_CONSULTA["porcao"].format(pessoas=nome, lista=lista)

    def _fora_do_cardapio(self, mensagem: str, texto: str) -> str | None:
        """Pedido de algo que nao esta na base ("tem pizza?", "tem vinho?").

        Bebidas: a base nao tem a carta, entao indica a equipe. Outro item
        procurado ("tem X?", ate 4 palavras): diz que nao encontrou X no
        cardapio, em vez de uma resposta fixa que desvia do assunto.
        """
        restaurante = self.base["restaurante"]
        if _RE_BEBIDAS.search(texto):
            return MENSAGENS_CONSULTA["sem_bebidas"].format(
                whatsapp=restaurante["whatsapp"], telefone=restaurante["telefone"]
            )
        achado = _RE_TERMO_PROCURADO.match(mensagem)
        if achado:
            termo = achado.group("termo").strip().lower()
            if 0 < len(termo.split()) <= _MAX_PALAVRAS_TERMO:
                return MENSAGENS_CONSULTA["nao_encontrado"].format(termo=f"“{termo}”")
        return None

    def _alergenicos_liberados(self, mensagem: str) -> set[str]:
        """Alergenicos que o cliente diz que PODE comer ("mas como peixe").

        Vale so a oracao com liberacao explicita (no inicio ou no fim) e sem
        nenhuma pista de evitar: na duvida, o alergenico continua evitado
        (por seguranca).
        """
        liberados = set()
        # A pontuacao some no pre-processamento: separa por ela antes.
        trechos = [preprocessar(t) for t in _RE_PONTUACAO_ORACOES.split(mensagem)]
        for oracao in (o for t in trechos for o in _RE_SEPARA_ORACOES.split(t)):
            oracao = _RE_PERGUNTA_FINAL.sub("", oracao).strip()
            # A pista de evitar e conferida fora da propria liberacao ("nao
            # tenho alergia a peixe" tem "alergia", mas libera o peixe).
            inicio, fim = _RE_LIBERADO_INICIO.search(oracao), _RE_LIBERADO_FIM.search(oracao)
            if inicio:
                resto = oracao[inicio.end():]
            elif fim:
                resto = oracao[:fim.start()]
            else:
                continue
            if not _RE_EVITAR.search(resto):
                liberados.update(extrair_entidades(resto, self.agora())["alergenicos"])
        return liberados

    def _listar_filtrado(
        self,
        categorias: list[str],
        restricoes: list[str],
        alergenicos: list[str],
        grupos: list[str],
        evitar: bool,
        preco_min: float | None = None,
        preco_max: float | None = None,
        ordem: str | None = None,
    ) -> str:
        """Pratos que passam em TODOS os criterios ao mesmo tempo.

        - categorias: o prato e de uma delas;
        - restricoes: o prato atende a todas (campos booleanos da base);
        - alergenicos com evitar: o prato nao leva nenhum, nem como "pode
          conter" (por seguranca); sem evitar: o prato leva algum deles;
        - preco_min/preco_max: o preco esta na faixa (limites inclusos);
        - ordem "barato"/"caro": so o mais barato (ou mais caro) de cada categoria.
        Um grupo ("frutos do mar") ja chega expandido em alergenicos; aqui
        so muda o titulo e acrescenta a explicacao do que foi considerado.
        """
        pratos = [
            p for p in self.pratos.values()
            if (not categorias or p["categoria"] in categorias)
            and all(p.get(r) for r in restricoes)
            and self._passa_alergenicos(p, alergenicos, evitar)
            and (preco_min is None or p["preco"] >= preco_min)
            and (preco_max is None or p["preco"] <= preco_max)
        ]
        titulo = self._titulo_lista(
            categorias, restricoes, alergenicos, grupos, evitar, preco_min, preco_max
        )
        if preco_min is not None or preco_max is not None:
            pratos.sort(key=lambda p: p["preco"])  # do mais barato ao mais caro
        if ordem and pratos:
            pratos = _extremo_por_categoria(pratos, ordem)
            if len(categorias) == 1:
                # "Sobremesas (a mais cara)", "Pratos principais (o mais barato)".
                feminino = _CATEGORIAS_CARDAPIO[categorias[0]][1]
                sufixo = MENSAGENS_CONSULTA[f"ordem_{ordem}_{'f' if feminino else 'm'}"]
            else:
                sufixo = (
                    MENSAGENS_CONSULTA[f"ordem_{ordem}_m"] + MENSAGENS_CONSULTA["ordem_por_categoria"]
                )
            titulo = sufixo[0].upper() + sufixo[1:] if titulo == "Pratos" else f"{titulo} ({sufixo})"
        if pratos:
            # Com uma categoria so no pedido, o titulo ja diz qual e.
            com_titulos = len(categorias) != 1
            lista = self._lista_por_categoria(pratos, com_titulos)
            if com_titulos:
                lista = "\n" + lista  # linha em branco entre o titulo e a 1a categoria
            texto_lista = MENSAGENS_CONSULTA["lista_filtrada"].format(titulo=titulo, lista=lista)
        else:
            texto_lista = MENSAGENS_CONSULTA["lista_filtrada_vazia"].format(
                titulo=titulo[0].lower() + titulo[1:]
            )
            if preco_max is not None:
                # Nada na faixa: diz o item mais barato do cardapio inteiro.
                barato = min(self.pratos.values(), key=lambda p: p["preco"])
                texto_lista += " " + MENSAGENS_CONSULTA["preco_mais_barato"].format(
                    nome=barato["nome"], preco=_preco(barato["preco"])
                )

        partes = []
        if grupos and evitar:
            for grupo in grupos:
                ids = self._ids_grupo(grupo)
                partes.append(MENSAGENS_CONSULTA["grupo_considerado"].format(
                    grupo=f"“{grupo}”", itens=_juntar([self._nome_alergenico(a) for a in ids])
                ))
            if "peixes" not in alergenicos and any(
                "peixes" in p["alergenicos"] or "peixes" in p.get("pode_conter", []) for p in pratos
            ):
                partes.append(MENSAGENS_CONSULTA["grupo_peixe"])

        # Observacoes e aviso num paragrafo separado, depois da lista.
        if alergenicos or restricoes:
            partes = [self._com_aviso(" ".join(partes), alergenicos).strip()]
        if partes and partes[0]:
            return texto_lista + "\n\n" + partes[0]
        return texto_lista

    @staticmethod
    def _passa_alergenicos(prato: dict, alergenicos: list[str], evitar: bool) -> bool:
        """Sem alergenicos, passa; evitando, nao pode ter nenhum; senao, precisa ter algum."""
        if not alergenicos:
            return True
        presentes = set(prato["alergenicos"])
        if evitar:
            presentes |= set(prato.get("pode_conter", []))
            return not presentes & set(alergenicos)
        return bool(presentes & set(alergenicos))

    def _titulo_lista(
        self,
        categorias: list[str],
        restricoes: list[str],
        alergenicos: list[str],
        grupos: list[str],
        evitar: bool,
        preco_min: float | None = None,
        preco_max: float | None = None,
    ) -> str:
        """'Pratos principais sem frutos do mar', 'Sobremesas veganas', 'Pratos até R$ 50,00'..."""
        if categorias:
            nomes = [_CATEGORIAS_CARDAPIO[c][0] for c in categorias]
            titulo = nomes[0] + "".join(
                (" e " if i == len(nomes) - 1 else ", ") + n.lower() for i, n in enumerate(nomes[1:], 1)
            )
            feminino = all(_CATEGORIAS_CARDAPIO[c][1] for c in categorias)
        elif restricoes and not alergenicos:
            titulo, feminino = "Opções", True
        else:
            titulo, feminino = "Pratos", False

        if restricoes:
            titulo += " " + _juntar([_ADJETIVOS_RESTRICOES[r][0 if feminino else 1] for r in restricoes])
        if alergenicos:
            # Os ids de um grupo aparecem pelo nome do grupo ("frutos do mar").
            do_grupo = {a for g in grupos for a in self._ids_grupo(g)}
            nomes = list(grupos) + [self._nome_alergenico(a) for a in alergenicos if a not in do_grupo]
            if evitar:
                # "Pratos sem glúten e sem frutos do mar" (nao "sem glúten sem").
                titulo += (" e sem " if restricoes else " sem ") + _juntar(nomes)
            else:
                titulo += " que levam " + _juntar(nomes)
        if preco_min is not None and preco_max is not None:
            titulo += " " + MENSAGENS_CONSULTA["faixa_entre"].format(
                minimo=_preco(preco_min), maximo=_preco(preco_max)
            )
        elif preco_max is not None:
            titulo += " " + MENSAGENS_CONSULTA["faixa_ate"].format(maximo=_preco(preco_max))
        elif preco_min is not None:
            titulo += " " + MENSAGENS_CONSULTA["faixa_a_partir"].format(minimo=_preco(preco_min))
        return titulo

    def _ids_grupo(self, grupo: str) -> list[str]:
        """Ids dos alergenicos de um termo de alergenicos.termos_ambiguos."""
        for termo in self.base["alergenicos"].get("termos_ambiguos", []):
            if termo["termo"] == grupo:
                return termo["ids"]
        return []

    def _cardapio_completo(self) -> str:
        """Cardapio inteiro, por categoria, com precos."""
        lista = self._lista_por_categoria(list(self.pratos.values()), com_titulos=True)
        return MENSAGENS_CONSULTA["cardapio_completo"].format(lista=lista)

    @staticmethod
    def _lista_por_categoria(pratos: list[dict], com_titulos: bool) -> str:
        """Um prato por linha, com recuo e preco, agrupado por categoria.

        Entradas:
           • Ostras in Natura (dúzia) – R$ 59,90
           • ...
        Sem titulos (o pedido ja era de uma categoria so), so as linhas.
        """
        blocos = []
        for categoria, (nome, _) in _CATEGORIAS_CARDAPIO.items():
            linhas = [
                MENSAGENS_CONSULTA["item_lista"].format(nome=p["nome"], preco=_preco(p["preco"]))
                for p in pratos if p["categoria"] == categoria
            ]
            if not linhas:
                continue
            if com_titulos:
                linhas.insert(0, MENSAGENS_CONSULTA["titulo_categoria"].format(categoria=nome))
            blocos.append("\n".join(linhas))
        return ("\n\n" if com_titulos else "\n").join(blocos)

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
            preco=_preco(prato["preco"]),
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

    def _iniciar_reserva(
        self, mensagem: str, estado: EstadoConversa, slots_iniciais: dict | None = None
    ) -> str:
        """Abre o fluxo de reserva, ja aproveitando os slots da mensagem.

        Se a mensagem e sobre uma reserva existente (cancelar, alterar,
        atraso), responde a politica da base em vez de abrir uma reserva nova.
        slots_iniciais: slots ja conhecidos (ex.: a data solta escolhida no
        esclarecimento); os da propria mensagem tem prioridade sobre eles.
        """
        texto = preprocessar(mensagem)
        for chave, regex in _RE_POLITICAS:
            if regex.search(texto):
                return self._regra_reserva(chave)

        estado.etapa_reserva = "coletando"
        estado.slots = {}
        novos = {k: v for k, v in (slots_iniciais or {}).items() if v}
        novos.update(self._extrair_slots(mensagem, estado))
        if novos:
            texto_slots = self._preencher_slots(novos, estado)
            if slots_iniciais:
                return MENSAGENS_RESERVA["inicio"] + " " + texto_slots
            return texto_slots
        return MENSAGENS_RESERVA["inicio"] + " " + self._pergunta(estado)

    def _regra_reserva(self, chave: str) -> str:
        """Texto de uma politica da base, ou de uma regra montada com os numeros dela."""
        regras = self.regras_reserva
        if chave == "regra_antecedencia":
            return MENSAGENS_RESERVA["regra_antecedencia"].format(
                minimo=_plural(regras["antecedencia_minima_horas"], "hora", "horas"),
                maximo=_plural(regras["antecedencia_maxima_dias"], "dia", "dias"),
                janela=regras["janela"]["regra"],
            )
        if chave == "regra_pessoas":
            restaurante = self.base["restaurante"]
            return MENSAGENS_RESERVA["regra_pessoas"].format(
                minimo=regras["min_pessoas"],
                maximo=regras["max_pessoas"],
                whatsapp=restaurante["whatsapp"],
                telefone=restaurante["telefone"],
            )
        return regras[chave]

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
        acima_do_limite = (novos.get("pessoas") or 0) > self.regras_reserva["max_pessoas"]
        erro = self._validar(estado)
        if erro is not None and acima_do_limite:
            # Grupo grande foi encaminhado para a equipe: encerra o fluxo em
            # vez de perguntar "para quantas pessoas?" logo em seguida.
            estado.encerrar_reserva()
            return erro + "\n\n" + MENSAGENS_RESERVA["acima_limite_alternativa"].format(
                maximo=self.regras_reserva["max_pessoas"]
            )
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
