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
    '<svg class="icone" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">' +
    '<path d="M3 11.5 20 4l-7.5 17-2.2-7.3L3 11.5Z" fill="none" stroke="currentColor" ' +
    'stroke-width="2" stroke-linejoin="round"/></svg>',
  reiniciar:
    '<svg class="icone" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">' +
    '<path d="M4 12a8 8 0 1 0 2.4-5.7M4 4v4h4" fill="none" stroke="currentColor" ' +
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  painel:
    '<svg class="icone" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">' +
    '<path d="M4 19V11M10 19V5M16 19v-6M22 19H2" fill="none" stroke="currentColor" ' +
    'stroke-width="2" stroke-linecap="round"/></svg>',
  erro:
    '<svg class="icone icone--pequeno" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false">' +
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
 * Ajusta as alturas:
 * - o textarea cresce com o texto (até o max-height do CSS);
 * - a altura da aplicação fica só no CSS (100dvh). Não medimos a tela em JS:
 *   visualViewport pode ser menor que a janela (zoom, teclado recém-fechado)
 *   e deixava uma faixa em branco abaixo do rodapé.
 */
function ajustarAltura() {
  el.campo.style.height = "auto";
  el.campo.style.height = el.campo.scrollHeight + 2 + "px";
  manterJanelaNoTopo();
  rolarParaFim();
}

/**
 * A janela nunca deve rolar (só .mensagens e .painel). O iOS desloca a
 * página ao abrir o teclado mesmo com overflow: hidden; isto desfaz o deslocamento.
 */
function manterJanelaNoTopo() {
  if (window.scrollX || window.scrollY) window.scrollTo(0, 0);
}

/** Foca sem deixar o navegador rolar contêineres para "mostrar" o elemento. */
function focarSemRolar(elemento) {
  try {
    elemento.focus({ preventScroll: true });
  } catch {
    elemento.focus();
  }
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
  ajustarAltura();
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
    if (!el.campo.value) {
      el.campo.value = mensagem;
      ajustarAltura();
    }
  } finally {
    definirOcupado(false);
    focarSemRolar(el.campo);
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
    ajustarAltura();
    mostrarBoasVindas();
    definirStatus("Online", "ok");
  } catch (erro) {
    // A conversa na tela fica como estava: o servidor não foi reiniciado.
    mostrarErro(erro, "Não foi possível reiniciar a conversa.");
    definirStatus(...statusDoErro(erro, "Erro ao reiniciar"));
  } finally {
    definirOcupado(false);
    focarSemRolar(el.campo);
  }
}

/* ---------- Painel "Como a Maresia entendeu" ---------- */

// Valores de chatbot/config.py, usados quando a resposta não os traz.
const LIMIAR_PADRAO = 0.45;
const MARGEM_PADRAO = 0.15;

// Chaves auxiliares de extrair_entidades(): já aparecem junto de outra
// entidade (dia_semana vai com data) ou servem só ao diálogo.
const CHAVES_AUXILIARES = new Set(["dia_semana", "pratos_ambiguos", "horario_ambiguo"]);

// Nomes dos campos do estado da conversa (contexto).
const NOMES_CONTEXTO = {
  assunto: "Assunto atual",
  intencao_anterior: "Assunto anterior",
  etapa_reserva: "Etapa da reserva",
  slots: "Dados da reserva",
  falhas_seguidas: "Falhas seguidas",
  encaminhado: "Encaminhado a atendente",
  herdou_contexto: "Herdou o contexto",
  data_solta: "Data pendente",
};

// Valores internos que ficam melhores por extenso.
const VALORES_LEGIVEIS = {
  sem_gluten: "sem glúten",
  sem_lactose: "sem lactose",
  vegetariano: "vegetariano",
  vegano: "vegano",
  almoco: "almoço",
  jantar: "jantar",
  segunda: "segunda-feira",
  terca: "terça-feira",
  quarta: "quarta-feira",
  quinta: "quinta-feira",
  sexta: "sexta-feira",
  sabado: "sábado",
  domingo: "domingo",
};

