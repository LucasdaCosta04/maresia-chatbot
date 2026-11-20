"""Gera as capturas de tela da interface da Maresia em docs/.

Uso (na raiz do repositório):
    pip install -r requirements.txt -r requirements-dev.txt
    python -m playwright install chromium
    python docs/capturar_telas.py              # sobe um servidor próprio, reproduzível
    python docs/capturar_telas.py --conectar   # usa o servidor já rodando em --url

Capturas geradas:
    docs/tela_contexto.png      desktop: herança de contexto + painel aberto
    docs/tela_dois_pedidos.png  desktop: dois pedidos na mesma mensagem (esclarecimento)
    docs/tela_celular.png       390x844: conversa e gaveta do painel, lado a lado

Reprodutibilidade: sem --conectar, o script sobe o Flask em segundo plano
com a data fixa em DATA_FIXA (as datas relativas, como "sábado", saem
sempre iguais) e com as variações de resposta sorteadas por uma semente
fixa. Se a porta já estiver ocupada por uma Maresia, o script se conecta a
ela (nesse caso as respostas dependem do relógio real do servidor).

O script também confere, a cada captura, que a página não tem rolagem
horizontal nem vertical e que o painel não exibe "undefined" nem "NaN";
se algo falhar, termina com erro.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import random
import sys
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parent.parent
PASTA_DOCS = RAIZ / "docs"
URL_PADRAO = "http://127.0.0.1:5000"

# Quarta-feira, 18/11/2026, 18:00: "sábado" = 21/11 e "domingo" = 22/11.
DATA_FIXA = datetime(2026, 11, 18, 18, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
SEMENTE = 42

VIEWPORT_DESKTOP = {"width": 1440, "height": 900}
VIEWPORT_CELULAR = {"width": 390, "height": 844}
ESCALA_CELULAR = 2  # device pixel ratio de um celular comum
TEMPO_LIMITE_MS = 20_000


# --- Servidor -------------------------------------------------------------------

def _servidor_no_ar(url: str) -> bool:
    """True se GET /api/saude responde como a Maresia com o modelo carregado."""
    try:
        with urllib.request.urlopen(url + "/api/saude", timeout=2) as resposta:
            dados = json.load(resposta)
    except (urllib.error.URLError, OSError, ValueError):
        return False
    return dados.get("status") == "ok" and bool(dados.get("modelo_carregado"))


def _criar_app_reproduzivel():
    """create_app() com data fixa e sorteio de respostas com semente fixa.

    chatbot.dialogo cria um random.Random() sem semente para sortear as
    variações das respostas; aqui o módulo enxerga um random cujo Random()
    já vem semeado. O arquivo chatbot/dialogo.py não é alterado.
    """
    sys.path.insert(0, str(RAIZ))
    import chatbot.dialogo as dialogo
    from app import create_app

    dialogo.random = SimpleNamespace(Random=lambda *args: random.Random(SEMENTE))
    return create_app(agora=lambda: DATA_FIXA)


@contextmanager
def servidor(url: str, conectar: bool):
    """Garante um servidor em `url` durante o bloco with.

    Se já houver uma Maresia no ar, apenas se conecta. Senão (e sem
    --conectar), sobe uma em uma thread e a encerra no final.
    """
    if _servidor_no_ar(url):
        print(f"Conectado ao servidor já em execução em {url}.")
        yield
        return
    if conectar:
        raise SystemExit(
            f"Nenhuma Maresia com modelo carregado respondeu em {url}. "
            "Inicie com 'python app.py' ou rode sem --conectar."
        )

    from werkzeug.serving import make_server

    logging.getLogger("werkzeug").setLevel(logging.WARNING)  # sem log por requisição
    partes = urlsplit(url)
    app = _criar_app_reproduzivel()
    try:
        http = make_server(partes.hostname, partes.port or 80, app, threaded=True)
    except OSError as erro:
        raise SystemExit(f"Não foi possível usar {url}: {erro}") from erro

    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    print(f"Servidor próprio iniciado em {url} (data fixa {DATA_FIXA:%d/%m/%Y %H:%M}).")
    try:
        if not _servidor_no_ar(url):
            raise SystemExit("O servidor subiu, mas o modelo não foi carregado. Rode: python treinar.py")
        yield
    finally:
        http.shutdown()
        thread.join(timeout=5)
        print("Servidor próprio encerrado.")


# --- Interações com a página -----------------------------------------------------

def abrir_conversa(navegador, url: str, viewport: dict, celular: bool = False):
    """Nova aba (sessão nova) com a conversa pronta para receber mensagens."""
    contexto = navegador.new_context(
        viewport=viewport,
        device_scale_factor=ESCALA_CELULAR if celular else 1,
        is_mobile=celular,
        has_touch=celular,
        locale="pt-BR",
        timezone_id="America/Sao_Paulo",
        reduced_motion="reduce",  # sem animações: capturas estáveis
    )
    pagina = contexto.new_page()
    pagina.set_default_timeout(TEMPO_LIMITE_MS)
    pagina.goto(url + "/", wait_until="load")
    pagina.wait_for_selector('#status[data-estado="ok"]')
    pagina.wait_for_selector(".mensagem--bot")  # saudação
    pagina.evaluate("document.fonts.ready")
    return contexto, pagina


def enviar(pagina, texto: str) -> None:
    """Digita e envia uma mensagem e espera a resposta da Maresia."""
    respostas_antes = pagina.locator(".mensagem--bot:not(.digitando)").count()
    pagina.fill("#campo-mensagem", texto)
    pagina.press("#campo-mensagem", "Enter")
    pagina.wait_for_function(
        "n => document.querySelectorAll('.mensagem--bot:not(.digitando)').length > n"
        " && !document.querySelector('.digitando')",
        arg=respostas_antes,
    )
    pagina.wait_for_selector('#status[data-estado="ok"]')
    erro = pagina.locator(".mensagem--erro")
    if erro.count():
        raise RuntimeError(f"A interface mostrou um erro: {erro.last.inner_text()}")


def conferir_layout(pagina, nome: str) -> None:
    """Falha se a janela rolar ou se o painel mostrar 'undefined'/'NaN'."""
    medidas = pagina.evaluate(
        """() => ({
            largura: document.documentElement.scrollWidth,
            janela: document.documentElement.clientWidth,
            altura: document.documentElement.scrollHeight,
            alturaJanela: document.documentElement.clientHeight,
            painel: document.getElementById('painel').innerText,
        })"""
    )
    problemas = []
    if medidas["largura"] > medidas["janela"]:
        problemas.append(f"rolagem horizontal ({medidas['largura']} > {medidas['janela']}px)")
    if medidas["altura"] > medidas["alturaJanela"]:
        problemas.append(f"rolagem vertical ({medidas['altura']} > {medidas['alturaJanela']}px)")
    for termo in ("undefined", "NaN"):
        if termo in medidas["painel"]:
            problemas.append(f"painel exibe '{termo}'")
    if problemas:
        raise RuntimeError(f"{nome}: " + "; ".join(problemas))


def foto(pagina, nome: str) -> bytes:
    """Confere o layout, leva a conversa até o fim e devolve o PNG da tela."""
    conferir_layout(pagina, nome)
    pagina.locator("#mensagens").evaluate("lista => { lista.scrollTop = lista.scrollHeight; }")
    return pagina.screenshot(animations="disabled", caret="hide")


def gravar(png: bytes, nome: str) -> None:
    caminho = PASTA_DOCS / nome
    caminho.write_bytes(png)
    print(f"  salvo: {caminho.relative_to(RAIZ).as_posix()}")


def painel_aberto(pagina, mostrar_decisao: bool = True) -> None:
    """Abre o painel (se estiver fechado), espera as etapas e, se pedido,
    rola o painel até a etapa "Decisão" (só o painel rola, não a janela)."""
    if pagina.get_attribute("#botao-painel", "aria-expanded") != "true":
        pagina.click("#botao-painel")
    pagina.wait_for_selector("#painel.painel--aberto #etapas:not([hidden])")
    if mostrar_decisao:
        pagina.evaluate(
            """() => {
                const painel = document.getElementById('painel');
                const etapa = document.getElementById('etapa-decisao').closest('.etapa');
                painel.scrollTop = etapa.offsetTop - painel.clientHeight / 2 + etapa.offsetHeight / 2;
            }"""
        )


def lado_a_lado(navegador, imagens: list[bytes], viewport: dict, escala: int) -> bytes:
    """Junta capturas do mesmo tamanho numa única imagem, lado a lado."""
    margem, espaco = 24, 24
    largura = viewport["width"] * len(imagens) + espaco * (len(imagens) - 1) + 2 * margem
    altura = viewport["height"] + 2 * margem
    contexto = navegador.new_context(
        viewport={"width": largura, "height": altura}, device_scale_factor=escala
    )
    try:
        pagina = contexto.new_page()
        figuras = "".join(
            f'<img src="data:image/png;base64,{base64.b64encode(png).decode()}" '
            f'width="{viewport["width"]}" height="{viewport["height"]}">'
            for png in imagens
        )
        pagina.set_content(
            f"""<!doctype html><html><body style="margin:0;padding:{margem}px;display:flex;
            gap:{espaco}px;background:#e2e8f0">{figuras}</body></html>""",
            wait_until="load",
        )
        pagina.add_style_tag(content="img{border-radius:18px;box-shadow:0 8px 24px rgba(15,23,42,.18)}")
        return pagina.screenshot()
    finally:
        contexto.close()


