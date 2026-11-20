# Changelog

Todas as mudanças relevantes deste projeto são documentadas neste arquivo.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e o projeto adota o [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Não lançado]

## [v1.0] - 2026-11-20

Primeira versão da **Maresia**, assistente virtual do restaurante fictício
**Tempero Açoriano** (projeto acadêmico A3 – UNISUL).

### Adicionado

#### Dados
- Dataset de intenções `dados/intencoes_treino.csv` com 236 frases
  balanceadas entre 4 intenções (59 cada): `cardapio_alergenicos`, `reserva`,
  `horario_localizacao` e `fora_escopo`.
- Base de conhecimento `dados/base_conhecimento.json` (versão 1.0) do Tempero
  Açoriano: dados do restaurante, funcionamento por dia da semana, regras de
  reserva (1 a 10 pessoas, antecedência de 1 hora a 30 dias, horários de 30 em
  30 minutos, tolerância de atraso), cardápio com 23 pratos, 11 alergênicos,
  respostas por intenção e textos de fallback, esclarecimento e encaminhamento
  humano. Todos os dados são fictícios.
- Documentação da origem, dos critérios e da limpeza do dataset em
  `dados/LEIAME_dados.md`.
- Scripts de validação `scripts/checar_dataset.py` (cabeçalho, rótulos,
  duplicatas e temas reservados) e `scripts/checar_base.py` (estrutura,
  cardápio, alergênicos, funcionamento e regras de reserva).

#### Núcleo do chatbot (`chatbot/`)
- `config.py` com os parâmetros ajustáveis: limiar de confiança (0,45),
  margem mínima (0,15), máximo de falhas seguidas (2), parâmetros do
  vetorizador e do classificador, fuso `America/Sao_Paulo` e limite de
  500 caracteres por mensagem.
- Pré-processamento (`preprocessamento.py`): minúsculas, remoção de acentos,
  expansão de abreviações de chat (`vc`, `p/`, `hj`, `pra`…), troca de números
  pelo token `num` e remoção de pontuação e emojis. As stopwords são mantidas
  por decisão empírica (acurácia da validação cruzada de 0,828 contra 0,819).
- Classificador de intenções (`modelo.py`): TF-IDF de palavras (1–2-gramas) e
  de caracteres (2–5-gramas) combinados com `FeatureUnion` + Regressão
  Logística com classes balanceadas.
- Política de decisão em quatro desfechos: **aceita** (confiança ≥ limiar e
  margem ≥ margem mínima), **abstenção** (fora do escopo), **esclarecimento**
  (duas intenções de domínio disputando) e **fallback**.
- Script `treinar.py`: validação cruzada estratificada (5 dobras), relatório
  de classificação, matriz de confusão e gravação do modelo em
  `modelos/classificador.joblib`.
- Extração de entidades (`entidades.py`): pratos (inclusive ambíguos),
  alergênicos, restrições alimentares, número de pessoas, data (absoluta e
  relativa, com dia da semana), horário (inclusive ambíguo), período do dia
  e nome do cliente.
- Gerenciador de diálogo (`dialogo.py`):
  - regras prioritárias antes do classificador (atendente, cancelar, ajuda,
    saudação e despedida);
  - respostas com entidades sobre cardápio, alergênicos, restrições e
    horário de funcionamento do dia pedido;
  - herança de contexto entre turnos (ex.: "e no domingo?" após perguntar
    o horário);
  - fluxo de reserva simulada com slots (pessoas, data, horário e nome),
    validação das regras de negócio, alteração de dados e confirmação;
  - **pedidos múltiplos**: mensagens com assuntos diferentes ("quero reservar
    e ver o cardápio") viram a pergunta "por qual começamos?";
  - **data solta**: uma mensagem só com a data ("sábado") leva a Maresia a
    perguntar o que o cliente quer fazer nesse dia;
  - contador de falhas seguidas com encaminhamento para um atendente humano.

#### API Flask (`app.py`)
- `POST /api/mensagem` (alias `POST /api/chat`): resposta, intenção, tipo
  de decisão, confiança, margem, 3 alternativas, herança de contexto, estado
  de encaminhamento, falhas seguidas e id da sessão.
- Campos de explicabilidade na mesma resposta, sem remover as chaves
  anteriores: `texto_original`, `texto_normalizado`, `tokens`, `entidades`,
  `limiar`, `margem_minima`, `probabilidades`, `contexto` e `modelo`.
- `POST /api/reiniciar`: limpa ou cria a sessão e devolve a saudação.
- `GET /api/saude`: status, modelo carregado, sessões ativas, limiar,
  margem mínima e metadados do modelo.
- Sessões em memória protegidas por lock, validação de entrada e erros
  padronizados em JSON (400, 404, 405, 500 e 503 quando o modelo não foi
  treinado).

#### Interface web (`templates/index.html`, `static/`)
- Chat com saudação, sugestões de mensagem, indicador "digitando…", envio
  com Enter, botão "Nova conversa" e mensagens de erro e de falta de conexão.
- Painel **"Como a Maresia entendeu"** com 5 etapas: pré-processamento,
  probabilidade por intenção (barras com a linha do limiar), entidades
  extraídas, decisão e contexto da conversa. Campos vazios ou nulos ficam de
  fora, sem exibir `undefined`.
- Layout em `100dvh` sem rolagem da janela: só a lista de mensagens e o
  painel rolam; sugestões e composer sempre visíveis.
- Responsividade: painel lateral no desktop e gaveta com véu em telas de até
  1080px, sem rolagem horizontal em 390px.
- Acessibilidade: regiões `aria-live`, rótulos acessíveis, foco visível,
  fechamento do painel com Esc e respeito a `prefers-reduced-motion`.

#### Testes e qualidade
- Suíte pytest em `testes/` com 325 casos de teste: pré-processamento (46),
  entidades (72), modelo e política de decisão (52), diálogo (123), treino (2)
  e API e interface web (30), incluindo a rota `/`, os arquivos estáticos e
  os campos de explicabilidade de `/api/chat`.
- Workflow de CI (`.github/workflows/testes.yml`) que roda os testes a cada
  push e pull request.
- README, guia de contribuição, modelos de pull request e de issue, licença
  MIT, `requirements.txt` e `.editorconfig`.

[Não lançado]: https://github.com/LucasdaCosta04/maresia-chatbot/compare/v1.0...HEAD
[v1.0]: https://github.com/LucasdaCosta04/maresia-chatbot/releases/tag/v1.0
