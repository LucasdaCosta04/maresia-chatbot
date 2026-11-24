# LEIAME — dataset de intenções (`intencoes_treino.csv`)

Dataset de treino do classificador de intenções da **Maresia**, assistente virtual do restaurante
fictício **Tempero Açoriano** (frutos do mar, Santo Antônio de Lisboa, Florianópolis/SC).
Versão atual: **v1.5 — 265 frases** (`cardapio_alergenicos` 63, `reserva` 71,
`horario_localizacao` 72, `fora_escopo` 59).

## Origem

As frases são **autorais**, escritas pela equipe do projeto (A3 UNISUL) **com apoio de IA**.
Toda frase gerada com apoio de IA foi **revisada pela equipe** antes de entrar no arquivo: rótulo
conferido, frases artificiais reescritas e duplicatas removidas. Nenhuma frase foi coletada de clientes
reais, de redes sociais ou de outros sites.

## Formato

| Item | Valor |
|---|---|
| Arquivo | `dados/intencoes_treino.csv` |
| Codificação | UTF-8, quebras de linha LF |
| Separador | vírgula; frases que contêm vírgula ficam entre aspas duplas |
| Cabeçalho | `frase,intencao` |
| Linhas | uma frase por linha, sem duplicatas |

O texto é mantido **como o usuário escreveria**: com e sem acento, com e sem pontuação, maiúsculas
ocasionais e abreviações de chat (`vcs`, `qnto`, `hj`, `p/`, `qro`). A normalização fica a cargo do
pré-processamento do chatbot, não do dataset.

## Classes

Os rótulos são exatamente estes quatro:

| Rótulo | Critério | Exemplos |
|---|---|---|
| `cardapio_alergenicos` | Pratos, preços, porções, ingredientes, opções vegetarianas, veganas e infantis, e **alergênicos**: os da RDC 26/2015 da ANVISA (trigo/glúten, crustáceos, ovos, peixes, amendoim, soja, leite, castanhas/oleaginosas, látex natural) mais **moluscos e gergelim**. Inclui risco de contaminação cruzada (óleo ou utensílios compartilhados). | "o atum selado vem com crosta de gergelim?", "a maionese caseira leva ovo cru?" |
| `reserva` | Criar, consultar, confirmar, **alterar** (data, horário, número de pessoas, local da mesa), **cancelar** ou remarcar reserva, além de dúvidas sobre a política de reservas (atraso, multa, antecedência). | "quero antecipar a reserva das 20h pras 18h30", "desisti da reserva de domingo" |
| `horario_localizacao` | Dias e horários de funcionamento (incluindo feriados e datas especiais), endereço, CEP, mapa, **estacionamento** e **como chegar** (de carro, moto, bicicleta, a pé ou por aplicativo). | "o estacionamento lota no fim de semana?", "vou de uber, qual ponto de referência eu coloco?" |
| `fora_escopo` | Qualquer assunto sem relação com o restaurante. Parte das frases usa de propósito **palavras do domínio em outro sentido** ("reservar passagem", "horário do Detran", "localização do celular", "alergia do cachorro", "mesa digitalizadora", "sequência de Fibonacci"), para o modelo não aprender que a palavra sozinha decide a classe. | "como reservar passagem aérea barata", "qual o horário de visita do hospital" |

Algumas frases são propositalmente difíceis, porque misturam palavras de duas classes. Elas recebem o
rótulo do **pedido principal**. Exemplo: "vou levar um bebê, da pra reservar com cadeirinha" é `reserva`.

## Temas excluídos de propósito

Nenhuma frase do treino trata destes temas (nem nas palavras, nem no assunto):

