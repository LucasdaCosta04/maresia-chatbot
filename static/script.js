"use strict";

/* ==========================================================================
   Maresia | Tempero Açoriano: interface de conversa
   ========================================================================== */

/* ---------- Rotas da API (app.py) ---------- */
const API = {
  chat: "/api/chat",
  reiniciar: "/api/reiniciar",
  saude: "/api/saude",
};

/* ---------- Textos e rótulos ---------- */

// Nomes legíveis das intenções do classificador (dados/intencoes_treino.csv).
const ROTULOS_INTENCAO = {
  cardapio_alergenicos: "Cardápio e alergênicos",
  reserva: "Reservas",
  horario_localizacao: "Horário e localização",
  fora_escopo: "Fora do escopo",
};

// Campo "tipo" da resposta → como mostrar a decisão no painel.
// "tom" é o data-tom do emblema .decisao (verde, ocre, tijolo ou ardosia).
const DECISOES = {
  aceita: {
    rotulo: "Respondeu",
    tom: "verde",
    descricao: "O modelo estava confiante e a intenção mais provável se destacou da segunda.",
  },
  esclarecimento: {
    rotulo: "Pediu esclarecimento",
    tom: "ocre",
    descricao: "A mensagem ficou entre dois assuntos ou faltou informação, então a Maresia perguntou.",
  },
  abstencao: {
    rotulo: "Fora do escopo",
    tom: "ardosia",
    descricao: "O assunto não é do restaurante, então a Maresia recusou com educação.",
  },
  fallback: {
    rotulo: "Não entendeu",
    tom: "tijolo",
    descricao: "Nenhuma intenção se destacou e a Maresia sugeriu os assuntos que conhece.",
  },
  regra: {
    rotulo: "Regra prioritária",
    tom: "verde",
    descricao: "Saudação, despedida, cancelamento ou ajuda: resolvido antes do classificador.",
  },
  reserva: {
    rotulo: "Fluxo de reserva",
    tom: "verde",
    descricao: "Mensagem tratada como um passo da reserva em andamento.",
  },
  encaminhamento: {
    rotulo: "Encaminhou a um atendente",
    tom: "tijolo",
    descricao: "Pedido do cliente ou falhas seguidas: a conversa foi passada para uma pessoa.",
  },
};

// Qual camada do diálogo produziu a resposta, a partir do "tipo".
const CAMADAS = {
  regra: "Regras prioritárias",
  reserva: "Fluxo de reserva (slots)",
  encaminhamento: "Encaminhamento humano",
  aceita: "Classificador de intenções",
  esclarecimento: "Classificador de intenções",
  abstencao: "Classificador de intenções",
  fallback: "Classificador de intenções",
};

// Chaves de extrair_entidades() (chatbot/entidades.py) → rótulo no painel.
const NOMES_ENTIDADES = {
  pratos: "Pratos",
  pratos_ambiguos: "Pratos (ambíguos)",
  alergenicos: "Alergênicos",
  restricoes: "Restrições",
  pessoas: "Pessoas",
  data: "Data",
  dia_semana: "Dia da semana",
  horario: "Horário",
  horario_ambiguo: "Horário (ambíguo)",
  periodo: "Período",
  nome: "Nome",
};

// Ícones SVG em linha (herdam a cor do texto com currentColor).
const ICONES = {
  enviar:
    '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">' +
    '<path d="M3 11.5 20 4l-7.5 17-2.2-7.3L3 11.5Z" fill="none" stroke="currentColor" ' +
    'stroke-width="2" stroke-linejoin="round"/></svg>',
  reiniciar:
    '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">' +
    '<path d="M4 12a8 8 0 1 0 2.4-5.7M4 4v4h4" fill="none" stroke="currentColor" ' +
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  painel:
    '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">' +
    '<path d="M4 19V11M10 19V5M16 19v-6M22 19H2" fill="none" stroke="currentColor" ' +
    'stroke-width="2" stroke-linecap="round"/></svg>',
  erro:
    '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false">' +
    '<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/>' +
    '<path d="M12 7v6M12 16.5v.5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
};

