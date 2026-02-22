> **Note:** This is an auto-translated version of the original English documentation.
> If there are any discrepancies, the [English version](../../README.md) takes precedence.
> **Nota:** Esta é uma versão autotraduzida da documentação original em inglês.
> Em caso de discrepâncias, a [versão em inglês](../../README.md) prevalece.

# claude-code-discord-bridge

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Execute múltiplas sessões do Claude Code em paralelo — com segurança — pelo Discord.**

Cada thread do Discord vira uma sessão isolada do Claude Code. Inicie quantas precisar: trabalhe em uma feature em uma thread, revise um PR em outra, execute uma tarefa agendada em uma terceira. O bridge cuida da coordenação automaticamente para que sessões simultâneas não interfiram entre si.

**[English](../../README.md)** | **[日本語](../ja/README.md)** | **[简体中文](../zh-CN/README.md)** | **[한국어](../ko/README.md)** | **[Español](../es/README.md)** | **[Français](../fr/README.md)**

> **Aviso:** Este projeto não é afiliado, endossado ou oficialmente conectado à Anthropic. "Claude" e "Claude Code" são marcas registradas da Anthropic, PBC. Esta é uma ferramenta open source independente que interage com o Claude Code CLI.

> **Construído inteiramente pelo Claude Code.** Todo este código base — arquitetura, implementação, testes, documentação — foi escrito pelo Claude Code. O autor humano forneceu requisitos e direção em linguagem natural, mas não leu nem editou manualmente o código fonte. Veja [Como este projeto foi construído](#como-este-projeto-foi-construído).

---

## A Grande Ideia: Sessões Paralelas Sem Medo

Quando você envia tarefas ao Claude Code em threads separadas do Discord, o bridge faz três coisas automaticamente:

1. **Injeção de aviso de concorrência** — O prompt de sistema de cada sessão inclui instruções obrigatórias: crie um git worktree, trabalhe apenas dentro dele, nunca toque diretamente no diretório de trabalho principal.

2. **Registro de sessões ativas** — Cada sessão em execução conhece as outras. Se duas sessões estiverem prestes a tocar no mesmo repositório, elas podem se coordenar ao invés de conflitar.

3. **Canal de coordenação** — Um canal compartilhado do Discord onde as sessões transmitem eventos de início/fim. Tanto o Claude quanto humanos podem ver de relance o que está acontecendo em todas as threads ativas.

```
Thread A (feature)    ──→  Claude Code (worktree-A)
Thread B (revisão PR) ──→  Claude Code (worktree-B)
Thread C (docs)       ──→  Claude Code (worktree-C)
           ↓ eventos de ciclo de vida
   #canal-coordenação
   "A: iniciando refactor de autenticação"
   "B: revisando PR #42"
   "C: atualizando README"
```

Sem race conditions. Sem trabalho perdido. Sem surpresas no merge.

---

## O Que Você Pode Fazer

### Chat Interativo (Mobile / Desktop)

Use o Claude Code de qualquer lugar onde o Discord funcione — celular, tablet ou desktop. Cada mensagem cria ou continua uma thread, mapeada 1:1 para uma sessão persistente do Claude Code.

### Desenvolvimento Paralelo

Abra múltiplas threads simultaneamente. Cada uma é uma sessão independente do Claude Code com seu próprio contexto, diretório de trabalho e git worktree. Padrões úteis:

- **Feature + revisão em paralelo**: Inicie uma feature em uma thread enquanto o Claude revisa um PR em outra.
- **Múltiplos colaboradores**: Diferentes membros do time têm sua própria thread; as sessões ficam cientes umas das outras via o canal de coordenação.
- **Experimente com segurança**: Tente uma abordagem na thread A enquanto mantém a thread B no código estável.

### Tarefas Agendadas (SchedulerCog)

Registre tarefas periódicas do Claude Code a partir de uma conversa no Discord ou via REST API — sem mudanças de código, sem redeploys. As tarefas são armazenadas no SQLite e executadas conforme um agendamento configurável. O Claude pode auto-registrar tarefas durante uma sessão usando `POST /api/tasks`.

```
/skill name:goodmorning         → executa imediatamente
Claude chama POST /api/tasks   → registra tarefa periódica
SchedulerCog (loop a cada 30s) → dispara tarefas no horário certo
```

### Automação CI/CD

Acione tarefas do Claude Code a partir do GitHub Actions via webhooks do Discord. O Claude roda autonomamente — lê código, atualiza docs, cria PRs, ativa auto-merge.

```
GitHub Actions → Discord Webhook → Bridge → Claude Code CLI
                                                  ↓
GitHub PR ←── git push ←── Claude Code ──────────┘
```

**Exemplo real:** A cada push para `main`, o Claude analisa o diff, atualiza documentação em inglês + japonês, cria um PR com resumo bilíngue e ativa o auto-merge. Zero interação humana.

### Sincronização de Sessões

Já usa o Claude Code CLI diretamente? Sincronize suas sessões de terminal existentes em threads do Discord com `/sync-sessions`. Preenche mensagens recentes de conversa para que você possa continuar uma sessão CLI pelo celular sem perder contexto.

### Criação Programática de Sessões

Crie novas sessões do Claude Code a partir de scripts, GitHub Actions ou outras sessões do Claude — sem interação com mensagens do Discord.

```bash
# De outra sessão do Claude ou um script CI:
curl -X POST "$CCDB_API_URL/api/spawn" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Executar scan de segurança no repositório", "thread_name": "Scan de Segurança"}'
# Retorna imediatamente com o ID da thread; Claude roda em segundo plano
```

Subprocessos do Claude recebem `DISCORD_THREAD_ID` como variável de ambiente, então uma sessão em execução pode criar sessões filhas para paralelizar o trabalho.

### Retomada ao Iniciar

Se o bot reiniciar no meio de uma sessão, as sessões do Claude interrompidas são automaticamente retomadas quando o bot volta online. As sessões são marcadas para retomada de três formas:

- **Automático (reinício por atualização)** — `AutoUpgradeCog` tira um snapshot de todas as sessões ativas logo antes de um reinício por atualização de pacote e as marca automaticamente.
- **Automático (qualquer encerramento)** — `ClaudeChatCog.cog_unload()` marca todas as sessões em execução quando o bot encerra por qualquer mecanismo (`systemctl stop`, `bot.close()`, SIGTERM, etc.).
- **Manual** — Qualquer sessão pode chamar `POST /api/mark-resume` diretamente.

---

## Funcionalidades

### Chat Interativo
- **Thread = Session** — Mapeamento 1:1 entre thread do Discord e sessão do Claude Code
- **Status em tempo real** — Reações emoji: 🧠 pensando, 🛠️ lendo arquivos, 💻 editando, 🌐 pesquisa web
- **Texto em streaming** — Texto intermediário do assistente aparece enquanto o Claude trabalha
- **Embeds de resultados de ferramentas** — Resultados ao vivo com tempo decorrido aumentando a cada 10s
- **Pensamento estendido** — Raciocínio exibido como embeds com spoiler (clique para revelar)
- **Persistência de sessão** — Retoma conversas entre mensagens via `--resume`
- **Execução de skills** — Comando `/skill` com autocomplete, argumentos opcionais, retomada dentro da thread
- **Hot reload** — Novos skills adicionados a `~/.claude/skills/` são detectados automaticamente (atualização a cada 60s, sem reinício)
- **Sessões concorrentes** — Múltiplas sessões paralelas com limite configurável
- **Parar sem limpar** — `/stop` para uma sessão preservando-a para retomada
- **Suporte a anexos** — Arquivos de texto adicionados automaticamente ao prompt (até 5 × 50 KB)
- **Notificações de timeout** — Embed com tempo decorrido e guia de retomada ao atingir timeout
- **Perguntas interativas** — `AskUserQuestion` renderiza como Botões do Discord ou Menu de Seleção; a sessão retoma com sua resposta; botões sobrevivem a reinícios do bot
- **Painel de threads** — Embed fixado ao vivo mostrando quais threads estão ativas vs. aguardando; owner é @mencionado quando input é necessário
- **Uso de tokens** — Taxa de acerto de cache e contagem de tokens exibidos no embed de sessão completa

### Concorrência e Coordenação
- **Instruções de worktree auto-injetadas** — Cada sessão recebe instruções para usar `git worktree` antes de tocar em qualquer arquivo
- **Limpeza automática de worktree** — Worktrees de sessão (`wt-{thread_id}`) são removidos automaticamente ao final da sessão e na inicialização do bot; worktrees com alterações nunca são removidos automaticamente (invariante de segurança)
- **Registro de sessões ativas** — Registro em memória; cada sessão vê o que as outras estão fazendo
- **Canal de coordenação** — Canal compartilhado opcional para transmissões de ciclo de vida entre sessões
- **Scripts de coordenação** — O Claude pode chamar `coord_post.py` / `coord_read.py` de dentro de uma sessão para postar e ler eventos

### Tarefas Agendadas
- **SchedulerCog** — Executor de tarefas periódicas com suporte SQLite e um loop mestre de 30 segundos
- **Auto-registro** — O Claude registra tarefas via `POST /api/tasks` durante uma sessão de chat
- **Sem mudanças de código** — Adiciona, remove ou modifica tarefas em tempo de execução
- **Ativar/desativar** — Pausa tarefas sem excluí-las (`PATCH /api/tasks/{id}`)

### Automação CI/CD
- **Disparadores webhook** — Aciona tarefas do Claude Code a partir do GitHub Actions ou qualquer sistema CI/CD
- **Auto-atualização** — Atualiza automaticamente o bot quando pacotes upstream são publicados
- **Reinício com drenagem** — Aguarda sessões ativas terminarem antes de reiniciar
- **Marcação automática de retomada** — Sessões ativas são automaticamente marcadas para retomada em qualquer encerramento (reinício por atualização via `AutoUpgradeCog`, ou qualquer outro encerramento via `ClaudeChatCog.cog_unload()`); retomam de onde pararam após o reinício do bot
- **Aprovação de reinício** — Portão opcional para confirmar atualizações antes de aplicá-las

### Gerenciamento de Sessões
- **Sincronização de sessões** — Importa sessões CLI como threads do Discord (`/sync-sessions`)
- **Lista de sessões** — `/sessions` com filtragem por origem (Discord / CLI / todas) e janela de tempo
- **Informações de retomada** — `/resume-info` mostra o comando CLI para continuar a sessão atual em um terminal
- **Retomada ao iniciar** — Sessões interrompidas reiniciam automaticamente após qualquer reinício do bot; `AutoUpgradeCog` (reinícios por atualização) e `ClaudeChatCog.cog_unload()` (todos os outros encerramentos) as marcam automaticamente, ou use `POST /api/mark-resume` manualmente
- **Criação programática** — `POST /api/spawn` cria uma nova thread do Discord + sessão do Claude de qualquer script ou subprocesso do Claude; retorna um 201 não bloqueante imediatamente após a criação da thread
- **Injeção de ID da thread** — A variável de ambiente `DISCORD_THREAD_ID` é passada para cada subprocesso do Claude, permitindo que sessões criem sessões filhas via `$CCDB_API_URL/api/spawn`
- **Gerenciamento de worktree** — `/worktree-list` mostra todos os worktrees de sessão ativos com status limpo/sujo; `/worktree-cleanup` remove worktrees limpos órfãos (suporta preview com `dry_run`)

### Segurança
- **Sem injeção de shell** — Apenas `asyncio.create_subprocess_exec`, nunca `shell=True`
- **Validação de ID de sessão** — Regex estrito antes de passar para `--resume`
- **Prevenção de injeção de flags** — Separador `--` antes de todos os prompts
- **Isolamento de segredos** — Token do bot removido do ambiente do subprocesso
- **Autorização de usuário** — `allowed_user_ids` restringe quem pode invocar o Claude

---

## Início Rápido

### Requisitos

- Python 3.10+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) instalado e autenticado
- Token de bot Discord com Message Content intent habilitado
- [uv](https://docs.astral.sh/uv/) (recomendado) ou pip

### Execução autônoma

```bash
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge

cp .env.example .env
# Edite .env com seu token de bot e ID do canal

uv run python -m claude_discord.main
```

### Instalar como pacote

Se você já tem um bot discord.py rodando (Discord permite apenas uma conexão Gateway por token):

```bash
uv add git+https://github.com/ebibibi/claude-code-discord-bridge.git
```

```python
from discord.ext import commands
from claude_discord import ClaudeRunner, setup_bridge

bot = commands.Bot(...)
runner = ClaudeRunner(command="claude", model="sonnet")

@bot.event
async def on_ready():
    await setup_bridge(
        bot,
        runner,
        claude_channel_id=YOUR_CHANNEL_ID,
        allowed_user_ids={YOUR_USER_ID},
    )
```

`setup_bridge()` conecta todos os Cogs automaticamente. Novos Cogs adicionados ao ccdb são incluídos sem mudanças no código do consumidor.

Atualizar para a última versão:

```bash
uv lock --upgrade-package claude-code-discord-bridge && uv sync
```

---

## Configuração

| Variável | Descrição | Padrão |
|----------|-----------|--------|
| `DISCORD_BOT_TOKEN` | Seu token de bot Discord | (obrigatório) |
| `DISCORD_CHANNEL_ID` | ID do canal para o chat do Claude | (obrigatório) |
| `CLAUDE_COMMAND` | Caminho para o Claude Code CLI | `claude` |
| `CLAUDE_MODEL` | Modelo a usar | `sonnet` |
| `CLAUDE_PERMISSION_MODE` | Modo de permissão do CLI | `acceptEdits` |
| `CLAUDE_WORKING_DIR` | Diretório de trabalho para o Claude | diretório atual |
| `MAX_CONCURRENT_SESSIONS` | Máximo de sessões paralelas | `3` |
| `SESSION_TIMEOUT_SECONDS` | Timeout de inatividade da sessão | `300` |
| `DISCORD_OWNER_ID` | ID do usuário para @mencionar quando o Claude precisa de input | (opcional) |
| `COORDINATION_CHANNEL_ID` | ID do canal para transmissões de eventos entre sessões | (opcional) |
| `CCDB_COORDINATION_CHANNEL_NAME` | Criar automaticamente canal de coordenação por nome | (opcional) |
| `WORKTREE_BASE_DIR` | Diretório base para escanear worktrees de sessão (ativa limpeza automática) | (opcional) |

---

## Configuração do Bot Discord

1. Crie uma nova aplicação no [Portal do Desenvolvedor Discord](https://discord.com/developers/applications)
2. Crie um bot e copie o token
3. Ative **Message Content Intent** em Privileged Gateway Intents
4. Convide o bot com estas permissões:
   - Send Messages
   - Create Public Threads
   - Send Messages in Threads
   - Add Reactions
   - Manage Messages (para limpeza de reações)
   - Read Message History

---

## GitHub + Automação com Claude Code

### Exemplo: Sincronização Automática de Documentação

A cada push para `main`, o Claude Code:
1. Puxa as últimas mudanças e analisa o diff
2. Atualiza a documentação em inglês
3. Traduz para japonês (ou qualquer idioma alvo)
4. Cria um PR com resumo bilíngue
5. Ativa o auto-merge — faz merge automaticamente quando o CI passa

**GitHub Actions:**

```yaml
# .github/workflows/docs-sync.yml
name: Documentation Sync
on:
  push:
    branches: [main]
jobs:
  trigger:
    if: "!contains(github.event.head_commit.message, '[docs-sync]')"
    runs-on: ubuntu-latest
    steps:
      - run: |
          curl -X POST "${{ secrets.DISCORD_WEBHOOK_URL }}" \
            -H "Content-Type: application/json" \
            -d '{"content": "🔄 docs-sync"}'
```

**Configuração do bot:**

```python
from claude_discord import WebhookTriggerCog, WebhookTrigger, ClaudeRunner

runner = ClaudeRunner(command="claude", model="sonnet")

triggers = {
    "🔄 docs-sync": WebhookTrigger(
        prompt="Analise mudanças, atualize docs, crie um PR com resumo bilíngue, ative auto-merge.",
        working_dir="/home/user/my-project",
        timeout=600,
    ),
}

await bot.add_cog(WebhookTriggerCog(
    bot=bot,
    runner=runner,
    triggers=triggers,
    channel_ids={YOUR_CHANNEL_ID},
))
```

**Segurança:** Prompts são definidos no lado do servidor. Webhooks apenas selecionam qual disparador acionar — sem injeção arbitrária de prompts.

### Exemplo: Auto-aprovação de PRs do Proprietário

```yaml
# .github/workflows/auto-approve.yml
name: Auto Approve Owner PRs
on:
  pull_request:
    types: [opened, synchronize, reopened]
jobs:
  auto-approve:
    if: github.event.pull_request.user.login == 'your-username'
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
      contents: write
    steps:
      - env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          PR_NUMBER: ${{ github.event.pull_request.number }}
        run: |
          gh pr review "$PR_NUMBER" --repo "$GITHUB_REPOSITORY" --approve
          gh pr merge "$PR_NUMBER" --repo "$GITHUB_REPOSITORY" --auto --squash
```

---

## Tarefas Agendadas

Registre tarefas periódicas do Claude Code em tempo de execução — sem mudanças de código, sem redeploys.

De dentro de uma sessão no Discord, o Claude pode registrar uma tarefa:

```bash
# Claude chama isso dentro de uma sessão:
curl -X POST "$CCDB_API_URL/api/tasks" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Verificar dependências desatualizadas e abrir uma issue se encontradas", "interval_seconds": 604800}'
```

Ou registre a partir dos seus próprios scripts:

```bash
curl -X POST http://localhost:8080/api/tasks \
  -H "Authorization: Bearer your-secret" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Scan semanal de segurança", "interval_seconds": 604800}'
```

O loop mestre de 30 segundos detecta tarefas pendentes e cria sessões do Claude Code automaticamente.

---

## Auto-atualização

Atualize automaticamente o bot quando uma nova versão é publicada:

```python
from claude_discord import AutoUpgradeCog, UpgradeConfig

config = UpgradeConfig(
    package_name="claude-code-discord-bridge",
    trigger_prefix="🔄 bot-upgrade",
    working_dir="/home/user/my-bot",
    restart_command=["sudo", "systemctl", "restart", "my-bot.service"],
    restart_approval=True,  # Reaja com ✅ para confirmar o reinício
)

await bot.add_cog(AutoUpgradeCog(bot, config))
```

Antes de reiniciar, o `AutoUpgradeCog`:

1. **Tira snapshot das sessões ativas** — Coleta todas as threads com sessões do Claude em execução (duck typing: qualquer Cog com dict `_active_runners` é descoberto automaticamente).
2. **Drena** — Aguarda as sessões ativas terminarem naturalmente.
3. **Marca para retomada** — Salva IDs de threads ativas na tabela de retomadas pendentes. No próximo início, essas sessões são retomadas automaticamente com um prompt "bot reiniciado, por favor continue".
4. **Reinicia** — Executa o comando de reinício configurado.

Qualquer Cog com uma propriedade `active_count` é descoberto automaticamente e drenado:

```python
class MyCog(commands.Cog):
    @property
    def active_count(self) -> int:
        return len(self._running_tasks)
```

> **Cobertura:** `AutoUpgradeCog` cobre reinícios por atualização. Para *todos os outros* encerramentos (`systemctl stop`, `bot.close()`, SIGTERM), `ClaudeChatCog.cog_unload()` fornece uma segunda rede de segurança automática.

---

## REST API

REST API opcional para notificações e gerenciamento de tarefas. Requer aiohttp:

```bash
uv add "claude-code-discord-bridge[api]"
```

### Endpoints

| Método | Caminho | Descrição |
|--------|---------|-----------|
| GET | `/api/health` | Verificação de saúde |
| POST | `/api/notify` | Enviar notificação imediata |
| POST | `/api/schedule` | Agendar uma notificação |
| GET | `/api/scheduled` | Listar notificações pendentes |
| DELETE | `/api/scheduled/{id}` | Cancelar uma notificação |
| POST | `/api/tasks` | Registrar uma tarefa agendada do Claude Code |
| GET | `/api/tasks` | Listar tarefas registradas |
| DELETE | `/api/tasks/{id}` | Remover uma tarefa |
| PATCH | `/api/tasks/{id}` | Atualizar uma tarefa (ativar/desativar, mudar agendamento) |
| POST | `/api/spawn` | Criar nova thread do Discord e iniciar sessão do Claude Code (não bloqueante) |
| POST | `/api/mark-resume` | Marcar thread para retomada automática no próximo início do bot |

```bash
# Enviar notificação
curl -X POST http://localhost:8080/api/notify \
  -H "Authorization: Bearer your-secret" \
  -H "Content-Type: application/json" \
  -d '{"message": "Build com sucesso!", "title": "CI/CD"}'

# Registrar tarefa recorrente
curl -X POST http://localhost:8080/api/tasks \
  -H "Authorization: Bearer your-secret" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Resumo diário de standup", "interval_seconds": 86400}'
```

---

## Arquitetura

```
claude_discord/
  main.py                  # Ponto de entrada autônomo
  setup.py                 # setup_bridge() — conexão de Cogs com uma chamada
  bot.py                   # Classe Discord Bot
  concurrency.py           # Instruções de worktree + registro de sessões ativas
  cogs/
    claude_chat.py         # Chat interativo (criação de threads, manipulação de mensagens)
    skill_command.py       # Comando slash /skill com autocomplete
    session_manage.py      # /sessions, /sync-sessions, /resume-info
    scheduler.py           # Executor de tarefas periódicas do Claude Code
    webhook_trigger.py     # Webhook → tarefa do Claude Code (CI/CD)
    auto_upgrade.py        # Webhook → atualização de pacote + reinício com drenagem
    event_processor.py     # EventProcessor — máquina de estados para eventos stream-json
    run_config.py          # RunConfig dataclass — agrupa todos os parâmetros de execução CLI
    _run_helper.py         # Camada de orquestração fina
  claude/
    runner.py              # Gerenciador de subprocessos Claude CLI
    parser.py              # Parser de eventos stream-json
    types.py               # Definições de tipos para mensagens SDK
  coordination/
    service.py             # Publica eventos de ciclo de vida de sessão no canal compartilhado
  database/
    models.py              # Schema SQLite
    repository.py          # CRUD de sessões
    task_repo.py           # CRUD de tarefas agendadas
    ask_repo.py            # CRUD de AskUserQuestion pendentes
    notification_repo.py   # CRUD de notificações agendadas
    resume_repo.py         # CRUD de retomada ao iniciar
    settings_repo.py       # Configurações por servidor
  discord_ui/
    status.py              # Gerenciador de reações emoji (com debounce)
    chunker.py             # Divisão de mensagens com conhecimento de blocos e tabelas
    embeds.py              # Construtores de embeds do Discord
    ask_view.py            # Botões/Menus de Seleção para AskUserQuestion
    ask_handler.py         # collect_ask_answers() — UI + ciclo de vida DB de AskUserQuestion
    streaming_manager.py   # StreamingMessageManager — edições de mensagem in-place com debounce
    tool_timer.py          # LiveToolTimer — contador de tempo decorrido para ferramentas longas
    thread_dashboard.py    # Embed fixado ao vivo mostrando estados de sessão
  session_sync.py          # Descoberta e importação de sessões CLI
  worktree.py              # WorktreeManager — ciclo de vida seguro de git worktree
  ext/
    api_server.py          # REST API (opcional, requer aiohttp)
  utils/
    logger.py              # Configuração de logging
```

### Filosofia de Design

- **Invocação CLI, não API** — Invoca `claude -p --output-format stream-json`, dando recursos completos do Claude Code (CLAUDE.md, skills, ferramentas, memória) sem reimplementá-los
- **Concorrência primeiro** — Múltiplas sessões simultâneas são o caso esperado, não um edge case; cada sessão recebe instruções de worktree, o registro e o canal de coordenação cuidam do resto
- **Discord como cola** — Discord fornece UI, threads, reações, webhooks e notificações persistentes; sem frontend personalizado necessário
- **Framework, não aplicação** — Instale como pacote, adicione Cogs ao seu bot existente, configure via código
- **Extensibilidade sem código** — Adicione tarefas agendadas e disparadores webhook sem tocar no código fonte
- **Segurança pela simplicidade** — ~3000 linhas de Python auditáveis; apenas subprocess exec, sem expansão de shell

---

## Testes

```bash
uv run pytest tests/ -v --cov=claude_discord
```

470+ testes cobrindo parser, chunker, repositório, runner, streaming, disparadores webhook, auto-atualização, REST API, UI do AskUserQuestion, painel de threads, tarefas agendadas e sincronização de sessões.

---

## Como Este Projeto Foi Construído

**Todo este código base foi escrito pelo [Claude Code](https://docs.anthropic.com/en/docs/claude-code)**, o agente de codificação com IA da Anthropic. O autor humano ([@ebibibi](https://github.com/ebibibi)) forneceu requisitos e direção em linguagem natural, mas não leu nem editou manualmente o código fonte.

Isso significa:

- **Todo o código foi gerado por IA** — arquitetura, implementação, testes, documentação
- **O autor humano não pode garantir correção no nível do código** — revise o fonte se precisar de certeza
- **Relatórios de bugs e PRs são bem-vindos** — Claude Code será usado para resolvê-los
- **Este é um exemplo real de software open source escrito por IA**

O projeto começou em 2026-02-18 e continua evoluindo através de conversas iterativas com Claude Code.

---

## Exemplo Real

**[EbiBot](https://github.com/ebibibi/discord-bot)** — Um bot pessoal do Discord construído sobre este framework. Inclui sincronização automática de documentação (inglês + japonês), notificações push, watchdog do Todoist, verificações de saúde agendadas e CI/CD com GitHub Actions. Use-o como referência para construir seu próprio bot.

---

## Inspirado em

- [OpenClaw](https://github.com/openclaw/openclaw) — Reações emoji de status, debounce de mensagens, divisão com conhecimento de blocos
- [claude-code-discord-bot](https://github.com/timoconnellaus/claude-code-discord-bot) — Abordagem de invocação CLI + stream-json
- [claude-code-discord](https://github.com/zebbern/claude-code-discord) — Padrões de controle de permissões
- [claude-sandbox-bot](https://github.com/RhysSullivan/claude-sandbox-bot) — Modelo de thread por conversa

---

## Licença

MIT