| Tema | Motivo |
|---|---|
| **pix**, **pagamento** | Ficam reservados para o desafio ao vivo do README ("adicionar uma intenção nova sem mexer no código"). Se já estivessem no treino como `fora_escopo` ou em outra classe, a demonstração da nova intenção `pagamento` ficaria contaminada. |
| **clima**, **chuva**, **futebol**, **receita** | Assuntos fora do escopo deixados de fora do treino para aparecerem só nos casos de teste (`casos_teste.csv`). Assim a avaliação mede se o modelo generaliza a abstenção para temas que **nunca viu**. |
| **delivery**, **entrega**, **ônibus** | Temas de borda, próximos do domínio (o restaurante não faz delivery; ônibus seria uma forma de "como chegar"). Ficam fora do treino para que os casos de teste mostrem como a Maresia reage a eles (classificação, esclarecimento ou fallback) sem tê-los visto antes. |

O script `scripts/checar_dataset.py` falha se algum desses temas aparecer no treino.

## Limpeza e validação

- Duplicatas são comparadas **depois de normalizar**: minúsculas, sem acento, sem pontuação e com
  espaços simples. "Vocês abrem?" e "voces abrem" contam como a mesma frase.
- Na revisão do lote 2, foi trocada uma frase que tocava num tema reservado (estádio de futebol).
- Validação automática (verifica cabeçalho, rótulos, frases vazias, duplicatas normalizadas e temas
  reservados, e imprime a contagem por classe; sai com código 1 se houver erro):

  ```bash
  python scripts/checar_dataset.py
  ```

## Evolução

| Versão | Frases | cardapio_alergenicos | reserva | horario_localizacao | fora_escopo | O que mudou |
|---|---|---|---|---|---|---|
| lote 1 | 138 | 35 | 35 | 34 | 34 | Base inicial das quatro classes. |
| lote 2 | 224 | 56 | 56 | 56 | 56 | +86 frases: alergênicos específicos (moluscos, gergelim, soja, ovo, amendoim), alteração e cancelamento de reserva, estacionamento e "como chegar", `fora_escopo` com palavras do domínio em outro sentido. |
| lote 3 — **v1.0** | 236 | 59 | 59 | 59 | 59 | +12 frases (3 por classe) para cobrir casos de borda restantes. |
| v1.3 | 251 | 59 | 69 | 64 | 59 | +15 frases para corrigir lacunas de vocabulário apontadas pela avaliação cega (ver abaixo). |
| v1.4 | 255 | 59 | 69 | 68 | 59 | +4 frases de `horario_localizacao` com "atendimento" (ver abaixo). |
| **v1.5** | 265 | 63 | 71 | 72 | 59 | +10 frases para perguntas claras que caíam em `fora_escopo` (ver abaixo). |

### Evolução v1.0 → v1.3

**Motivo.** A avaliação cega da v1.1 (`resultados/matriz_testes.md`) mostrou duas lacunas de
vocabulário no treino:

1. **Reserva dita de forma coloquial.** O treino quase só tinha "reservar"/"reserva". Pedidos como
   "marcar", "segurar", "guardar", "garantir" ou "deixar separada" uma mesa ou um lugar, e "janta" ou
   "almoço" com a galera ou com a família, ficavam sem intenção definida. Foram acrescentadas
   **10 frases de `reserva`** com esses verbos e situações, variando data, horário e número de pessoas.
2. **Localização em mensagens muito curtas.** Mensagens de 1 a 3 palavras sobre endereço,
   localização, mapa, onde fica ou como chegar caíam no fallback. Foram acrescentadas
   **5 frases curtas de `horario_localizacao`**.

**Regra para não contaminar a avaliação.** As frases novas são gerais e foram escritas sem abrir
`casos_teste.csv`. Não copiam nem parafraseiam de perto nenhuma mensagem dos casos de teste. Por exemplo,
"endereço" sozinho não entrou porque seria cópia exata de um caso. Uma frase candidata que ficou parecida
demais com um caso foi reescrita antes de entrar. Nenhum caso de teste foi alterado. Nenhuma frase
existente foi removida ou modificada. Os temas reservados continuam fora do treino.

