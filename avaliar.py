"""Avaliacao cega da Maresia sobre os 34 casos de dados/casos_teste.csv.

Uso:
    python avaliar.py

Cada caso roda numa conversa nova (GerenciadorDialogo + EstadoConversa),
com "agora" fixo em quarta 18/11/2026 18:00 (America/Sao_Paulo) e sorteio
com semente fixa, entao duas execucoes geram arquivos identicos.
O avaliador so mede: nao altera casos, dados, modelo nem dialogo.

Saidas em resultados/: resultados_casos.csv, matriz_testes.md,
resumo_metricas.json, matriz_confusao.png, limiar_confianca.csv/.png,
comparacao_abordagens.csv/.png e verificacao_vazamento.csv.
"""

import csv
import importlib.util
import json
import random
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from sklearn.base import clone  # noqa: E402
from sklearn.model_selection import StratifiedKFold, cross_validate  # noqa: E402
from sklearn.naive_bayes import MultinomialNB  # noqa: E402

import chatbot.modelo as modelo_mod  # noqa: E402
from chatbot.config import (  # noqa: E402
    ARQUIVO_MODELO,
    CAMINHO_DATASET,
    FOLDS_VALIDACAO,
    FUSO_HORARIO,
    SEMENTE,
)
from chatbot.dialogo import EstadoConversa, GerenciadorDialogo, carregar_base  # noqa: E402

_RAIZ = Path(__file__).resolve().parent
PASTA_RESULTADOS = _RAIZ / "resultados"

# scripts/ nao e um pacote: carrega o checador dos casos pelo caminho
# (mesmo jeito de testes/test_casos_teste.py) para reaproveitar a leitura,
# a normalizacao e a medida de similaridade.
_spec = importlib.util.spec_from_file_location(
    "checar_casos_teste", _RAIZ / "scripts" / "checar_casos_teste.py"
)
checar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checar)

# "Agora" dos casos de teste (ver dados/LEIAME_dados.md, Data de referencia).
AGORA_REFERENCIA = datetime(2026, 11, 18, 18, 0, tzinfo=ZoneInfo(FUSO_HORARIO))
LIMIARES = [round(0.30 + 0.05 * i, 2) for i in range(9)]  # 0,30 ... 0,70
SEM_INTENCAO = "nenhuma"
ROTULOS_CONFUSAO = list(checar.INTENCOES_DOMINIO) + ["fora_escopo", SEM_INTENCAO]

COLUNAS_CASOS = [
    "id",
    "categoria",
    "contexto",
    "mensagem",
    "tipo_esperado",
    "intencao_esperada",
    "resposta_deve_conter",
    "tipo_obtido",
    "intencao_obtida",
    "confianca",
    "margem",
    "passou",
    "motivo_falha",
    "resposta",
]

# Paleta (categorica em ordem fixa + tinta de texto) dos graficos.
_COR_1, _COR_2, _COR_3 = "#2a78d6", "#eb6834", "#1baf7a"
_TINTA, _TINTA_SECUNDARIA, _GRADE = "#0b0b0b", "#52514e", "#e4e3df"


# --- Formatacao ---------------------------------------------------------------


def _num(valor) -> str:
    """Float com 4 casas (ponto decimal) para CSV; vazio se None."""
    return "" if valor is None else f"{valor:.4f}"


def _pct(acertos: int, total: int) -> str:
    """Percentual com virgula decimal, ex.: '76,5%'."""
    return f"{100 * acertos / total:.1f}%".replace(".", ",") if total else "-"


def _placar(acertos: int, total: int) -> str:
    """Ex.: '26/34 = 76,5%'."""
    return f"{acertos}/{total} = {_pct(acertos, total)}"


# --- Avaliacao dos casos ------------------------------------------------------


def criar_gerenciador(modelo, base: dict | None = None) -> GerenciadorDialogo:
    """GerenciadorDialogo com relogio fixo e sorteio com semente fixa."""
    return GerenciadorDialogo(
        modelo,
        base,
        aleatorio=random.Random(SEMENTE),
        agora=lambda: AGORA_REFERENCIA,
    )