// Emblema quando a resposta veio do contexto herdado do turno anterior.
const DECISAO_CONTEXTO = {
  rotulo: "Usou o contexto",
  tom: "verde",
  descricao: "A mensagem completou o assunto do turno anterior, então a Maresia herdou a intenção.",
};

/** Nome legível de uma chave (entidade, contexto ou campo qualquer). */
function nomeCampo(chave) {
  if (NOMES_ENTIDADES[chave]) return NOMES_ENTIDADES[chave];
  if (NOMES_CONTEXTO[chave]) return NOMES_CONTEXTO[chave];
  const texto = String(chave).replace(/_/g, " ").trim();
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}

/** "0.8234" → "82%" (ou "—" quando não há número). */
function porcentagem(valor) {
  return typeof valor === "number" && Number.isFinite(valor) ? Math.round(valor * 100) + "%" : "—";
}

/** Converte um valor de entidade/contexto em texto para o painel. */
function formatarValor(valor, chave = "", grupo = {}) {
  if (valor === null || valor === undefined || valor === "") return "";
  if (typeof valor === "boolean") return valor ? "Sim" : "Não";
  if (Array.isArray(valor)) {
    return valor.map((item) => formatarValor(item, chave)).filter(Boolean).join(", ");
  }
  if (typeof valor === "object") {
    if (typeof valor.nome === "string") return valor.nome;
    return Object.entries(valor)
      .map(([k, v]) => {
        const texto = formatarValor(v, k, valor);
        return texto ? nomeCampo(k) + ": " + texto : "";
      })
      .filter(Boolean)
      .join(" · ");
  }
  if (chave === "data" && /^\d{4}-\d{2}-\d{2}$/.test(valor)) {
    const [ano, mes, dia] = valor.split("-");
    const semana = grupo.dia_semana ? VALORES_LEGIVEIS[grupo.dia_semana] || grupo.dia_semana : "";
    return (semana ? semana + ", " : "") + dia + "/" + mes + "/" + ano;
  }
  if (chave === "etapa_reserva" || chave === "assunto" || chave === "intencao_anterior") {
    return ROTULOS_INTENCAO[valor] || VALORES_LEGIVEIS[valor] || nomeCampo(valor);
  }
  return VALORES_LEGIVEIS[valor] || String(valor);
}

/**
 * Preenche uma <ul class="entidades"> com itens {rotulo, valor}.
 * valor pode ser texto ou um nó (ex.: <code>). Lista vazia vira um item
 * .entidades--vazia com textoVazio. Devolve a própria lista.
 */
function preencherLista(lista, itens, textoVazio = "Nenhuma") {
  lista.replaceChildren();
  lista.classList.add("entidades");

  if (!itens.length) {
    const vazio = document.createElement("li");
    vazio.className = "entidades--vazia";
    vazio.textContent = textoVazio;
    lista.appendChild(vazio);
    return lista;
  }

  for (const { rotulo, valor } of itens) {
    const item = document.createElement("li");
    const tipo = document.createElement("span");
    tipo.className = "entidades__tipo";
    tipo.textContent = rotulo;
    const conteudo = document.createElement("span");
    conteudo.className = "entidades__valor";
    if (valor instanceof Node) conteudo.appendChild(valor);
    else conteudo.textContent = valor;
    item.append(tipo, conteudo);
    lista.appendChild(item);
  }
  return lista;
}

/** <code> com o texto (para mostrar frases sem formatação). */
function codigo(texto) {
  const elemento = document.createElement("code");
  elemento.textContent = texto;
  return elemento;
}

/** Parágrafo simples com uma classe opcional. */
function paragrafo(texto, classe = "etapa__descricao") {
  const p = document.createElement("p");
  p.className = classe;
  p.textContent = texto;
  return p;
}