**Conferência.** `scripts/checar_dataset.py` sem erros. Em `scripts/checar_casos_teste.py`, a similaridade
média dos casos com o treino passou de **0,362** para **0,364**. A máxima continua em **0,675** (T24),
abaixo do limite de 0,85. Os casos que mais subiram foram T10 (0,230 → 0,271) e T13 (0,327 → 0,365).

**Efeito colateral.** As classes deixaram de ser balanceadas (69 e 64 contra 59). A diferença é pequena,
mas deve ser lembrada ao interpretar a matriz de confusão.

### Evolução v1.3 → v1.4

**Motivo.** "qual o horário de atendimento?" caía em `fora_escopo`: a única frase do treino com
"atendimento" era "qual o horário de atendimento do posto de saúde" (`fora_escopo`). Foram acrescentadas
**4 frases de `horario_localizacao`** com "atendimento". A frase do posto de saúde continua no treino,
e perguntas de horário de atendimento de outros lugares (banco, posto) continuam em `fora_escopo`.

**Conferência.** `scripts/checar_dataset.py` sem erros. Em `scripts/checar_casos_teste.py`, a similaridade
média continua em **0,364** e a máxima é **0,671**, abaixo do limite de 0,85.

### Evolução v1.4 → v1.5

**Motivo.** Uma bateria exploratória de perguntas de clientes mostrou perguntas claras do domínio caindo
em `fora_escopo` ou no fallback: horário de um dia ("qual o horário de sábado?"), "horário" sozinho,
"menu", pedido de recomendação de prato e antecedência da reserva. Foram acrescentadas **10 frases**:
4 de `horario_localizacao`, 4 de `cardapio_alergenicos` e 2 de `reserva`. Nenhuma copia as frases da
bateria nem dos casos de teste.