/* ---------- Elementos da página ---------- */
const el = {
  status: document.getElementById("status"),
  botaoReiniciar: document.getElementById("botao-reiniciar"),
  botaoPainel: document.getElementById("botao-painel"),
  mensagens: document.getElementById("mensagens"),
  sugestoes: document.getElementById("sugestoes"),
  formulario: document.getElementById("formulario"),
  campo: document.getElementById("campo-mensagem"),
  botaoEnviar: document.getElementById("botao-enviar"),
  painel: document.getElementById("painel"),
  botaoFecharPainel: document.getElementById("botao-fechar-painel"),
  painelVazio: document.getElementById("painel-vazio"),
  etapas: document.getElementById("etapas"),
  etapaPreprocessamento: document.getElementById("etapa-preprocessamento"),
  etapaProbabilidades: document.getElementById("etapa-probabilidades"),
  etapaEntidades: document.getElementById("etapa-entidades"),
  etapaDecisao: document.getElementById("etapa-decisao"),
  etapaContexto: document.getElementById("etapa-contexto"),
  infoModelo: document.getElementById("info-modelo"),
  veu: document.getElementById("veu"),
};

/* ---------- Estado ---------- */
const estado = {
  sessaoId: null,   // id devolvido pelo servidor (ou gerado aqui até lá)
  enviando: false,  // trava envios enquanto espera a resposta
  boasVindas: "",   // texto de /api/reiniciar, reaproveitado ao reiniciar
  sugestoesIniciais: [
    "Qual o horário de funcionamento?",
    "Quero reservar uma mesa",
    "A moqueca leva camarão?",
    "Vocês têm opção sem glúten?",
  ],
};

/* ---------- Utilitários ---------- */

/** Id de sessão aleatório; o servidor troca por um próprio se não o conhecer. */
function novoIdSessao() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID();
  }
  return "sessao-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
}

