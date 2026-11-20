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