**Conferência.** `scripts/checar_dataset.py` sem erros. Em `scripts/checar_casos_teste.py`, a similaridade
média foi para **0,365** e a máxima para **0,672**, abaixo do limite de 0,85. Perguntas com as mesmas
palavras em outro sentido ("horário do Detran", "horário do banco", "me recomenda uma série", "horário de
verão") continuam em `fora_escopo`.

**Efeito colateral.** A acurácia da validação cruzada (5 folds) ficou em **0,815**; na v1.4 era 0,835.
Os números não são diretamente comparáveis (o conjunto mudou), e as classes ficaram mais desbalanceadas
(`fora_escopo` com 59 contra 63 a 72 das outras).

## Casos de teste (`casos_teste.csv`)

### Objetivo

34 casos **inéditos** para a avaliação cega da Maresia como um todo (classificador, política de decisão,
regras, contexto e regras de reserva), e não só do classificador. Nenhuma mensagem é cópia ou quase-cópia
de uma frase do treino.

### Execução cega

- Os casos foram escritos **sem abrir** `intencoes_treino.csv`. Só o script de checagem lê o treino, e só
  depois que os casos estavam escritos.
- O chatbot, o modelo e o app **não foram executados** sobre os casos. O resultado esperado vem da
  especificação (README, `base_conhecimento.json` e regras de negócio), não do que o modelo faz hoje.
- Casos não são ajustados para melhorar a métrica. Só se reescreve um caso que fure o limite de
  similaridade com o treino.

### Data de referência

As datas relativas consideram que **"agora" é quarta-feira, 18/11/2026, 18:00 (America/Sao_Paulo)**.
Assim, "amanhã" é quinta 19/11, "sexta" é 20/11, "sábado" é 21/11 e "segunda que vem" é 23/11 (fechado).
Às 18:00 de quarta o restaurante está entre o almoço e o jantar (o jantar abre às 18:30).

### Formato

UTF-8, separador vírgula, campos com vírgula entre aspas duplas. Cabeçalho:
`id,categoria,contexto,mensagem,tipo_esperado,intencao_esperada,resposta_deve_conter,justificativa`.

| Coluna | Conteúdo |
|---|---|
| `id` | `T01` a `T34` |
| `categoria` | `esperada`, `reformulacao`, `ambigua`, `fora_escopo`, `limite`, `contexto`, `regra_negocio` ou `encaminhamento` |
| `contexto` | Mensagens anteriores da mesma conversa, separadas por ` \|\| ` (vazio se não houver) |
| `mensagem` | A mensagem avaliada |
| `tipo_esperado` | Tipo de `dialogo.Resposta`: `aceita`, `regra`, `reserva`, `esclarecimento`, `abstencao`, `fallback` ou `encaminhamento`. Quando mais de um é aceitável, vêm separados por `\|`, e a justificativa explica |
| `intencao_esperada` | `cardapio_alergenicos`, `reserva`, `horario_localizacao`, `fora_escopo` ou vazio (sem intenção definida, como em esclarecimento e encaminhamento) |
| `resposta_deve_conter` | Trecho curto, minúsculo e sem acento que a resposta precisa conter (comparar com a resposta normalizada), ou vazio |
| `justificativa` | Uma frase dizendo por que esse é o comportamento correto |

### Distribuição

| Categoria | Casos | O que cobre |
|---|---|---|
| `esperada` | 6 | Pedidos diretos, 2 por intenção de domínio |
| `reformulacao` | 6 | O mesmo tipo de pedido dito de forma indireta, coloquial ou com gíria, 2 por intenção de domínio |
| `ambigua` | 4 | Dois assuntos na mesma mensagem ou mensagem vaga (data solta) → esclarecimento |
| `fora_escopo` | 6 | Um de cada tema nunca visto no treino: clima, delivery, PIX, futebol, receita culinária e ônibus (linha urbana, não "como chegar") |
| `limite` | 5 | Erros de digitação pesados, tudo em maiúsculas, uma palavra só, mensagem longa e emoji/gíria |
| `contexto` | 3 | A resposta depende do turno anterior |
| `regra_negocio` | 2 | Reserva numa segunda-feira (fechado) e reserva para mais de 10 pessoas |
| `encaminhamento` | 2 | Pedido explícito de atendente e mensagem sem sentido após 2 falhas no contexto |

Os tipos múltiplos foram usados só onde a especificação não decide sozinha: o primeiro turno de uma
reserva (`aceita|reserva`), delivery e PIX, que a base não cobre (`abstencao|fallback`), o grupo acima de
10 pessoas (`reserva|encaminhamento`) e o pedido de atendente, que é regra prioritária e encaminhamento
ao mesmo tempo (`encaminhamento|regra`).

### Checagem e similaridade com o treino

```bash
python scripts/checar_casos_teste.py
```

O script valida cabeçalho, 34 linhas, ids únicos, categorias, a distribuição acima, tipos e intenções.
Depois mede a similaridade de cada mensagem com **todas** as frases do treino (TF-IDF de n-gramas de
caracteres 2–5 sobre o texto normalizado, cosseno), imprime a frase de treino mais parecida de cada caso
e sai com código 1 se houver cópia normalizada exata ou similaridade **> 0,85**. As mesmas validações
rodam no CI por `testes/test_casos_teste.py`.

Resultado na primeira execução, sem nenhum caso reescrito:

| Métrica | Valor |
|---|---|
| Similaridade média (frase de treino mais parecida) | **0,362** |
| Similaridade máxima | **0,675** (T24, "QUE HORAS VOCÊS FECHAM NO DOMINGO???") |
| Cópias normalizadas exatas | 0 |

## LGPD

O dataset **não contém dados pessoais**. As frases são fictícias, não identificam ninguém e não trazem
nomes, telefones, e-mails, CPF ou endereços de pessoas. Menções a alergias ou à rotina são genéricas e
inventadas. Ao acrescentar frases, mantenha esse critério: nunca copie mensagens reais de clientes.

## Licença

Os dados desta pasta são distribuídos sob a licença
[Creative Commons Atribuição 4.0 Internacional (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/deed.pt_BR).
O código do projeto segue a licença MIT (ver `LICENSE`).