def _margem(probabilidades: dict[str, float]) -> float | None:
    """Diferenca entre a 1a e a 2a probabilidade (None sem classificador)."""
    if len(probabilidades) < 2:
        return None
    primeira, segunda = sorted(probabilidades.values(), reverse=True)[:2]
    return primeira - segunda


def avaliar_caso(modelo, caso: dict, base: dict | None = None) -> dict:
    """Roda um caso numa conversa nova e confere tipo, intencao e texto."""
    gerente = criar_gerenciador(modelo, base)
    estado = EstadoConversa()
    contexto = caso["contexto"]
    for anterior in contexto.split(checar.SEPARADOR_CONTEXTO) if contexto else []:
        gerente.responder(anterior, estado)
    resposta = gerente.responder(caso["mensagem"], estado)

    tipos = caso["tipo_esperado"].split("|")
    intencao_esperada = caso["intencao_esperada"]
    trecho = caso["resposta_deve_conter"]
    motivos = []
    if resposta.tipo not in tipos:
        motivos.append(f"tipo: esperado {caso['tipo_esperado']}, obtido {resposta.tipo}")
    if intencao_esperada and resposta.intencao != intencao_esperada:
        motivos.append(
            f"intencao: esperada {intencao_esperada}, obtida {resposta.intencao or SEM_INTENCAO}"
        )
    if trecho and trecho not in checar.normalizar_trecho(resposta.texto):
        motivos.append(f"texto: falta '{trecho}'")

    return {
        "id": caso["id"],
        "categoria": caso["categoria"],
        "contexto": contexto,
        "mensagem": caso["mensagem"],
        "tipo_esperado": caso["tipo_esperado"],
        "intencao_esperada": intencao_esperada,
        "resposta_deve_conter": trecho,
        "tipo_obtido": resposta.tipo,
        "intencao_obtida": resposta.intencao or "",
        "confianca": resposta.confianca,
        "margem": _margem(resposta.probabilidades),
        "passou": not motivos,
        "motivo_falha": "; ".join(motivos),
        "resposta": resposta.texto,
    }


def avaliar_casos(modelo, casos: list[dict], base: dict | None = None) -> list[dict]:
    """Avalia todos os casos, cada um numa conversa independente."""
    base = base if base is not None else carregar_base()
    return [avaliar_caso(modelo, caso, base) for caso in casos]


def resumir_por_categoria(resultados: list[dict]) -> dict[str, dict]:
    """{categoria: {"acertos", "total"}}, na ordem de checar.DISTRIBUICAO."""
    total = Counter(r["categoria"] for r in resultados)
    acertos = Counter(r["categoria"] for r in resultados if r["passou"])
    ordem = list(checar.DISTRIBUICAO) + sorted(set(total) - set(checar.DISTRIBUICAO))
    return {c: {"acertos": acertos[c], "total": total[c]} for c in ordem if total[c]}


# --- Validacao cruzada e abordagens -------------------------------------------


def criar_folds() -> StratifiedKFold:
    """Os mesmos folds de treinar.py (FOLDS_VALIDACAO, shuffle, SEMENTE)."""
    return StratifiedKFold(n_splits=FOLDS_VALIDACAO, shuffle=True, random_state=SEMENTE)


def validacao_cruzada(pipeline, frases: list[str], intencoes: list[str]) -> dict:
    """Acuracia e F1-macro (media e desvio) nos folds de treinar.py."""
    resultados = cross_validate(
        pipeline, frases, intencoes, cv=criar_folds(), scoring=["accuracy", "f1_macro"]
    )
    acuracias, f1s = resultados["test_accuracy"], resultados["test_f1_macro"]
    return {
        "acuracia_media": float(np.mean(acuracias)),
        "acuracia_desvio": float(np.std(acuracias)),
        "f1_macro_media": float(np.mean(f1s)),
        "f1_macro_desvio": float(np.std(f1s)),
    }