# --- Cenários --------------------------------------------------------------------

def capturar_contexto(navegador, url: str) -> None:
    contexto, pagina = abrir_conversa(navegador, url, VIEWPORT_DESKTOP)
    try:
        enviar(pagina, "Que horas vocês abrem no sábado?")
        enviar(pagina, "E no domingo?")  # herda o assunto "horário"
        painel_aberto(pagina)  # emblema "Usou o contexto"
        gravar(foto(pagina, "tela_contexto.png"), "tela_contexto.png")
    finally:
        contexto.close()


def capturar_dois_pedidos(navegador, url: str) -> None:
    contexto, pagina = abrir_conversa(navegador, url, VIEWPORT_DESKTOP)
    try:
        enviar(pagina, "Quero reservar uma mesa e também saber se a moqueca tem camarão")
        painel_aberto(pagina)  # emblema "Pediu esclarecimento"
        gravar(foto(pagina, "tela_dois_pedidos.png"), "tela_dois_pedidos.png")
    finally:
        contexto.close()


def capturar_celular(navegador, url: str) -> None:
    """Duas telas de 390x844 lado a lado: a conversa e a gaveta do painel aberta."""
    contexto, pagina = abrir_conversa(navegador, url, VIEWPORT_CELULAR, celular=True)
    try:
        enviar(pagina, "Quero reservar mesa p/ 4 no sábado às 20h")
        conversa = foto(pagina, "tela_celular.png (conversa)")
        painel_aberto(pagina, mostrar_decisao=False)  # no celular, o painel é uma gaveta
        gaveta = foto(pagina, "tela_celular.png (gaveta)")
    finally:
        contexto.close()
    gravar(lado_a_lado(navegador, [conversa, gaveta], VIEWPORT_CELULAR, ESCALA_CELULAR), "tela_celular.png")


# --- Entrada ---------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=URL_PADRAO, help=f"endereço do servidor (padrão: {URL_PADRAO})")
    parser.add_argument(
        "--conectar", action="store_true",
        help="só se conecta a um servidor já em execução (não sobe um próprio)",
    )
    args = parser.parse_args()
    url = args.url.rstrip("/")

    try:
        from playwright.sync_api import Error as ErroPlaywright
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright não instalado. Rode: pip install -r requirements-dev.txt", file=sys.stderr)
        return 1

    PASTA_DOCS.mkdir(exist_ok=True)
    with servidor(url, args.conectar), sync_playwright() as p:
        try:
            navegador = p.chromium.launch(headless=True)
        except ErroPlaywright as erro:
            print(
                f"Não foi possível abrir o Chromium: {erro}\n"
                "Rode: python -m playwright install chromium",
                file=sys.stderr,
            )
            return 1
        try:
            print("Gerando capturas…")
            capturar_contexto(navegador, url)
            capturar_dois_pedidos(navegador, url)
            capturar_celular(navegador, url)
        finally:
            navegador.close()
    print("Pronto.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
