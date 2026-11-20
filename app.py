"""Servidor Flask da Maresia: API de conversa (e, depois, a interface web).

Uso:
    python app.py              # http://127.0.0.1:5000
    FLASK_DEBUG=1 python app.py  # com modo debug

Rotas:
    POST /api/mensagem   {"mensagem": "...", "sessao": "..."}  (alias: /api/chat)
    POST /api/reiniciar  {"sessao": "..."}
    GET  /api/saude
    GET  /

As sessoes ficam em memoria (um EstadoConversa por id), protegidas por um
Lock. Elas se perdem quando o servidor reinicia.
"""

import os
import threading
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from chatbot.config import (
    ARQUIVO_MODELO,
    C_REGULARIZACAO,
    LIMIAR_CONFIANCA,
    MARGEM_MINIMA,
    MAX_CARACTERES_MENSAGEM,
    NGRAM_CARACTERES,
    NGRAM_PALAVRAS,
)
from chatbot.dialogo import (
    EstadoConversa,
    GerenciadorDialogo,
    carregar_base,
    mensagem_boas_vindas,
)
from chatbot.entidades import extrair_entidades
from chatbot.modelo import carregar_modelo
from chatbot.preprocessamento import preprocessar

# Quantas intencoes mostrar em "alternativas" (como no exemplo do README).
N_ALTERNATIVAS = 3

ROTAS_API = [
    "POST /api/mensagem  (alias: POST /api/chat)",
    "POST /api/reiniciar",
    "GET  /api/saude",
]

MSG_SEM_MODELO = (
    "O modelo de intenções ainda não foi treinado. "
    "Rode \"python treinar.py\" e reinicie o servidor."
)


def _erro(mensagem: str, status: int):
    """Resposta de erro padronizada em JSON."""
    return jsonify({"erro": mensagem, "status": status}), status


def _arredondar(valor: float | None) -> float | None:
    """Arredonda probabilidades para 4 casas (ou mantem None)."""
    return None if valor is None else round(valor, 4)


def _alternativas_e_margem(probabilidades: dict[str, float]) -> tuple[list, float | None]:
    """Top-N intencoes do classificador e a margem entre a 1a e a 2a."""
    ordenadas = sorted(probabilidades.items(), key=lambda item: item[1], reverse=True)
    alternativas = [
        {"intencao": intencao, "probabilidade": _arredondar(prob)}
        for intencao, prob in ordenadas[:N_ALTERNATIVAS]
    ]
    margem = ordenadas[0][1] - ordenadas[1][1] if len(ordenadas) >= 2 else None
    return alternativas, _arredondar(margem)


def _metadados_modelo(modelo) -> dict:
    """Descricao do classificador para o painel (sem depender do objeto treinado)."""
    classes = getattr(modelo, "classes_", None) if modelo is not None else None
    return {
        "carregado": modelo is not None,
        "tipo": "TF-IDF (palavras + caracteres) + Regressão Logística",
        "arquivo": ARQUIVO_MODELO.name,
        "intencoes": [str(c) for c in classes] if classes is not None else [],
        "ngram_palavras": list(NGRAM_PALAVRAS),
        "ngram_caracteres": list(NGRAM_CARACTERES),
        "c_regularizacao": C_REGULARIZACAO,
        "limiar": LIMIAR_CONFIANCA,
        "margem_minima": MARGEM_MINIMA,
    }


def _contexto(estado: EstadoConversa, herdou_contexto: bool) -> dict:
    """O que a sessao lembra depois da resposta (para a etapa 5 do painel)."""
    return {
        "assunto": estado.assunto_anterior,
        "etapa_reserva": estado.etapa_reserva,
        "slots": dict(estado.slots),
        "esclarecimento": list(estado.esclarecimento) if estado.esclarecimento else None,
        "ultimo_prato": estado.ultimo_prato,
        "ultima_data": estado.ultima_data,
        "data_solta": dict(estado.data_solta) if estado.data_solta else None,
        "falhas_seguidas": estado.falhas_seguidas,
        "encaminhado": estado.encaminhado,
        "herdou_contexto": herdou_contexto,
    }