def abordagens() -> dict:
    """As 4 abordagens comparadas, todas derivadas de construir_pipeline()."""
    atual = modelo_mod.construir_pipeline()
    so_palavras = clone(atual).set_params(vetorizadores__caracteres="drop")
    so_caracteres = clone(atual).set_params(vetorizadores__palavras="drop")
    naive_bayes = clone(so_palavras).set_params(classificador=MultinomialNB())
    return {
        "TF-IDF palavras + LR": so_palavras,
        "TF-IDF caracteres + LR": so_caracteres,
        "TF-IDF palavras + caracteres + LR (atual)": atual,
        "TF-IDF palavras + MultinomialNB (linha de base)": naive_bayes,
    }


def comparar_abordagens(frases: list[str], intencoes: list[str]) -> list[dict]:
    """Validacao cruzada de cada abordagem, nos mesmos folds."""
    return [
        {"abordagem": nome, **validacao_cruzada(pipeline, frases, intencoes)}
        for nome, pipeline in abordagens().items()
    ]


# --- Limiar de confianca ------------------------------------------------------


def varrer_limiar(modelo, casos: list[dict], base: dict | None = None,
                  limiares=LIMIARES) -> list[dict]:
    """Repete a avaliacao para cada LIMIAR_CONFIANCA (so em memoria)."""
    base = base if base is not None else carregar_base()
    original = modelo_mod.LIMIAR_CONFIANCA
    linhas = []
    try:
        for limiar in limiares:
            modelo_mod.LIMIAR_CONFIANCA = limiar
            resultados = avaliar_casos(modelo, casos, base)
            tipos = Counter(r["tipo_obtido"] for r in resultados)
            linhas.append({
                "limiar": limiar,
                "acertos": sum(r["passou"] for r in resultados),
                "total": len(resultados),
                "fallbacks": tipos["fallback"],
                "abstencoes": tipos["abstencao"],
            })
    finally:
        modelo_mod.LIMIAR_CONFIANCA = original
    return linhas


# --- Vazamento ----------------------------------------------------------------


def verificar_vazamento(casos: list[dict], frases_treino: list[str]) -> list[dict]:
    """Frase de treino mais parecida com cada caso (checar_casos_teste)."""
    similares = checar.medir_similaridade([c["mensagem"] for c in casos], frases_treino)
    return [
        {
            "id": caso["id"],
            "mensagem": caso["mensagem"],
            "frase_treino_mais_parecida": frase,
            "similaridade": valor,
            "acima_do_limite": valor > checar.LIMITE_SIMILARIDADE,
        }
        for caso, (frase, valor) in zip(casos, similares)
    ]


# --- Gravacao -----------------------------------------------------------------


