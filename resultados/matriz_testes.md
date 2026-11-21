# Matriz de testes — avaliação cega da Maresia

Data de referência: quarta-feira, 18/11/2026 18:00 (America/Sao_Paulo). Dataset de treino: 251 frases.

| Categoria | Acertos/Total | % |
|---|---|---|
| esperada | 5/6 | 83,3% |
| reformulacao | 4/6 | 66,7% |
| ambigua | 3/4 | 75,0% |
| fora_escopo | 5/6 | 83,3% |
| limite | 4/5 | 80,0% |
| contexto | 3/3 | 100,0% |
| regra_negocio | 1/2 | 50,0% |
| encaminhamento | 1/2 | 50,0% |
| **total** | **26/34** | **76,5%** |

## Casos que falharam

| Id | Categoria | Mensagem | Motivo |
|---|---|---|---|
| T06 | esperada | Qual é o endereço do restaurante? | texto: falta 'rendeiras' |
| T11 | reformulacao | vcs tão funcionando agora? | texto: falta '18:30' |
| T12 | reformulacao | saindo do aeroporto de carro qual caminho eu faço pra chegar aí? | texto: falta 'santo antonio' |
| T13 | ambigua | quero dar uma olhada no cardápio e já deixar uma mesa garantida pra sexta | tipo: esperado esclarecimento, obtido aceita |
| T18 | fora_escopo | vocês fazem delivery pro Campeche? | tipo: esperado abstencao\|fallback, obtido aceita; intencao: esperada fora_escopo, obtida horario_localizacao |
| T25 | limite | endereço | texto: falta 'rendeiras' |
| T32 | regra_negocio | preciso de mesa pra 14 pessoas no sábado às 20h | tipo: esperado reserva\|encaminhamento, obtido aceita |
| T34 | encaminhamento | asdf qwer tyu | tipo: esperado encaminhamento, obtido fallback; texto: falta 'whatsapp' |