/** Lista [ [intencao, prob], ... ] em ordem decrescente, venha como dict ou lista. */
function probabilidadesOrdenadas(a) {
  let pares = [];
  if (a.probabilidades && typeof a.probabilidades === "object" && !Array.isArray(a.probabilidades)) {
    pares = Object.entries(a.probabilidades);
  } else if (Array.isArray(a.alternativas)) {
    pares = a.alternativas.map((alt) => [alt.intencao, alt.probabilidade]);
  }
  return pares
    .filter(([intencao, prob]) => intencao && typeof prob === "number")
    .sort((x, y) => y[1] - x[1]);
}

/** Uma barra de probabilidade com a linha tracejada do limiar. */
function criarBarra(intencao, prob, limiar, escolhida) {
  const barra = document.createElement("div");
  barra.className = "barra" + (escolhida ? " barra--escolhida" : "");

  const rotulo = document.createElement("span");
  rotulo.className = "barra__rotulo";
  rotulo.textContent = ROTULOS_INTENCAO[intencao] || nomeCampo(intencao);

  const valor = document.createElement("span");
  valor.className = "barra__valor";
  valor.textContent = porcentagem(prob);

  const trilho = document.createElement("div");
  trilho.className = "barra__trilho";
  trilho.style.setProperty("--limiar", Math.min(Math.max(limiar, 0), 1) * 100 + "%");
  trilho.setAttribute("role", "img");
  trilho.setAttribute(
    "aria-label",
    rotulo.textContent + ": " + valor.textContent + " (limiar " + porcentagem(limiar) + ")"
  );

  const preenchimento = document.createElement("div");
  preenchimento.className = "barra__preenchimento";
  preenchimento.style.width = Math.min(Math.max(prob, 0), 1) * 100 + "%";

  const linha = document.createElement("div");
  linha.className = "barra__limiar";
  linha.title = "Limiar de confiança: " + porcentagem(limiar);

  trilho.append(preenchimento, linha);
  barra.append(rotulo, valor, trilho);
  return barra;
}

/**
 * Desenha as 5 etapas do painel a partir da análise de uma mensagem:
 * {
 *   texto_original, texto_normalizado, tokens?,
 *   probabilidades {intencao: prob} | alternativas [{intencao, probabilidade}],
 *   limiar?, margem?, intencao, tipo, confianca, camada?,
 *   entidades {...}, contexto {...}
 * }
 * Campos ausentes viram um aviso curto na etapa, sem quebrar o painel.
 */