def _gravar_csv(caminho: Path, colunas: list[str], linhas: list[dict]) -> None:
    with open(caminho, "w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=colunas, lineterminator="\n")
        escritor.writeheader()
        for linha in linhas:
            escritor.writerow({
                chave: _num(valor) if isinstance(valor, float) or valor is None
                else ("sim" if valor is True else "nao" if valor is False else valor)
                for chave, valor in linha.items()
            })


def _salvar_figura(figura, caminho: Path) -> None:
    # Sem metadado "Software" para o PNG nao mudar com a versao do matplotlib.
    figura.savefig(caminho, dpi=120, metadata={"Software": None})
    plt.close(figura)


def _estilizar_eixos(eixos) -> None:
    for lado in ("top", "right"):
        eixos.spines[lado].set_visible(False)
    for lado in ("left", "bottom"):
        eixos.spines[lado].set_color(_GRADE)
    eixos.tick_params(colors=_TINTA_SECUNDARIA)


def gravar_matriz_testes(caminho: Path, resultados: list[dict], resumo: dict) -> None:
    """Tabela por categoria, total e lista de falhas em Markdown."""
    por_categoria = resumo["por_categoria"]
    linhas = [
        "# Matriz de testes — avaliação cega da Maresia",
        "",
        f"Data de referência: quarta-feira, 18/11/2026 18:00 ({FUSO_HORARIO}). "
        f"Dataset de treino: {resumo['dataset']['n_frases']} frases.",
        "",
        "| Categoria | Acertos/Total | % |",
        "|---|---|---|",
    ]
    for categoria, valores in por_categoria.items():
        linhas.append(
            f"| {categoria} | {valores['acertos']}/{valores['total']} "
            f"| {_pct(valores['acertos'], valores['total'])} |"
        )
    total = resumo["casos"]
    linhas.append(
        f"| **total** | **{total['acertos']}/{total['total']}** "
        f"| **{_pct(total['acertos'], total['total'])}** |"
    )
    linhas += ["", "## Casos que falharam", ""]
    falhas = [r for r in resultados if not r["passou"]]
    if falhas:
        linhas += ["| Id | Categoria | Mensagem | Motivo |", "|---|---|---|---|"]
        for r in falhas:
            mensagem = r["mensagem"].replace("|", "\\|")
            motivo = r["motivo_falha"].replace("|", "\\|")
            linhas.append(f"| {r['id']} | {r['categoria']} | {mensagem} | {motivo} |")
    else:
        linhas.append("Nenhum caso falhou.")
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8", newline="\n")


def gravar_matriz_confusao(caminho: Path, resultados: list[dict]) -> None:
    """Intencao esperada x obtida nos casos (vazio vira 'nenhuma')."""
    indice = {rotulo: i for i, rotulo in enumerate(ROTULOS_CONFUSAO)}
    matriz = np.zeros((len(ROTULOS_CONFUSAO), len(ROTULOS_CONFUSAO)), dtype=int)
    for r in resultados:
        esperada = r["intencao_esperada"] or SEM_INTENCAO
        obtida = r["intencao_obtida"] or SEM_INTENCAO
        matriz[indice[esperada], indice[obtida]] += 1

    figura, eixos = plt.subplots(figsize=(7.5, 6))
    eixos.imshow(matriz, cmap="Blues", vmin=0, vmax=max(1, matriz.max()))
    limite_escuro = matriz.max() / 2
    for i in range(matriz.shape[0]):
        for j in range(matriz.shape[1]):
            eixos.text(
                j, i, str(matriz[i, j]), ha="center", va="center", fontsize=11,
                color="white" if matriz[i, j] > limite_escuro else _TINTA,
            )
    eixos.set_xticks(range(len(ROTULOS_CONFUSAO)), ROTULOS_CONFUSAO, rotation=30, ha="right")
    eixos.set_yticks(range(len(ROTULOS_CONFUSAO)), ROTULOS_CONFUSAO)
    eixos.set_xlabel("Intenção obtida", color=_TINTA_SECUNDARIA)
    eixos.set_ylabel("Intenção esperada", color=_TINTA_SECUNDARIA)
    eixos.set_title(f"Matriz de confusão — {len(resultados)} casos de teste", color=_TINTA)
    eixos.tick_params(colors=_TINTA_SECUNDARIA, length=0)
    for lado in eixos.spines.values():
        lado.set_visible(False)
    figura.tight_layout()
    _salvar_figura(figura, caminho)


def gravar_grafico_limiar(caminho: Path, linhas: list[dict], limiar_atual: float) -> None:
    """Acertos, fallbacks e abstencoes por limiar, com o limiar atual marcado."""
    limiares = [l["limiar"] for l in linhas]
    figura, eixos = plt.subplots(figsize=(8, 4.8))
    series = [
        ("acertos", "Acertos", _COR_1),
        ("fallbacks", "Fallbacks", _COR_2),
        ("abstencoes", "Abstenções", _COR_3),
    ]
    for chave, nome, cor in series:
        valores = [l[chave] for l in linhas]
        eixos.plot(limiares, valores, color=cor, linewidth=2, marker="o", markersize=6, label=nome)
        eixos.annotate(
            f"{nome}: {valores[-1]}", (limiares[-1], valores[-1]), xytext=(8, 0),
            textcoords="offset points", va="center", color=_TINTA_SECUNDARIA, fontsize=9,
        )
    eixos.axvline(limiar_atual, color=_TINTA_SECUNDARIA, linestyle="--", linewidth=1)
    eixos.annotate(
        f"limiar atual ({limiar_atual:.2f})".replace(".", ","), (limiar_atual, 1),
        xycoords=("data", "axes fraction"), xytext=(4, -4), textcoords="offset points",
        va="top", color=_TINTA_SECUNDARIA, fontsize=9,
    )
    eixos.set_xticks(limiares, [f"{x:.2f}".replace(".", ",") for x in limiares])
    eixos.set_xlim(limiares[0] - 0.02, limiares[-1] + 0.09)
    eixos.set_ylim(0, linhas[0]["total"] + 1)
    eixos.grid(axis="y", color=_GRADE, linewidth=0.8)
    eixos.set_axisbelow(True)
    eixos.set_xlabel("LIMIAR_CONFIANCA", color=_TINTA_SECUNDARIA)
    eixos.set_ylabel(f"Casos (de {linhas[0]['total']})", color=_TINTA_SECUNDARIA)
    eixos.set_title("Efeito do limiar de confiança nos casos de teste", color=_TINTA)
    eixos.legend(frameon=False, loc="center left")
    _estilizar_eixos(eixos)
    figura.tight_layout()
    _salvar_figura(figura, caminho)


def gravar_grafico_abordagens(caminho: Path, linhas: list[dict]) -> None:
    """Barras horizontais de acuracia e F1-macro (media +- desvio)."""
    nomes = [l["abordagem"] for l in linhas]
    posicoes = np.arange(len(nomes))
    altura = 0.36
    figura, eixos = plt.subplots(figsize=(9, 4.8))
    series = [
        ("acuracia", "Acurácia", _COR_1, -altura / 2),
        ("f1_macro", "F1-macro", _COR_2, altura / 2),
    ]
    for chave, nome, cor, deslocamento in series:
        medias = [l[f"{chave}_media"] for l in linhas]
        desvios = [l[f"{chave}_desvio"] for l in linhas]
        eixos.barh(
            posicoes + deslocamento, medias, height=altura - 0.04, xerr=desvios, color=cor,
            label=nome, error_kw={"ecolor": _TINTA_SECUNDARIA, "elinewidth": 1, "capsize": 3},
        )
        for y, media, desvio in zip(posicoes + deslocamento, medias, desvios):
            eixos.text(
                media + desvio + 0.01, y, f"{media:.3f}".replace(".", ","),
                va="center", fontsize=8, color=_TINTA_SECUNDARIA,
            )
    eixos.set_yticks(posicoes, nomes)
    eixos.invert_yaxis()
    marcas = [0, 0.2, 0.4, 0.6, 0.8, 1.0]
    eixos.set_xticks(marcas, [f"{x:.1f}".replace(".", ",") for x in marcas])
    eixos.set_xlim(0, 1.12)
    eixos.grid(axis="x", color=_GRADE, linewidth=0.8)
    eixos.set_axisbelow(True)
    eixos.set_xlabel(f"Validação cruzada estratificada ({FOLDS_VALIDACAO} folds)",
                     color=_TINTA_SECUNDARIA)
    eixos.set_title("Comparação de abordagens (média ± desvio)", color=_TINTA)
    eixos.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=2)
    _estilizar_eixos(eixos)
    figura.tight_layout()
    _salvar_figura(figura, caminho)


