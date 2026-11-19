"""Gerenciador de dialogo da Maresia.

Para cada mensagem, nesta ordem:
1. regras prioritarias (atendente, cancelar, ajuda, saudacao/despedida),
   avaliadas sobre o texto pre-processado, antes do classificador;
2. classificador de intencoes + politica de decisao (modelo.classificar);
3. tratamento da decisao: aceita, esclarecimento, abstencao ou fallback,
   com encaminhamento humano depois de MAX_FALHAS_SEGUIDAS falhas.

Os textos de fallback, esclarecimento, encaminhamento humano e as respostas
de cada intencao vem da base de conhecimento (CAMINHO_BASE). Os textos das
regras prioritarias nao existem na base e ficam em MENSAGENS_REGRAS.
"""

import json
import random
import re
from dataclasses import dataclass, field

from chatbot.config import CAMINHO_BASE, INTENCAO_FORA_ESCOPO, MAX_FALHAS_SEGUIDAS
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

# Indices das mensagens de encaminhamento_humano na base: a 1a fala de
# "nao estou conseguindo te ajudar" (falhas); a 2a, de "vou te passar para
# um atendente" (pedido explicito).
_ENCAMINHAR_POR_FALHAS = 0
_ENCAMINHAR_POR_PEDIDO = 1

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


@dataclass
class EstadoConversa:
    """Estado de uma conversa entre uma mensagem e outra.

    falhas_seguidas: mensagens seguidas sem entender (fallback).
    assunto_anterior: intencao da ultima resposta aceita.
    esclarecimento: intencoes candidatas aguardando o cliente escolher.
    slots: dados da reserva em andamento (preenchidos em etapas futuras).
    encaminhado: se a conversa ja foi encaminhada para um atendente.
    """

    falhas_seguidas: int = 0
    assunto_anterior: str | None = None
    esclarecimento: list[str] | None = None
    slots: dict = field(default_factory=dict)
    encaminhado: bool = False

    def reiniciar(self) -> None:
        """Volta o estado ao inicio da conversa."""
        self.falhas_seguidas = 0
        self.assunto_anterior = None
        self.esclarecimento = None
        self.slots = {}
        self.encaminhado = False


@dataclass
class Resposta:
    """Resposta da Maresia a uma mensagem.

    tipo: "regra", "aceita", "esclarecimento", "abstencao", "fallback"
    ou "encaminhamento".
    """

    texto: str
    intencao: str | None
    tipo: str
    confianca: float | None = None


def carregar_base(caminho=CAMINHO_BASE) -> dict:
    """Le a base de conhecimento (JSON em UTF-8)."""
    with open(caminho, encoding="utf-8") as arquivo:
        return json.load(arquivo)


class GerenciadorDialogo:
    """Decide a resposta de cada mensagem e atualiza o EstadoConversa."""

    def __init__(self, modelo, base: dict | None = None, aleatorio: random.Random | None = None):
        """modelo: pipeline treinado; base: base de conhecimento (carregada
        de CAMINHO_BASE se omitida); aleatorio: gerador para sortear entre
        as variacoes de cada mensagem (permite resultados fixos nos testes).
        """
        self.modelo = modelo
        self.base = base if base is not None else carregar_base()
        self.aleatorio = aleatorio or random.Random()
        self.respostas_fixas = {
            item["intencao"]: item["respostas_fixas"] for item in self.base["intencoes"]
        }
        nome = self.base["restaurante"]["nome"]
        assuntos = list(NOMES_INTENCOES.values())
        self._campos_texto = {
            "restaurante": nome,
            "assunto_1": assuntos[0],
            "assunto_2": assuntos[1],
            "assunto_3": assuntos[2],
        }

    # --- Entrada principal ----------------------------------------------------

    def responder(self, mensagem: str, estado: EstadoConversa) -> Resposta:
        """Responde a mensagem: regras prioritarias primeiro, depois o modelo."""
        resposta = self._aplicar_regras(preprocessar(mensagem), estado)
        if resposta is not None:
            return resposta
        decisao = self._ajustar_decisao(classificar(self.modelo, mensagem), mensagem)
        return self._tratar_decisao(decisao, estado)

    # --- Regras prioritarias --------------------------------------------------

    def _aplicar_regras(self, texto: str, estado: EstadoConversa) -> Resposta | None:
        """Testa as regras na ordem: atendente, cancelar, ajuda, saudacao/despedida.

        Qualquer regra que case zera falhas_seguidas: a mensagem foi entendida.
        """
        if _RE_ATENDENTE.search(texto):
            estado.falhas_seguidas = 0
            estado.encaminhado = True
            return Resposta(self._encaminhamento(_ENCAMINHAR_POR_PEDIDO), None, "encaminhamento")

        if _RE_CANCELAR.match(texto):
            estado.falhas_seguidas = 0
            estado.slots = {}
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

    def _tratar_decisao(self, decisao: Decisao, estado: EstadoConversa) -> Resposta:
        """Transforma a Decisao do modelo em Resposta e atualiza o estado."""
        pendente = estado.esclarecimento

        if decisao.tipo == "aceita":
            # Aceita: entendeu. Se havia esclarecimento pendente, esta
            # resposta o resolve (seja uma das candidatas ou outro assunto).
            estado.falhas_seguidas = 0
            estado.esclarecimento = None
            estado.assunto_anterior = decisao.intencao
            texto = self._responder_intencao(decisao.intencao, estado, resolveu=pendente)
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
        estado.falhas_seguidas += 1
        if estado.falhas_seguidas >= MAX_FALHAS_SEGUIDAS:
            estado.falhas_seguidas = 0
            estado.encaminhado = True
            return Resposta(
                self._encaminhamento(_ENCAMINHAR_POR_FALHAS), None, "encaminhamento",
                decisao.confianca,
            )
        return Resposta(self._sortear(self.base["fallback"]), None, "fallback", decisao.confianca)

    # --- Respostas ------------------------------------------------------------

    def _responder_intencao(
        self, intencao: str, estado: EstadoConversa, resolveu: list[str] | None = None
    ) -> str:
        """Monta a resposta de uma intencao aceita.

        Por enquanto usa as respostas_fixas da base. Ponto de extensao para
        respostas detalhadas por intencao (pratos, reserva com slots,
        horarios do dia...). `resolveu` traz as candidatas do esclarecimento
        que esta resposta encerrou, se houver.
        """
        return self._sortear(self.respostas_fixas[intencao])

    def _encaminhamento(self, indice: int) -> str:
        """Mensagem de encaminhamento humano da base."""
        mensagens = self.base["encaminhamento_humano"]
        return mensagens[min(indice, len(mensagens) - 1)]

    def _sortear(self, opcoes: list[str]) -> str:
        """Escolhe uma das variacoes de uma mensagem."""
        return self.aleatorio.choice(opcoes)