def create_app(modelo=None, agora=None) -> Flask:
    """Cria a aplicacao Flask.

    modelo: pipeline treinado; se None, carrega de modelos/ com
    carregar_modelo(). Se o arquivo nao existir, a aplicacao sobe mesmo
    assim e as rotas de mensagem respondem 503.
    agora: funcao que devolve o datetime atual, repassada ao
    GerenciadorDialogo (usada nos testes).
    """
    app = Flask(__name__)
    app.json.ensure_ascii = False  # acentos legiveis no JSON

    if modelo is None:
        try:
            modelo = carregar_modelo()
        except FileNotFoundError as erro:
            app.logger.warning("%s", erro)
            modelo = None

    base = carregar_base()
    gerente = GerenciadorDialogo(modelo, base, agora=agora) if modelo is not None else None
    boas_vindas = mensagem_boas_vindas(base)
    metadados = _metadados_modelo(modelo)

    # Sessoes em memoria: {id_sessao: EstadoConversa}. O Lock protege o dict
    # e tambem o processamento de cada mensagem, porque o GerenciadorDialogo
    # altera o EstadoConversa (duas requisicoes da mesma sessao ao mesmo
    # tempo nao podem se misturar).
    sessoes: dict[str, EstadoConversa] = {}
    trava = threading.Lock()

    def _sessao(id_recebido) -> tuple[str, EstadoConversa]:
        """Devolve (id, estado) da sessao; cria uma nova se o id for ausente
        ou desconhecido. Chamar com a trava adquirida."""
        if isinstance(id_recebido, str) and id_recebido in sessoes:
            return id_recebido, sessoes[id_recebido]
        novo_id = str(uuid.uuid4())
        sessoes[novo_id] = EstadoConversa()
        return novo_id, sessoes[novo_id]

    def _corpo_json() -> dict | None:
        """Corpo da requisicao como dict, ou None se nao for um objeto JSON valido."""
        corpo = request.get_json(silent=True)
        return corpo if isinstance(corpo, dict) else None

    # --- Rotas ----------------------------------------------------------------

    @app.post("/api/mensagem")
    @app.post("/api/chat")
    def mensagem():
        """Recebe uma mensagem e devolve a resposta da Maresia."""
        corpo = _corpo_json()
        if corpo is None:
            return _erro("Corpo inválido: envie um JSON como {\"mensagem\": \"...\"}.", 400)
        texto = corpo.get("mensagem")
        if not isinstance(texto, str) or not texto.strip():
            return _erro("O campo \"mensagem\" é obrigatório e não pode estar vazio.", 400)
        texto = texto.strip()
        if len(texto) > MAX_CARACTERES_MENSAGEM:
            return _erro(
                f"A mensagem pode ter no máximo {MAX_CARACTERES_MENSAGEM} caracteres.", 400
            )
        if gerente is None:
            return _erro(MSG_SEM_MODELO, 503)

        with trava:
            id_sessao, estado = _sessao(corpo.get("sessao"))
            resposta = gerente.responder(texto, estado)
            alternativas, margem = _alternativas_e_margem(resposta.probabilidades)
            texto_normalizado = preprocessar(texto)
            try:
                entidades = extrair_entidades(texto, gerente.agora())
            except Exception:  # o painel e opcional: nunca derruba a resposta
                app.logger.exception("Falha ao extrair entidades para o painel")
                entidades = {}
            probabilidades = {
                intencao: _arredondar(prob)
                for intencao, prob in sorted(
                    resposta.probabilidades.items(), key=lambda item: item[1], reverse=True
                )
            }
            return jsonify({
                "resposta": resposta.texto,
                "intencao": resposta.intencao,
                "tipo": resposta.tipo,
                "confianca": _arredondar(resposta.confianca),
                "margem": margem,
                "alternativas": alternativas,
                "herdou_contexto": resposta.herdou_contexto,
                "encaminhado": estado.encaminhado,
                "falhas_seguidas": estado.falhas_seguidas,
                "sessao": id_sessao,
                # Aliases com os nomes documentados no README.
                "decisao": resposta.tipo,
                "encaminhar_humano": estado.encaminhado,
                # Campos do painel "Como a Maresia entendeu".
                "texto_original": texto,
                "texto_normalizado": texto_normalizado,
                "tokens": texto_normalizado.split(),
                "entidades": entidades,
                "limiar": LIMIAR_CONFIANCA,
                "margem_minima": MARGEM_MINIMA,
                "probabilidades": probabilidades,
                "contexto": _contexto(estado, resposta.herdou_contexto),
                "modelo": metadados,
            })

    @app.post("/api/reiniciar")
    def reiniciar():
        """Limpa o estado da sessao (ou cria uma nova) e da as boas-vindas."""
        corpo = _corpo_json() or {}
        with trava:
            id_sessao, estado = _sessao(corpo.get("sessao"))
            estado.reiniciar()
        return jsonify({"sessao": id_sessao, "resposta": boas_vindas})

    @app.get("/api/saude")
    def saude():
        """Verificacao de saude: servidor no ar, modelo carregado e sessoes."""
        with trava:
            n_sessoes = len(sessoes)
        return jsonify({
            "status": "ok",
            "modelo_carregado": gerente is not None,
            "sessoes_ativas": n_sessoes,
            "limiar": LIMIAR_CONFIANCA,
            "margem_minima": MARGEM_MINIMA,
            "modelo": metadados,
        })

    @app.get("/")
    def inicio():
        """Interface web, se ja existir; senao, um texto com as rotas da API."""
        if Path(app.root_path, app.template_folder, "index.html").exists():
            return render_template("index.html")
        texto = (
            "Maresia: a interface web ainda não foi criada.\n\n"
            "Rotas da API:\n" + "\n".join(f"  {rota}" for rota in ROTAS_API) + "\n"
        )
        return texto, 200, {"Content-Type": "text/plain; charset=utf-8"}

    # --- Erros em JSON ----------------------------------------------------------

    @app.errorhandler(404)
    def nao_encontrado(_erro_http):
        return _erro("Rota não encontrada.", 404)

    @app.errorhandler(405)
    def metodo_nao_permitido(_erro_http):
        return _erro("Método não permitido para esta rota.", 405)

    @app.errorhandler(HTTPException)
    def erro_http(erro_http: HTTPException):
        return _erro(erro_http.description or erro_http.name, erro_http.code or 500)

    @app.errorhandler(Exception)
    def erro_interno(erro: Exception):
        app.logger.exception("Erro inesperado: %s", erro)
        return _erro("Erro interno no servidor.", 500)

    return app


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0").lower() in ("1", "true", "sim", "on")
    create_app().run(host="127.0.0.1", port=5000, debug=debug)
