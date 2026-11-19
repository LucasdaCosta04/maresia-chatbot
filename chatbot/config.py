"""Parametros ajustaveis da Maresia (limiares, caminhos e fuso horario)."""

from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent

LIMIAR_CONFIANCA = 0.45
MARGEM_MINIMA = 0.15
MAX_FALHAS_SEGUIDAS = 2
CAMINHO_BASE = _RAIZ / "dados" / "base_conhecimento.json"
CAMINHO_MODELO = _RAIZ / "modelos"
FUSO_HORARIO = "America/Sao_Paulo"

# --- Dados e modelo ---
# Dataset de treino do classificador (CSV com cabecalho frase,intencao).
CAMINHO_DATASET = _RAIZ / "dados" / "intencoes_treino.csv"
# Arquivo do modelo treinado, salvo dentro de CAMINHO_MODELO.
ARQUIVO_MODELO = CAMINHO_MODELO / "classificador.joblib"

# --- Vetorizador (TF-IDF) ---
# Faixa de n-gramas do TF-IDF de palavras (unigramas e bigramas).
NGRAM_PALAVRAS = (1, 2)
# Faixa de n-gramas do TF-IDF de caracteres (tolera erros de digitacao).
NGRAM_CARACTERES = (2, 5)
# Usa 1 + log(tf) para suavizar palavras repetidas na mesma frase.
SUBLINEAR_TF = True

# --- Classificador (Regressao Logistica) ---
# Inverso da forca de regularizacao: maior = menos regularizacao.
C_REGULARIZACAO = 10
# Compensa classes desbalanceadas ajustando o peso de cada uma.
CLASS_WEIGHT = "balanced"
# Maximo de iteracoes do otimizador.
MAX_ITER = 1000
# Semente aleatoria para resultados reprodutiveis.
SEMENTE = 42

# --- Politica de esclarecimento ---
# Soma minima das duas maiores probabilidades para pedir esclarecimento.
SOMA_ESCLARECIMENTO = 0.70
# Probabilidade minima da 2a intencao para ela entrar no esclarecimento.
MIN_SEGUNDA_ESCLARECIMENTO = 0.20

# --- Intencoes e avaliacao ---
# Rotulo da intencao de assuntos sem relacao com o restaurante.
INTENCAO_FORA_ESCOPO = "fora_escopo"
# Numero de dobras da validacao cruzada estratificada.
FOLDS_VALIDACAO = 5
