# Como contribuir com a Maresia

Guia de trabalho da equipe (**Carlos**, **Lucas** e **Murilo**) no repositório `maresia-chatbot`.
Leia antes de abrir sua primeira branch.

---

## 1. Fluxo de trabalho: GitHub Flow

A `main` contém sempre uma versão estável. **Depois da preparação inicial do repositório, ninguém envia
commits direto para a `main`.** Toda mudança segue estes passos:

1. Atualize a `main` local.
2. Crie uma **branch curta** para uma única tarefa.
3. Faça commits pequenos e com mensagens claras.
4. Envie a branch e abra um **Pull Request**.
5. **Outra pessoa da equipe** revisa e aprova.
6. Os testes do **GitHub Actions** (`testes.yml`) precisam passar.
7. Faça o merge e apague a branch.

### Nomes de branch

| Prefixo | Quando usar | Exemplo |
|---|---|---|
| `feat/` | Funcionalidade nova | `feat/intencao-pagamento` |
| `fix/` | Correção de bug | `fix/data-reserva-domingo` |
| `test/` | Testes novos ou ajustados | `test/casos-fora-do-escopo` |
| `docs/` | Documentação | `docs/readme-resultados` |
| `chore/` | Manutenção, configuração, dependências | `chore/atualiza-requirements` |

Use letras minúsculas, sem acentos, com palavras separadas por hífen. Uma branch deve durar poucos dias.
Se estiver crescendo demais, divida o trabalho.

---

## 2. Comandos do dia a dia

```bash
# 1. Atualizar a main
git switch main
git pull origin main

# 2. Criar a branch da tarefa
git switch -c feat/intencao-pagamento

# 3. Conferir o que mudou
git status
git diff

# 4. Adicionar PELO NOME do arquivo
git add dados/base_conhecimento.json
git add testes/test_dialogo.py

# 5. Commitar
git commit -m "feat(dados): adiciona intencao de pagamento via PIX"

# 6. Enviar a branch
git push -u origin feat/intencao-pagamento
```

> ⚠️ **Nunca use `git add .` nem `git add -A`.** Adicionar arquivo por arquivo evita que `.venv/`,
> `__pycache__/`, `modelos/*.joblib`, logs ou arquivos pessoais entrem no repositório por engano.
> Antes de cada commit, confira com `git status` o que está preparado.

Se a `main` avançou enquanto você trabalhava, atualize a sua branch:

```bash
git switch main
git pull origin main
git switch feat/intencao-pagamento
git merge main
```

---

## 3. Mensagens de commit: Conventional Commits em português

Formato:

```
<tipo>(<escopo>): <descrição no imperativo, em minúsculas, sem ponto final>
```

Exemplos:

```
feat(dialogo): adiciona encaminhamento humano apos duas falhas seguidas
fix(entidades): corrige leitura de horario no formato "8 da noite"
test(avaliacao): inclui casos ambiguos de cardapio e reserva
docs(readme): atualiza resultados da v1.0
```

### Tipos

| Tipo | Uso |
|---|---|
| `feat` | Nova funcionalidade |
| `fix` | Correção de bug |
| `test` | Criação ou ajuste de testes |
| `docs` | Documentação |
| `refactor` | Mudança de código sem alterar o comportamento |
| `style` | Formatação, espaços, nomes (sem mudar a lógica) |
| `chore` | Manutenção, configuração, dependências |
| `ci` | Mudanças no GitHub Actions |

### Escopos usados no projeto

| Escopo | Abrange |
|---|---|
| `nucleo` | Estrutura geral do pacote `chatbot/`, pré-processamento e configuração |
| `modelo` | `chatbot/modelo.py`, treino e classificador |
| `dados` | `dados/base_conhecimento.json` |
| `entidades` | `chatbot/entidades.py` |
| `conhecimento` | `chatbot/conhecimento.py` |
| `dialogo` | `chatbot/dialogo.py` e a política de decisão |
| `api` | Rotas do `app.py` |
| `interface` | `templates/` e `static/` |
| `avaliacao` | `avaliar.py` e os casos de teste |
| `resultados` | Métricas e gráficos gerados |
| `readme` | `README.md` |
| `changelog` | `CHANGELOG.md` |

O escopo é opcional quando a mudança é geral (ex.: `chore: atualiza .gitignore`).

---

## 4. Pull Requests

### Regras

- Um PR resolve **uma** tarefa. PRs pequenos são revisados mais rápido.
- Título no mesmo padrão dos commits: `feat(dados): adiciona intencao de pagamento via PIX`.
- Na descrição, diga **o que** mudou, **por que** mudou e **como testar**.
- Se mexer em dados, modelo ou diálogo, cole a saída do `python avaliar.py` antes e depois da mudança.
- É preciso **aprovação de outra pessoa da equipe**. Ninguém aprova o próprio PR.
- O check do **GitHub Actions** precisa estar verde.
- Faça o merge com **Create a merge commit**. Não use *Squash* nem *Rebase*, para preservar o histórico
  dos commits.
- Depois do merge, apague a branch no GitHub e localmente (`git branch -d <branch>`).

### Checklist do revisor

- [ ] O título e os commits seguem o padrão Conventional Commits.
- [ ] O check do GitHub Actions passou.
- [ ] Rodei `python -m pytest` localmente e os testes passaram.
- [ ] Se o PR mexe em **dados, modelo ou diálogo**: rodei `python treinar.py` e `python avaliar.py` e as
      métricas não pioraram (ou a piora foi justificada na descrição).
- [ ] **Não entraram** no PR: `.venv/`, `__pycache__/`, `*.pyc` nem `modelos/*.joblib`.
- [ ] Sem senhas, tokens, arquivos `.env` nem dados pessoais.
- [ ] O código segue a PEP 8 e os nomes estão em português, como no restante do projeto.
- [ ] README/CHANGELOG atualizados, se a mudança altera comportamento ou métricas.

---

## 5. Estilo de código

- Siga a **[PEP 8](https://peps.python.org/pep-0008/)**: 4 espaços de indentação, `snake_case` para funções e
  variáveis, `MAIUSCULAS` para constantes (como em `chatbot/config.py`) e `PascalCase` para classes.
- Os nomes de funções, variáveis e comentários ficam em **português**, sem acentos nos identificadores.
- Escreva docstrings curtas explicando o que cada função faz.
- Limiares e caminhos ficam em `chatbot/config.py`, nunca espalhados pelo código.
- Respeite o `.editorconfig` do repositório (codificação UTF-8, fim de linha e espaços).

---

## 6. Uso de IA generativa

A equipe pode usar ferramentas de IA generativa, como o **Claude, da Anthropic**, como apoio para revisar
código, sugerir testes e redigir documentação, desde que:

- quem abre o PR **leia, entenda e teste** todo conteúdo gerado antes de enviar;
- o uso relevante seja **mencionado na descrição do PR** (ex.: "testes sugeridos com apoio do Claude e
  revisados por mim");
- nenhum dado sensível ou pessoal seja colado nessas ferramentas.

A responsabilidade pelo código e pelos resultados é sempre da equipe.
