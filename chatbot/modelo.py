"""Classificador de intencoes da Maresia: TF-IDF + Regressao Logistica.

Fluxo: carregar_dataset -> treinar_modelo -> salvar_modelo. Em uso:
carregar_modelo -> classificar (prever_probabilidades + decidir).
"""

import csv
from dataclasses import dataclass, field
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

from chatbot.config import (
    ARQUIVO_MODELO,
    C_REGULARIZACAO,
    CAMINHO_DATASET,
    CLASS_WEIGHT,
    INTENCAO_FORA_ESCOPO,
    LIMIAR_CONFIANCA,
    MARGEM_MINIMA,
    MAX_ITER,
    MIN_SEGUNDA_ESCLARECIMENTO,
    NGRAM_CARACTERES,
    NGRAM_PALAVRAS,
    SEMENTE,
    SOMA_ESCLARECIMENTO,
    SUBLINEAR_TF,
)
from chatbot.preprocessamento import preprocessar

# Folga para erros de arredondamento de ponto flutuante nas comparacoes
# inclusivas (ex.: 0.60 - 0.45 da 0.14999999999999997 em vez de 0.15).
_TOLERANCIA = 1e-9

TIPOS_DECISAO = ("aceita", "abstencao", "esclarecimento", "fallback")


def carregar_dataset(caminho=CAMINHO_DATASET) -> tuple[list[str], list[str]]:
    """Le o CSV de treino (cabecalho frase,intencao) e devolve (frases, intencoes)."""
    frases, intencoes = [], []
    with open(caminho, encoding="utf-8", newline="") as arquivo:
        for linha in csv.DictReader(arquivo):
            frases.append(linha["frase"])
            intencoes.append(linha["intencao"])
    return frases, intencoes


def construir_pipeline() -> Pipeline:
    """Monta o pipeline (ainda nao treinado) de vetorizacao + classificacao.

    Dois TF-IDF lado a lado (FeatureUnion):
    - "palavras": captura termos e expressoes ("reservar mesa");
    - "caracteres": n-gramas de caracteres dentro das palavras, que toleram
      erros de digitacao ("resevar", "camarao" x "camaroes").
    Os dois aplicam o mesmo preprocessar() antes de vetorizar.
    """
    vetorizadores = FeatureUnion([
        ("palavras", TfidfVectorizer(
            preprocessor=preprocessar,
            analyzer="word",
            ngram_range=NGRAM_PALAVRAS,
            sublinear_tf=SUBLINEAR_TF,
        )),
        ("caracteres", TfidfVectorizer(
            preprocessor=preprocessar,
            analyzer="char_wb",
            ngram_range=NGRAM_CARACTERES,
            sublinear_tf=SUBLINEAR_TF,
        )),
    ])
    # Nao passamos multi_class (depreciado no scikit-learn): com o solver
    # lbfgs e mais de 2 classes a regressao ja e multinomial (softmax), entao
    # as probabilidades das intencoes somam 1.
    classificador = LogisticRegression(
        C=C_REGULARIZACAO,
        class_weight=CLASS_WEIGHT,
        max_iter=MAX_ITER,
        random_state=SEMENTE,
        solver="lbfgs",
    )
    return Pipeline([("vetorizadores", vetorizadores), ("classificador", classificador)])


def treinar_modelo(frases: list[str], intencoes: list[str]) -> Pipeline:
    """Treina um pipeline novo com as frases e seus rotulos."""
    modelo = construir_pipeline()
    modelo.fit(frases, intencoes)
    return modelo