# --- Orquestracao -------------------------------------------------------------


def gerar_resultados(caminho_modelo=ARQUIVO_MODELO, pasta_saida=PASTA_RESULTADOS,
                     caminho_dataset=CAMINHO_DATASET, caminho_casos=checar.CAMINHO_CASOS) -> dict:
    """Roda toda a avaliacao, grava os arquivos e devolve o resumo."""
    modelo = modelo_mod.carregar_modelo(caminho_modelo)
    pasta = Path(pasta_saida)
    pasta.mkdir(parents=True, exist_ok=True)
    _, casos = checar.ler_casos(caminho_casos)
    frases, intencoes = modelo_mod.carregar_dataset(caminho_dataset)
    base = carregar_base()

    resultados = avaliar_casos(modelo, casos, base)
    por_categoria = resumir_por_categoria(resultados)
    comparacao = comparar_abordagens(frases, intencoes)
    atual = next(l for l in comparacao if l["abordagem"].endswith("(atual)"))
    limiar = varrer_limiar(modelo, casos, base)
    vazamento = verificar_vazamento(casos, frases)

    acertos = sum(r["passou"] for r in resultados)
    resumo = {
        "casos": {
            "acertos": acertos,
            "total": len(resultados),
            "percentual": round(100 * acertos / len(resultados), 1),
        },
        "por_categoria": {
            c: {**v, "percentual": round(100 * v["acertos"] / v["total"], 1)}
            for c, v in por_categoria.items()
        },
        "validacao_cruzada": {
            "folds": FOLDS_VALIDACAO,
            "semente": SEMENTE,
            **{chave: round(valor, 4) for chave, valor in atual.items() if chave != "abordagem"},
        },
        "data_referencia": AGORA_REFERENCIA.isoformat(),
        "limiar_confianca": modelo_mod.LIMIAR_CONFIANCA,
        "dataset": {"arquivo": Path(caminho_dataset).name, "n_frases": len(frases)},
    }

    _gravar_csv(pasta / "resultados_casos.csv", COLUNAS_CASOS, resultados)
    gravar_matriz_testes(pasta / "matriz_testes.md", resultados, resumo)
    (pasta / "resumo_metricas.json").write_text(
        json.dumps(resumo, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    gravar_matriz_confusao(pasta / "matriz_confusao.png", resultados)
    _gravar_csv(pasta / "limiar_confianca.csv", list(limiar[0]), limiar)
    gravar_grafico_limiar(pasta / "limiar_confianca.png", limiar, modelo_mod.LIMIAR_CONFIANCA)
    _gravar_csv(pasta / "comparacao_abordagens.csv", list(comparacao[0]), comparacao)
    gravar_grafico_abordagens(pasta / "comparacao_abordagens.png", comparacao)
    _gravar_csv(pasta / "verificacao_vazamento.csv", list(vazamento[0]), vazamento)
    return resumo


def formatar_tabela(resumo: dict) -> str:
    """Tabela por categoria e total para o terminal."""
    linhas = [f"{'Categoria':<16} {'Resultado':>16}", "-" * 33]
    for categoria, valores in resumo["por_categoria"].items():
        linhas.append(f"{categoria:<16} {_placar(valores['acertos'], valores['total']):>16}")
    linhas.append("-" * 33)
    total = resumo["casos"]
    linhas.append(f"{'total':<16} {_placar(total['acertos'], total['total']):>16}")
    return "\n".join(linhas)


def main(caminho_modelo=ARQUIVO_MODELO, pasta_saida=PASTA_RESULTADOS) -> int:
    if not Path(caminho_modelo).exists():
        print(f"Modelo nao encontrado em '{caminho_modelo}'. Rode antes: python treinar.py")
        return 1
    resumo = gerar_resultados(caminho_modelo, pasta_saida)
    vc = resumo["validacao_cruzada"]
    print("Avaliacao cega dos casos de teste (agora = qua 18/11/2026 18:00)")
    print()
    print(formatar_tabela(resumo))
    print()
    print(
        f"Validacao cruzada ({vc['folds']} folds): acuracia "
        f"{vc['acuracia_media']:.3f} ± {vc['acuracia_desvio']:.3f}, "
        f"F1-macro {vc['f1_macro_media']:.3f}".replace(".", ",")
    )
    print(f"Resultados gravados em: {pasta_saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
