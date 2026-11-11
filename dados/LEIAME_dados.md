# LEIAME — dataset de intenções (`intencoes_treino.csv`)

Dataset de treino do classificador de intenções da **Maresia**, assistente virtual do restaurante
fictício **Tempero Açoriano** (frutos do mar, Santo Antônio de Lisboa, Florianópolis/SC).
Versão atual: **v1.0 — 236 frases, 59 por classe**.

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

## LGPD

O dataset **não contém dados pessoais**. As frases são fictícias, não identificam ninguém e não trazem
nomes, telefones, e-mails, CPF ou endereços de pessoas. Menções a alergias ou à rotina são genéricas e
inventadas. Ao acrescentar frases, mantenha esse critério: nunca copie mensagens reais de clientes.

## Licença

Os dados desta pasta são distribuídos sob a licença
[Creative Commons Atribuição 4.0 Internacional (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/deed.pt_BR).
O código do projeto segue a licença MIT (ver `LICENSE`).