function renderizarAnalise(a) {
  if (!a || typeof a !== "object") return;

  // 1. Pré-processamento
  const itensTexto = [];
  if (a.texto_original) itensTexto.push({ rotulo: "Original", valor: codigo(a.texto_original) });
  if (a.texto_normalizado) itensTexto.push({ rotulo: "Normalizado", valor: codigo(a.texto_normalizado) });
  if (Array.isArray(a.tokens) && a.tokens.length) {
    itensTexto.push({ rotulo: "Tokens", valor: codigo(a.tokens.join(" · ")) });
  }
  el.etapaPreprocessamento.replaceChildren(
    preencherLista(document.createElement("ul"), itensTexto, "Texto não informado.")
  );
  if (a.texto_original && !a.texto_normalizado) {
    el.etapaPreprocessamento.appendChild(paragrafo("O servidor não enviou o texto normalizado."));
  }

  // 2. Probabilidade por intenção
  const limiar = typeof a.limiar === "number" ? a.limiar : LIMIAR_PADRAO;
  const pares = probabilidadesOrdenadas(a);
  el.etapaProbabilidades.replaceChildren();
  if (pares.length) {
    for (const [intencao, prob] of pares) {
      el.etapaProbabilidades.appendChild(criarBarra(intencao, prob, limiar, intencao === a.intencao));
    }
    const legenda = "Linha tracejada: limiar de confiança (" + porcentagem(limiar) + ")" +
      (typeof a.margem === "number" ? " · margem entre as duas primeiras: " + porcentagem(a.margem) : "");
    el.etapaProbabilidades.appendChild(paragrafo(legenda));
  } else {
    el.etapaProbabilidades.appendChild(
      paragrafo("O classificador não foi usado: a mensagem foi resolvida por " +
        (CAMADAS[a.tipo] || "outra camada").toLowerCase() + ".")
    );
  }

  // 3. Entidades extraídas (sem as chaves auxiliares e sem valores vazios)
  const entidades = a.entidades && typeof a.entidades === "object" ? a.entidades : null;
  el.etapaEntidades.replaceChildren();
  if (entidades) {
    const itens = Object.entries(entidades)
      .filter(([chave]) => !CHAVES_AUXILIARES.has(chave) && !chave.startsWith("_"))
      .map(([chave, valor]) => ({ rotulo: nomeCampo(chave), valor: formatarValor(valor, chave, entidades) }))
      .filter((item) => item.valor);
    el.etapaEntidades.appendChild(
      preencherLista(document.createElement("ul"), itens, "Nenhuma entidade encontrada.")
    );
  } else {
    el.etapaEntidades.appendChild(paragrafo("O servidor não enviou as entidades desta mensagem."));
  }

  // 4. Decisão
  const usouContexto = a.camada === "contexto";
  const decisao = usouContexto
    ? DECISAO_CONTEXTO
    : DECISOES[a.tipo] || { rotulo: a.tipo ? nomeCampo(a.tipo) : "Desconhecida", tom: "ardosia", descricao: "" };

  const emblema = document.createElement("span");
  emblema.className = "decisao";
  emblema.dataset.tom = decisao.tom;
  emblema.textContent = decisao.rotulo;

  const itensDecisao = [
    { rotulo: "Camada", valor: usouContexto ? "Contexto da conversa" : CAMADAS[a.tipo] || "—" },
  ];
  if (a.intencao) {
    itensDecisao.push({ rotulo: "Intenção", valor: ROTULOS_INTENCAO[a.intencao] || nomeCampo(a.intencao) });
  }
  if (typeof a.confianca === "number") itensDecisao.push({ rotulo: "Confiança", valor: porcentagem(a.confianca) });

  el.etapaDecisao.replaceChildren(emblema);
  if (decisao.descricao) el.etapaDecisao.appendChild(paragrafo(decisao.descricao));
  el.etapaDecisao.appendChild(preencherLista(document.createElement("ul"), itensDecisao));

  // 5. Contexto da conversa
  const contexto = a.contexto && typeof a.contexto === "object" ? a.contexto : {};
  const itensContexto = Object.entries(contexto)
    .map(([chave, valor]) => ({ rotulo: nomeCampo(chave), valor: formatarValor(valor, chave, contexto) }))
    .filter((item) => item.valor);
  el.etapaContexto.replaceChildren(
    preencherLista(document.createElement("ul"), itensContexto, "Nada guardado ainda.")
  );

  el.painelVazio.hidden = true;
  el.etapas.hidden = false;
}

/**
 * Monta a análise a partir da resposta de /api/chat e desenha o painel.
 * Usa dados.analise quando o servidor a envia; o que faltar vem dos
 * campos de nível superior (tipo, confiança, alternativas, contexto).
 */
function atualizarPainel(dados, mensagem) {
  const extra = dados.analise && typeof dados.analise === "object" ? dados.analise : {};
  const analise = {
    texto_original: mensagem,
    intencao: dados.intencao,
    tipo: dados.tipo,
    confianca: dados.confianca,
    margem: dados.margem,
    alternativas: dados.alternativas,
    camada: dados.herdou_contexto ? "contexto" : undefined,
    ...extra,
    contexto: {
      herdou_contexto: dados.herdou_contexto,
      falhas_seguidas: dados.falhas_seguidas,
      encaminhado: dados.encaminhado,
      ...(extra.contexto || {}),
    },
  };
  renderizarAnalise(analise);

  const limiar = typeof analise.limiar === "number" ? analise.limiar : LIMIAR_PADRAO;
  const margem = typeof analise.margem_minima === "number" ? analise.margem_minima : MARGEM_PADRAO;
  el.infoModelo.textContent =
    "TF-IDF + regressão logística · limiar " + porcentagem(limiar) +
    " · margem mínima " + porcentagem(margem) +
    (estado.sessaoId ? " · sessão " + estado.sessaoId.slice(0, 8) : "");
}