def salvar_modelo(modelo: Pipeline, caminho=ARQUIVO_MODELO) -> Path:
    """Salva o modelo treinado com joblib, criando a pasta se preciso."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(modelo, caminho)
    return caminho


def carregar_modelo(caminho=ARQUIVO_MODELO) -> Pipeline:
    """Carrega o modelo salvo. Erro claro se ele ainda nao foi treinado."""
    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(
            f"Modelo nao encontrado em '{caminho}'. "
            "Treine o classificador antes com: python treinar.py"
        )
    return joblib.load(caminho)


def prever_probabilidades(modelo: Pipeline, texto: str) -> dict[str, float]:
    """Devolve {intencao: probabilidade} para o texto (soma 1)."""
    probabilidades = modelo.predict_proba([texto])[0]
    return {
        str(intencao): float(prob)
        for intencao, prob in zip(modelo.classes_, probabilidades)
    }


@dataclass
class Decisao:
    """Resultado da politica de decisao sobre as probabilidades do modelo.

    tipo: "aceita", "abstencao", "esclarecimento" ou "fallback".
    intencao: intencao aceita (ou a mais provavel, nos outros casos).
    confianca: probabilidade da intencao mais provavel.
    candidatas: as duas intencoes oferecidas no esclarecimento.
    probabilidades: todas as probabilidades, para depuracao/interface.
    """

    tipo: str
    intencao: str | None
    confianca: float
    candidatas: list[str] = field(default_factory=list)
    probabilidades: dict[str, float] = field(default_factory=dict)


def _maior_ou_igual(valor: float, limite: float) -> bool:
    """Comparacao inclusiva (>=) tolerante a arredondamento."""
    return valor >= limite - _TOLERANCIA


def decidir(probabilidades: dict[str, float]) -> Decisao:
    """Aplica a politica de decisao, nesta ordem: aceita, abstencao,
    esclarecimento, fallback."""
    ordenadas = sorted(probabilidades.items(), key=lambda item: item[1], reverse=True)
    top1, prob1 = ordenadas[0]
    prob2 = ordenadas[1][1] if len(ordenadas) > 1 else 0.0

    # a) Aceita: o modelo esta confiante (>= limiar) E a 1a intencao se
    # destaca da 2a (margem). Sem a margem, um 0.46 x 0.44 seria aceito
    # mesmo sendo praticamente um empate.
    if (
        top1 != INTENCAO_FORA_ESCOPO
        and _maior_ou_igual(prob1, LIMIAR_CONFIANCA)
        and _maior_ou_igual(prob1 - prob2, MARGEM_MINIMA)
    ):
        return Decisao("aceita", top1, prob1, [], probabilidades)

    # b) Abstencao: se o mais provavel e fora do escopo, a Maresia recusa
    # com educacao, mesmo com confianca baixa. Melhor nao responder do que
    # inventar uma resposta sobre um assunto que nao e do restaurante.
    if top1 == INTENCAO_FORA_ESCOPO:
        return Decisao("abstencao", top1, prob1, [], probabilidades)

    # c) Esclarecimento: entre as intencoes de dominio, as duas primeiras
    # concentram a maior parte da probabilidade e a 2a nao e desprezivel.
    # Ou seja, a mensagem e do dominio, mas o modelo hesita entre duas:
    # perguntar e melhor do que chutar. fora_escopo nunca vira candidata.
    dominio = [item for item in ordenadas if item[0] != INTENCAO_FORA_ESCOPO]
    if len(dominio) >= 2:
        (intencao_a, prob_a), (intencao_b, prob_b) = dominio[0], dominio[1]
        if (
            _maior_ou_igual(prob_a + prob_b, SOMA_ESCLARECIMENTO)
            and _maior_ou_igual(prob_b, MIN_SEGUNDA_ESCLARECIMENTO)
        ):
            return Decisao(
                "esclarecimento", top1, prob1, [intencao_a, intencao_b], probabilidades
            )

    # d) Fallback: a probabilidade esta espalhada e nada se destaca;
    # a Maresia diz que nao entendeu e sugere os assuntos que conhece.
    return Decisao("fallback", top1, prob1, [], probabilidades)


def classificar(modelo: Pipeline, texto: str) -> Decisao:
    """Atalho: preve as probabilidades do texto e aplica decidir()."""
    return decidir(prever_probabilidades(modelo, texto))