/** Escapa &, <, >, " e ' para inserir texto com segurança em innerHTML. */
function escaparHtml(texto) {
  return String(texto ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * Converte o texto da Maresia em HTML seguro:
 * - **negrito** → <strong>;
 * - linha em branco → novo parágrafo; quebra simples → <br>.
 * O texto é escapado antes, então nenhum HTML vindo do servidor é executado.
 */
function formatarResposta(texto) {
  const normalizado = String(texto ?? "").replace(/\r\n?/g, "\n").trim();
  if (!normalizado) return "";

  return normalizado
    .split(/\n{2,}/)
    .map((paragrafo) => {
      const html = escaparHtml(paragrafo)
        .replace(/\*\*(.+?)\*\*/gs, "<strong>$1</strong>")
        .replace(/\n/g, "<br>");
      return "<p>" + html + "</p>";
    })
    .join("");
}

/* ---------- Mensagens ---------- */

/**
 * Adiciona uma mensagem à conversa e devolve o <li> criado.
 * autor: "bot", "usuario" ou "erro".
 * Mensagens do usuário entram como texto puro; as da Maresia passam por
 * formatarResposta().
 */
function adicionarMensagem(texto, autor = "bot") {
  const item = document.createElement("li");
  item.className = "mensagem mensagem--" + autor;

  const balao = document.createElement("div");
  balao.className = "balao";

  if (autor === "usuario") {
    balao.textContent = texto;
  } else if (autor === "erro") {
    balao.innerHTML = ICONES.erro + " " + formatarResposta(texto);
  } else {
    balao.innerHTML = formatarResposta(texto);
  }

  item.appendChild(balao);
  el.mensagens.appendChild(item);
  rolarParaFim();
  return item;
}

/** Leva a lista de mensagens até a última. */
function rolarParaFim() {
  requestAnimationFrame(() => {
    el.mensagens.scrollTop = el.mensagens.scrollHeight;
  });
}

/**
 * Mostra (ou remove) o indicador "digitando…".
 * Devolve o <li> do indicador quando mostrado.
 */
function mostrarDigitando(ativo = true) {
  const atual = el.mensagens.querySelector(".digitando");
  if (!ativo) {
    if (atual) atual.remove();
    return null;
  }
  if (atual) return atual;

  const item = document.createElement("li");
  item.className = "mensagem mensagem--bot digitando";
  item.setAttribute("aria-label", "Maresia está digitando");
  item.innerHTML =
    '<div class="balao"><span class="ponto"></span><span class="ponto"></span><span class="ponto"></span></div>';

  el.mensagens.appendChild(item);
  rolarParaFim();
  return item;
}

/**
 * Troca as pílulas de sugestão. Uma lista vazia limpa a área
 * (o CSS esconde #sugestoes vazio). Clicar numa pílula envia o texto dela.
 */
function mostrarSugestoes(lista = []) {
  el.sugestoes.replaceChildren();

  for (const texto of lista) {
    const botao = document.createElement("button");
    botao.type = "button";
    botao.className = "sugestao";
    botao.textContent = texto;
    botao.addEventListener("click", () => {
      if (estado.enviando) return;
      el.campo.value = texto;
      el.formulario.requestSubmit();
    });
    el.sugestoes.appendChild(botao);
  }
}

/* ---------- Comunicação com a API ---------- */

// Tempo máximo de espera por uma resposta do servidor.
const TEMPO_LIMITE_MS = 15000;

/** Erro de requisição com um texto pronto para mostrar ao cliente. */
class ErroApi extends Error {
  constructor(mensagem, { status = 0, offline = false } = {}) {
    super(mensagem);
    this.name = "ErroApi";
    this.status = status;   // código HTTP (0 quando nem chegou ao servidor)
    this.offline = offline; // sem rede, servidor fora do ar ou tempo esgotado
  }
}

/**
 * fetch() + JSON com tempo limite. Devolve o corpo já convertido ou lança
 * ErroApi: offline (rede, servidor ou tempo) ou HTTP (usa o campo "erro" do JSON).
 */
async function requisitarJson(url, { metodo = "GET", corpo } = {}) {
  if (!navigator.onLine) {
    throw new ErroApi("Você está sem conexão com a internet. Verifique a rede e tente de novo.", {
      offline: true,
    });
  }

  const controle = new AbortController();
  const temporizador = setTimeout(() => controle.abort(), TEMPO_LIMITE_MS);

  let resposta;
  try {
    resposta = await fetch(url, {
      method: metodo,
      headers: corpo === undefined ? {} : { "Content-Type": "application/json" },
      body: corpo === undefined ? undefined : JSON.stringify(corpo),
      signal: controle.signal,
    });
  } catch (erro) {
    const esgotou = erro && erro.name === "AbortError";
    throw new ErroApi(
      esgotou
        ? "O servidor demorou demais para responder. Tente de novo em instantes."
        : "Não consegui falar com o servidor. Ele pode estar fora do ar.",
      { offline: true }
    );
  } finally {
    clearTimeout(temporizador);
  }

  let dados = null;
  try {
    dados = await resposta.json();
  } catch {
    dados = null; // corpo vazio ou não-JSON (ex.: página de erro de um proxy)
  }

  if (!resposta.ok) {
    const texto =
      (dados && typeof dados.erro === "string" && dados.erro) ||
      (resposta.status >= 500
        ? "O servidor teve um problema ao responder. Tente de novo."
        : "Não foi possível processar o pedido (erro " + resposta.status + ").");
    throw new ErroApi(texto, { status: resposta.status });
  }

  if (!dados || typeof dados !== "object") {
    throw new ErroApi("O servidor enviou uma resposta inválida.", { status: resposta.status });
  }
  return dados;
}

/** Texto e tipo de status para um erro qualquer. */
function statusDoErro(erro, textoPadrao) {
  if (erro instanceof ErroApi && erro.offline) return ["Sem conexão", "offline"];
  return [textoPadrao, "erro"];
}

/** Mostra o erro na conversa (e no console, se for inesperado). */
function mostrarErro(erro, textoPadrao) {
  adicionarMensagem(erro instanceof ErroApi ? erro.message : textoPadrao, "erro");
  if (!(erro instanceof ErroApi)) console.error(erro);
}

/* ---------- Status e layout ---------- */

/**
 * Atualiza o texto de #status no topo.
 * tipo: "ok", "ocupado", "erro" ou "offline" (vira data-estado, que muda a cor do ponto).
 */
function definirStatus(texto, tipo = "ok") {
  el.status.textContent = texto;
  el.status.dataset.estado = tipo;
}

/** Liga ou desliga o modo "enviando": trava novos envios e o botão Reiniciar. */
function definirOcupado(ocupado) {
  estado.enviando = ocupado;
  el.botaoEnviar.disabled = ocupado;
  el.botaoReiniciar.disabled = ocupado;
  el.formulario.setAttribute("aria-busy", String(ocupado));
}

/**
 * Ajusta a altura da aplicação à área realmente visível. Em celulares o
 * teclado virtual encolhe a tela sem mudar 100dvh; com visualViewport o
 * formulário continua à vista enquanto o cliente digita.
 */
function ajustarAltura() {
  const altura = window.visualViewport ? window.visualViewport.height : window.innerHeight;
  document.documentElement.style.setProperty("--altura-app", Math.round(altura) + "px");
  rolarParaFim();
}

/* ---------- Conversa ---------- */

/**
 * Envia a mensagem do cliente para POST /api/chat e mostra a resposta.
 * Em caso de erro, mostra um balão .mensagem--erro e devolve o texto ao
 * campo para o cliente poder reenviar.
 */
async function enviarMensagem(texto) {
  const mensagem = String(texto ?? "").trim();
  if (!mensagem || estado.enviando) return;

  adicionarMensagem(mensagem, "usuario");
  el.campo.value = "";
  mostrarSugestoes([]);
  definirOcupado(true);
  definirStatus("Maresia está digitando…", "ocupado");
  mostrarDigitando(true);

  try {
    const dados = await requisitarJson(API.chat, {
      metodo: "POST",
      corpo: { mensagem, sessao: estado.sessaoId },
    });

    if (typeof dados.sessao === "string") estado.sessaoId = dados.sessao;

    mostrarDigitando(false);
    adicionarMensagem(dados.resposta || "…", "bot");

    if (typeof atualizarPainel === "function") atualizarPainel(dados, mensagem);

    if (dados.encaminhado) {
      definirStatus("Encaminhado a um atendente", "ocupado");
    } else {
      definirStatus("Online", "ok");
    }
  } catch (erro) {
    mostrarDigitando(false);
    mostrarErro(erro, "Algo deu errado ao enviar a mensagem.");
    definirStatus(...statusDoErro(erro, "Erro ao responder"));

    // devolve o texto ao campo se o cliente ainda não começou outro
    if (!el.campo.value) el.campo.value = mensagem;
  } finally {
    definirOcupado(false);
    el.campo.focus();
  }
}

/** Mostra a saudação e as sugestões iniciais numa conversa vazia. */
function mostrarBoasVindas() {
  el.mensagens.replaceChildren();
  if (estado.boasVindas) adicionarMensagem(estado.boasVindas, "bot");
  mostrarSugestoes(estado.sugestoesIniciais);
  if (typeof limparPainel === "function") limparPainel();
}

/**
 * Primeira carga: confere GET /api/saude, abre a sessão com
 * POST /api/reiniciar (que devolve a saudação) e mostra as sugestões.
 */
async function iniciarConversa() {
  definirStatus("Conectando…", "ocupado");
  definirOcupado(true);

  try {
    const saude = await requisitarJson(API.saude);
    if (saude.status !== "ok") {
      throw new ErroApi("O servidor respondeu, mas ainda não está pronto.", { status: 503 });
    }

    // Sem sessão no corpo, o servidor cria uma nova e devolve o id.
    const inicio = await requisitarJson(API.reiniciar, { metodo: "POST", corpo: {} });
    estado.sessaoId = typeof inicio.sessao === "string" ? inicio.sessao : novoIdSessao();
    estado.boasVindas = inicio.resposta || "";
    mostrarBoasVindas();

    if (saude.modelo_carregado) {
      definirStatus("Online", "ok");
    } else {
      definirStatus("Modelo não treinado", "erro");
      adicionarMensagem(
        "O modelo de intenções ainda não foi treinado. Rode **python treinar.py** e reinicie o servidor.",
        "erro"
      );
    }
  } catch (erro) {
    estado.sessaoId = estado.sessaoId || novoIdSessao();
    mostrarErro(erro, "Não foi possível iniciar a conversa.");
    definirStatus(...statusDoErro(erro, "Indisponível"));
  } finally {
    definirOcupado(false);
  }
}

/**
 * Botão Reiniciar: limpa a sessão no servidor (POST /api/reiniciar),
 * apaga a conversa na tela e volta à saudação.
 */
async function reiniciarConversa() {
  if (estado.enviando) return;
  definirOcupado(true);
  definirStatus("Reiniciando…", "ocupado");

  try {
    const dados = await requisitarJson(API.reiniciar, {
      metodo: "POST",
      corpo: { sessao: estado.sessaoId },
    });
    if (typeof dados.sessao === "string") estado.sessaoId = dados.sessao;
    if (dados.resposta) estado.boasVindas = dados.resposta;

    el.campo.value = "";
    mostrarBoasVindas();
    definirStatus("Online", "ok");
  } catch (erro) {
    // A conversa na tela fica como estava: o servidor não foi reiniciado.
    mostrarErro(erro, "Não foi possível reiniciar a conversa.");
    definirStatus(...statusDoErro(erro, "Erro ao reiniciar"));
  } finally {
    definirOcupado(false);
    el.campo.focus();
  }
}