/** Volta o painel ao estado inicial (antes da primeira mensagem). */
function limparPainel() {
  for (const caixa of [
    el.etapaPreprocessamento,
    el.etapaProbabilidades,
    el.etapaEntidades,
    el.etapaDecisao,
    el.etapaContexto,
  ]) {
    caixa.replaceChildren();
  }
  el.etapas.hidden = true;
  el.painelVazio.hidden = false;
  el.infoModelo.textContent = "";
}

/* ---------- Abrir e fechar o painel (gaveta em telas até 1080px) ---------- */

const consultaGaveta = window.matchMedia("(max-width: 1080px)");

/**
 * abrir = true abre, false fecha. Cuida do véu, do aria-expanded e do foco.
 * focar = false não move o foco (usado na abertura automática, no carregamento).
 */
function abrirPainel(abrir, focar = true) {
  const aberto = el.painel.classList.contains("painel--aberto");
  if (abrir === aberto) return;

  el.painel.classList.toggle("painel--aberto", abrir);
  el.veu.hidden = !abrir;
  el.botaoPainel.setAttribute("aria-expanded", String(abrir));

  if (!focar) return;
  if (abrir) {
    focarSemRolar(el.botaoFecharPainel);
  } else if (el.painel.contains(document.activeElement)) {
    focarSemRolar(el.botaoPainel);
  }
}

/** Desktop (> 1080px): painel aberto ao lado da conversa. Celular: gaveta fechada. */
function abrirPainelConformeTela() {
  abrirPainel(!consultaGaveta.matches, false);
}

/* ---------- Ouvintes de eventos ---------- */

el.formulario.addEventListener("submit", (evento) => {
  evento.preventDefault();
  enviarMensagem(el.campo.value);
});

// Enter envia; Shift+Enter quebra a linha (comportamento padrão do textarea).
el.campo.addEventListener("keydown", (evento) => {
  if (evento.key !== "Enter" || evento.shiftKey || evento.isComposing) return;
  evento.preventDefault();
  if (!estado.enviando) el.formulario.requestSubmit();
});

el.campo.addEventListener("input", ajustarAltura);

window.addEventListener("resize", ajustarAltura);
if (window.visualViewport) window.visualViewport.addEventListener("resize", ajustarAltura);
window.addEventListener("scroll", manterJanelaNoTopo, { passive: true });

// Ao cruzar 1080px: no desktop o painel volta aberto; no celular a gaveta fecha.
consultaGaveta.addEventListener("change", abrirPainelConformeTela);

el.botaoReiniciar.addEventListener("click", reiniciarConversa);
el.botaoPainel.addEventListener("click", () => {
  abrirPainel(!el.painel.classList.contains("painel--aberto"));
});
el.botaoFecharPainel.addEventListener("click", () => abrirPainel(false));
el.veu.addEventListener("click", () => abrirPainel(false));

document.addEventListener("keydown", (evento) => {
  if (evento.key === "Escape" && el.painel.classList.contains("painel--aberto")) {
    abrirPainel(false);
  }
});

window.addEventListener("offline", () => definirStatus("Sem conexão", "offline"));
window.addEventListener("online", () => {
  if (!estado.enviando) definirStatus("Online", "ok");
});

/* ---------- Início ---------- */
// Abre o painel no desktop sem animar o primeiro quadro (.sem-transicao).
document.body.classList.add("sem-transicao");
abrirPainelConformeTela();
requestAnimationFrame(() => {
  requestAnimationFrame(() => document.body.classList.remove("sem-transicao"));
});

ajustarAltura();
iniciarConversa();
