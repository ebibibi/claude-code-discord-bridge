> **Note:** This is an auto-translated version of the original English documentation.
> If there are any discrepancies, the [English version](../../README.md) takes precedence.
> **Nota:** Esta é uma versão autotraduzida da documentação original em inglês.
> Em caso de discrepâncias, a [versão em inglês](../../README.md) prevalece.

# claude-code-discord-bridge

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Conecta o [Claude Code](https://docs.anthropic.com/en/docs/claude-code) ao Discord e GitHub. Um framework que une o Claude Code CLI com o Discord para **chat interativo, automação CI/CD e integração com fluxos de trabalho do GitHub**.

O Claude Code é ótimo no terminal — mas pode fazer muito mais. Esta ponte permite que você **use o Claude Code no seu fluxo de desenvolvimento com GitHub**: sincronize documentação automaticamente, revise e mescle PRs, e execute qualquer tarefa do Claude Code acionada pelo GitHub Actions. Tudo através do Discord como cola universal.

**[English](../../README.md)** | **[日本語](../ja/README.md)** | **[简体中文](../zh-CN/README.md)** | **[한국어](../ko/README.md)** | **[Español](../es/README.md)** | **[Français](../fr/README.md)**

> **Aviso:** Este projeto não é afiliado, endossado ou oficialmente conectado à Anthropic. "Claude" e "Claude Code" são marcas registradas da Anthropic, PBC. Esta é uma ferramenta de código aberto independente que se integra ao Claude Code CLI.

> **Construído inteiramente pelo Claude Code.** Este projeto foi projetado, implementado, testado e documentado pelo próprio Claude Code — o agente de codificação de IA da Anthropic. O autor humano não leu o código-fonte. Veja [Como este projeto foi construído](#como-este-projeto-foi-construído) para detalhes.

## Duas formas de usar

### 1. Chat interativo (Mobile / Desktop)

Use o Claude Code pelo celular ou qualquer dispositivo com Discord. Cada conversa vira um thread com persistência de sessão completa.

```
Você (Discord)  →  Bridge  →  Claude Code CLI
      ↑                              ↓
      ←──── saída stream-json ───────←
```

### 2. Automação CI/CD (GitHub → Discord → Claude Code → GitHub)

Acione tarefas do Claude Code a partir do GitHub Actions via webhooks do Discord. O Claude Code executa de forma autônoma — lendo código, atualizando docs, criando PRs e habilitando mesclagem automática.

```
GitHub Actions  →  Discord Webhook  →  Bridge  →  Claude Code CLI
                                                         ↓
GitHub PR (auto-merge)  ←  git push  ←  Claude Code  ←──┘
```

**Exemplo real:** A cada push para main, o Claude Code analisa automaticamente as mudanças, atualiza a documentação em inglês e japonês, cria um PR com resumo bilíngue e habilita mesclagem automática. Sem intervenção humana.

## Funcionalidades

### Chat interativo
- **Thread = Session** — Cada tarefa tem seu próprio thread do Discord, mapeado 1:1 para uma sessão do Claude Code
- **Status em tempo real** — Reações com emoji mostram o que o Claude está fazendo (🧠 pensando, 🛠️ lendo arquivos, 💻 editando, 🌐 pesquisa web)
- **Texto em streaming** — Texto intermediário aparece enquanto o Claude trabalha, não apenas no final
- **Exibição de resultados de ferramentas** — Resultados do uso de ferramentas mostrados como embeds em tempo real
- **Temporização de ferramentas ao vivo** — Embeds de ferramentas em progresso atualizam o tempo decorrido a cada 10s para comandos de longa duração (autenticação, builds), para que você sempre saiba que o Claude ainda está trabalhando
- **Pensamento estendido** — O raciocínio do Claude aparece como embeds com tag spoiler (clique para revelar)
- **Persistência de sessão** — Continue conversas entre mensagens com `--resume`
- **Execução de skills** — Execute skills do Claude Code com `/skill` com autocompletar, argumentos opcionais e retomada em thread
- **Sessões simultâneas** — Execute múltiplas sessões em paralelo (limite configurável)
- **Parar sem limpar** — `/stop` interrompe uma sessão em execução preservando-a para retomada
- **Suporte a anexos** — Anexos de texto são adicionados automaticamente ao prompt (até 5 arquivos, 50 KB cada)
- **Notificações de timeout** — Embed dedicado com segundos decorridos e orientações quando uma sessão expira
- **Perguntas interativas** — Quando o Claude chama `AskUserQuestion`, o bot renderiza Botões do Discord ou um Select Menu e retoma a sessão com sua resposta
- **Painel de status da sessão** — Um embed fixado ao vivo no canal principal mostra quais threads estão processando vs. aguardando entrada; o proprietário é @mencionado quando o Claude precisa de uma resposta
- **Coordenação multissessão** — Com `COORDINATION_CHANNEL_ID` configurado, cada sessão transmite eventos de início/fim para um canal compartilhado para que sessões simultâneas se mantenham cientes umas das outras

### Tarefas agendadas (SchedulerCog)
- **Tarefas periódicas do Claude Code** — Registre tarefas via chat do Discord ou API REST; são executadas em um intervalo configurável
- **Baseado em SQLite** — Tarefas persistem entre reinicializações; gerenciadas via endpoints `/api/tasks`
- **Agendamento sem código** — O Claude Code pode auto-registrar novas tarefas com a ferramenta Bash durante uma sessão; sem reinicializações do bot ou mudanças de código
- **Loop mestre único** — Um loop `discord.ext.tasks` de 30 segundos despacha todas as tarefas, mantendo baixa a sobrecarga

### Automação CI/CD
- **Gatilhos de webhook** — Acione tarefas do Claude Code pelo GitHub Actions ou qualquer sistema CI/CD
- **Atualização automática** — Atualize automaticamente o bot quando pacotes upstream são lançados
- **API REST** — Envie notificações e gerencie tarefas agendadas de ferramentas externas (opcional, requer aiohttp)

### Segurança
- **Sem injeção de shell** — Apenas `asyncio.create_subprocess_exec`, nunca `shell=True`
- **Validação de ID de sessão** — Regex estrita antes de passar para `--resume`
- **Prevenção de injeção de flags** — Separador `--` antes de todos os prompts
- **Isolamento de segredos** — Token do bot e segredos removidos do ambiente do subprocesso
- **Autorização de usuários** — `allowed_user_ids` restringe quem pode invocar o Claude

## Skills

Execute [skills do Claude Code](https://docs.anthropic.com/en/docs/claude-code) diretamente do Discord via o comando de barra `/skill`.

```
/skill name:goodmorning                      → executa /goodmorning
/skill name:todoist args:filter "today"      → executa /todoist filter "today"
/skills                                      → lista todas as skills disponíveis
```

**Funcionalidades:**
- **Autocompletar** — Digite para filtrar; nomes e descrições são pesquisáveis
- **Argumentos** — Passe argumentos adicionais via o parâmetro `args`
- **Retomada em thread** — Use `/skill` dentro de um thread Claude existente para executar a skill na sessão atual em vez de criar um novo thread
- **Recarga automática** — Novas skills adicionadas a `~/.claude/skills/` são detectadas automaticamente (intervalo de atualização de 60s, sem reinicialização necessária)

## Início rápido

### Requisitos

- Python 3.10+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) instalado e autenticado
- Token de bot do Discord com Message Content intent habilitado
- [uv](https://docs.astral.sh/uv/) (recomendado) ou pip

### Executar de forma independente

```bash
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge

cp .env.example .env
# Edite .env com seu token de bot e ID do canal

uv run python -m claude_discord.main
```

### Instalar como pacote

Se você já tem um bot discord.py rodando (o Discord permite apenas uma conexão Gateway por token):

```bash
uv add git+https://github.com/ebibibi/claude-code-discord-bridge.git
```

```python
from claude_discord import ClaudeRunner, setup_bridge

runner = ClaudeRunner(command="claude", model="sonnet")

# Uma chamada registra todos os Cogs — novos recursos são incluídos automaticamente
await setup_bridge(
    bot,
    runner,
    session_db_path="data/sessions.db",
    claude_channel_id=YOUR_CHANNEL_ID,
    allowed_user_ids={YOUR_USER_ID},
)
```

`setup_bridge()` conecta automaticamente `ClaudeChatCog`, `SkillCommandCog`, `SessionManageCog` e `SchedulerCog`. Quando novos Cogs são adicionados ao ccdb, aparecem automaticamente — sem mudanças de código no consumidor.

<details>
<summary>Conexão manual (avançado)</summary>

```python
from claude_discord import ClaudeChatCog, ClaudeRunner, SessionRepository
from claude_discord.database.models import init_db

await init_db("data/sessions.db")
repo = SessionRepository("data/sessions.db")
runner = ClaudeRunner(command="claude", model="sonnet")

await bot.add_cog(ClaudeChatCog(bot, repo, runner))
```
</details>

Atualizar para a versão mais recente:

```bash
uv lock --upgrade-package claude-code-discord-bridge && uv sync
```

## Configuração

| Variável | Descrição | Padrão |
|----------|-----------|--------|
| `DISCORD_BOT_TOKEN` | Token do bot do Discord | (obrigatório) |
| `DISCORD_CHANNEL_ID` | ID do canal para chat do Claude | (obrigatório) |
| `CLAUDE_COMMAND` | Caminho para o Claude Code CLI | `claude` |
| `CLAUDE_MODEL` | Modelo a usar | `sonnet` |
| `CLAUDE_PERMISSION_MODE` | Modo de permissão para CLI | `acceptEdits` |
| `CLAUDE_WORKING_DIR` | Diretório de trabalho para Claude | diretório atual |
| `MAX_CONCURRENT_SESSIONS` | Máximo de sessões paralelas | `3` |
| `SESSION_TIMEOUT_SECONDS` | Timeout de inatividade de sessão | `300` |
| `DISCORD_OWNER_ID` | ID de usuário do Discord para @menção quando Claude precisa de entrada | (opcional) |
| `COORDINATION_CHANNEL_ID` | ID do canal para broadcasts de coordenação multissessão | (opcional) |

## Configuração do bot do Discord

1. Crie um novo aplicativo no [Portal do desenvolvedor Discord](https://discord.com/developers/applications)
2. Crie um bot e copie o token
3. Habilite **Message Content Intent** em Privileged Gateway Intents
4. Convide o bot para seu servidor com estas permissões:
   - Send Messages
   - Create Public Threads
   - Send Messages in Threads
   - Add Reactions
   - Manage Messages (para limpeza de reações)
   - Read Message History

## Automação GitHub + Claude Code

O sistema de gatilhos de webhook permite criar fluxos de trabalho CI/CD totalmente autônomos onde o Claude Code age como um agente inteligente — não apenas executando scripts, mas entendendo mudanças de código e tomando decisões.

### Exemplo: Sincronização automática de documentação

A cada push para main, o Claude Code:
1. Busca as últimas mudanças e analisa o diff
2. Atualiza a documentação em inglês se o código-fonte mudou
3. Traduz para japonês (ou qualquer idioma alvo)
4. Cria um PR com resumo bilíngue
5. Habilita mesclagem automática — PR mescla automaticamente quando CI passa

**Fluxo de trabalho do GitHub Actions:**

```yaml
# .github/workflows/docs-sync.yml
name: Documentation Sync
on:
  push:
    branches: [main]
jobs:
  trigger:
    # Ignora commits do próprio docs-sync (prevenção de loop infinito)
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
        prompt="Analise mudanças, atualize docs, crie um PR com resumo bilíngue, habilite auto-merge.",
        working_dir="/home/user/my-project",
        timeout=600,
    ),
    "🚀 deploy": WebhookTrigger(
        prompt="Faça deploy para o ambiente de staging.",
        timeout=300,
    ),
}

await bot.add_cog(WebhookTriggerCog(
    bot=bot,
    runner=runner,
    triggers=triggers,
    channel_ids={YOUR_CHANNEL_ID},
))
```

**Segurança:** Apenas mensagens de webhook são processadas. `allowed_webhook_ids` opcional para controle mais rigoroso. Prompts são definidos no lado do servidor — webhooks apenas selecionam qual gatilho disparar.

### Exemplo: Auto-aprovação de PRs do proprietário

Aprove e mescle automaticamente seus próprios PRs após CI passar:

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

## Tarefas agendadas

`SchedulerCog` executa tarefas periódicas do Claude Code armazenadas no SQLite. As tarefas são registradas em tempo de execução via API REST — sem mudanças de código ou reinicializações do bot.

### Registrar uma tarefa (via API REST)

```bash
curl -X POST http://localhost:8080/api/tasks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secret-token" \
  -d '{
    "name": "daily-standup",
    "prompt": "Verifique issues abertas do GitHub e publique um breve resumo no Discord.",
    "interval_seconds": 86400,
    "channel_id": 123456789
  }'
```

### Registrar uma tarefa (Claude auto-registra durante uma sessão)

O Claude Code pode registrar suas próprias tarefas recorrentes usando a ferramenta Bash — sem configuração manual:

```
# Dentro de uma sessão do Claude Code, o Claude executa:
curl -X POST $CCDB_API_URL/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"name": "health-check", "prompt": "Execute o conjunto de testes e informe os resultados.", "interval_seconds": 3600}'
```

`CCDB_API_URL` é injetado automaticamente no ambiente do subprocesso do Claude quando `api_port` está configurado no `ClaudeRunner`.

## Atualização automática

Atualize automaticamente o bot quando um pacote upstream é lançado.

```python
from claude_discord import AutoUpgradeCog, UpgradeConfig

config = UpgradeConfig(
    package_name="claude-code-discord-bridge",
    trigger_prefix="🔄 bot-upgrade",
    working_dir="/home/user/my-bot",
    restart_command=["sudo", "systemctl", "restart", "my-bot.service"],
)

await bot.add_cog(AutoUpgradeCog(bot, config))
```

**Pipeline:** Push upstream → CI webhook → `🔄 bot-upgrade` → `uv lock --upgrade-package` → `uv sync` → reinicialização do serviço.

### Drenagem elegante (DrainAware)

Antes de reiniciar, AutoUpgradeCog espera todas as sessões ativas terminarem. Qualquer Cog que implemente uma propriedade `active_count` (satisfazendo o protocolo `DrainAware`) é descoberto automaticamente — sem necessidade de lambda `drain_check` manual.

Cogs DrainAware embutidos: `ClaudeChatCog`, `WebhookTriggerCog`.

Para tornar seu próprio Cog compatível com drenagem, basta adicionar uma propriedade `active_count`:

```python
class MyCog(commands.Cog):
    @property
    def active_count(self) -> int:
        return len(self._running_tasks)
```

Você ainda pode passar um callable `drain_check` explícito para sobrescrever o autodescoberta.

### Aprovação de reinicialização

Para cenários de auto-atualização (ex. atualizar o bot a partir de sua própria sessão do Discord), habilite `restart_approval` para evitar reinicializações automáticas:

```python
config = UpgradeConfig(
    package_name="claude-code-discord-bridge",
    trigger_prefix="🔄 bot-upgrade",
    working_dir="/home/user/my-bot",
    restart_command=["sudo", "systemctl", "restart", "my-bot.service"],
    restart_approval=True,
)
```

Com `restart_approval=True`, após atualizar o pacote o bot publica uma mensagem pedindo aprovação. Reaja com ✅ para acionar o reinício. O bot envia lembretes periódicos até aprovação.

## API REST

API REST opcional para enviar notificações ao Discord de ferramentas externas. Requer aiohttp:

```bash
uv add "claude-code-discord-bridge[api]"
```

```python
from claude_discord import NotificationRepository
from claude_discord.ext.api_server import ApiServer

repo = NotificationRepository("data/notifications.db")
await repo.init_db()

api = ApiServer(
    repo=repo,
    bot=bot,
    default_channel_id=YOUR_CHANNEL_ID,
    host="127.0.0.1",
    port=8080,
    api_secret="your-secret-token",  # Autenticação Bearer opcional
)
await api.start()
```

### Endpoints

**Notificações**

| Método | Caminho | Descrição |
|--------|---------|-----------|
| GET | `/api/health` | Verificação de integridade |
| POST | `/api/notify` | Enviar notificação imediata |
| POST | `/api/schedule` | Agendar notificação para mais tarde |
| GET | `/api/scheduled` | Listar notificações pendentes |
| DELETE | `/api/scheduled/{id}` | Cancelar uma notificação agendada |

**Tarefas agendadas** (requer `SchedulerCog`)

| Método | Caminho | Descrição |
|--------|---------|-----------|
| POST | `/api/tasks` | Registrar uma nova tarefa periódica do Claude Code |
| GET | `/api/tasks` | Listar todas as tarefas registradas |
| DELETE | `/api/tasks/{id}` | Remover uma tarefa agendada |
| PATCH | `/api/tasks/{id}` | Atualizar tarefa (habilitar/desabilitar, prompt, intervalo) |

### Exemplos

```bash
# Verificação de integridade
curl http://localhost:8080/api/health

# Enviar notificação
curl -X POST http://localhost:8080/api/notify \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secret-token" \
  -d '{"message": "Build bem-sucedido!", "title": "CI/CD"}'

# Agendar notificação
curl -X POST http://localhost:8080/api/schedule \
  -H "Content-Type: application/json" \
  -d '{"message": "Hora de revisar os PRs", "scheduled_at": "2026-01-01T09:00:00"}'
```

## Arquitetura

```
claude_discord/
  main.py                  # Ponto de entrada independente
  bot.py                   # Classe Discord Bot
  setup.py                 # setup_bridge() — fábrica de chamada única para todos os Cogs
  cogs/
    claude_chat.py         # Chat interativo (criação de threads, tratamento de mensagens)
    skill_command.py       # Comando de barra /skill com autocompletar
    webhook_trigger.py     # Webhook → execução de tarefa Claude Code (CI/CD)
    auto_upgrade.py        # Webhook → atualização de pacote + reinicialização
    scheduler.py           # Tarefas periódicas Claude Code (baseado em SQLite, loop mestre de 30s)
    _run_helper.py         # Lógica de execução compartilhada do Claude CLI
  claude/
    runner.py              # Gerenciador de subprocesso Claude CLI
    parser.py              # Parser de eventos stream-json
    types.py               # Definições de tipo para mensagens SDK
  database/
    models.py              # Esquema SQLite
    repository.py          # Operações CRUD de sessões
    ask_repo.py            # CRUD de AskUserQuestion pendentes (recuperação após reinicialização)
    notification_repo.py   # CRUD de notificações agendadas
    task_repo.py           # CRUD de tarefas agendadas (SchedulerCog)
  coordination/
    service.py             # CoordinationService — publica eventos de ciclo de vida de sessão em canal compartilhado
  discord_ui/
    status.py              # Gerenciador de status de reações emoji (com debounce)
    chunker.py             # Divisão de mensagens com consciência de blocos de código e tabelas
    embeds.py              # Construtores de embeds do Discord
    ask_view.py            # Botões do Discord/Select Menus para AskUserQuestion
    ask_bus.py             # Roteamento de bus para botões AskView persistentes (sobrevive reinicializações)
    thread_dashboard.py    # Embed fixado ao vivo mostrando estados de sessão por thread
  ext/
    api_server.py          # Servidor API REST (opcional, requer aiohttp)
                           # Inclui endpoints /api/tasks para SchedulerCog
  utils/
    logger.py              # Configuração de logging
```

### Filosofia de design

- **Spawn de CLI, não API** — Invocamos `claude -p --output-format stream-json`, obtendo todos os recursos do Claude Code (CLAUDE.md, skills, ferramentas, memória) gratuitamente
- **Discord como cola** — Discord fornece a interface, threading, notificações e infraestrutura de webhooks
- **Framework, não aplicação** — Instale como pacote, adicione Cogs ao seu bot existente, configure via código
- **Segurança pela simplicidade** — ~2500 linhas de Python auditável, sem execução de shell, sem caminhos de código arbitrários

## Testes

```bash
uv run pytest tests/ -v --cov=claude_discord
```

473 testes cobrindo parser, chunker, repositório, runner, streaming, webhook triggers, auto-upgrade, API REST, UI do AskUserQuestion, painel de status de threads, SchedulerCog e repositório de tarefas.

## Como este projeto foi construído

**Todo este código foi escrito pelo [Claude Code](https://docs.anthropic.com/en/docs/claude-code)**, o agente de codificação de IA da Anthropic. O autor humano ([@ebibibi](https://github.com/ebibibi)) forneceu requisitos e direção em linguagem natural, mas não leu ou editou manualmente o código-fonte.

Isso significa:

- **Todo o código foi gerado por IA** — arquitetura, implementação, testes, documentação
- **O autor humano não pode garantir a correção no nível de código** — revise o código-fonte se precisar de certeza
- **Relatórios de bugs e PRs são bem-vindos** — Claude Code provavelmente será usado para abordá-los também
- **Este é um exemplo real de software open source de autoria de IA** — use como referência do que o Claude Code pode construir

O projeto começou em 2026-02-18 e continua evoluindo através de conversas iterativas com o Claude Code.

## Exemplo do mundo real

**[EbiBot](https://github.com/ebibibi/discord-bot)** — Um bot Discord pessoal que usa claude-code-discord-bridge como dependência de pacote. Inclui sincronização automática de documentação (inglês + japonês), notificações push, watchdog do Todoist e integração CI/CD com GitHub Actions. Use como referência para construir seu próprio bot sobre este framework.

## Inspirado em

- [OpenClaw](https://github.com/openclaw/openclaw) — Reações de status com emoji, debouncing de mensagens, chunking com consciência de blocos de código
- [claude-code-discord-bot](https://github.com/timoconnellaus/claude-code-discord-bot) — Abordagem CLI spawn + stream-json
- [claude-code-discord](https://github.com/zebbern/claude-code-discord) — Padrões de controle de permissão
- [claude-sandbox-bot](https://github.com/RhysSullivan/claude-sandbox-bot) — Modelo de thread por conversa

## Licença

MIT
