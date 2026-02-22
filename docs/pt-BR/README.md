> **Note:** This is an auto-translated version of the original English documentation.
> If there are any discrepancies, the [English version](../../README.md) takes precedence.
> **Nota:** Esta é uma versão autotraduzida da documentação original em inglês.
> Em caso de discrepâncias, a [versão em inglês](../../README.md) prevalece.

# claude-code-discord-bridge

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Execute múltiplas sessões do Claude Code em paralelo — com segurança — pelo Discord.**

Cada thread do Discord se torna uma sessão isolada do Claude Code. Abra quantas precisar: trabalhe em uma funcionalidade numa thread, revise um PR em outra, execute uma tarefa agendada em uma terceira. O bridge gerencia a coordenação automaticamente para que sessões simultâneas não interfiram entre si.

**[English](../../README.md)** | **[日本語](../ja/README.md)** | **[简体中文](../zh-CN/README.md)** | **[한국어](../ko/README.md)** | **[Español](../es/README.md)** | **[Français](../fr/README.md)**

> **Aviso:** Este projeto não é afiliado, endossado ou oficialmente conectado à Anthropic. "Claude" e "Claude Code" são marcas registradas da Anthropic, PBC. Esta é uma ferramenta open source independente que interage com o Claude Code CLI.

> **Construído inteiramente pelo Claude Code.** Arquitetura, implementação, testes, documentação — toda esta base de código foi escrita pelo Claude Code. O autor humano forneceu requisitos e direção em linguagem natural. Veja [Como este projeto foi construído](#como-este-projeto-foi-construído) para detalhes.

---

## A ideia principal: sessões paralelas sem medo

Quando você envia tarefas ao Claude Code em threads separadas do Discord, o bridge faz quatro coisas automaticamente:

1. **Injeção automática de instruções de concorrência** — O prompt do sistema de cada sessão inclui instruções obrigatórias: criar um git worktree, trabalhar apenas dentro dele, nunca tocar diretamente o diretório de trabalho principal.

2. **Registro de sessões ativas** — Cada sessão em execução conhece as outras. Se duas sessões estão prestes a tocar o mesmo repositório, elas podem se coordenar em vez de conflitar.

3. **Canal de coordenação** — Um canal do Discord compartilhado onde sessões transmitem eventos de início/fim. Tanto o Claude quanto os humanos podem ver de relance o que está acontecendo em todas as threads ativas.

4. **AI Lounge** — Uma "sala de descanso" de sessão para sessão injetada em cada prompt. Antes de começar, cada sessão lê as mensagens recentes do lounge para ver o que outras sessões estão fazendo. Antes de operações destrutivas (force push, reinicialização do bot, exclusão de DB), as sessões verificam o lounge primeiro para não atrapalhar o trabalho das outras.

```
Thread A (funcionalidade) ──→  Claude Code (worktree-A)  ─┐
Thread B (revisão PR)     ──→  Claude Code (worktree-B)   ├─→  #ai-lounge
Thread C (docs)           ──→  Claude Code (worktree-C)  ─┘    "A: refatoração auth em progresso"
           ↓ eventos de ciclo de vida                           "B: revisão PR #42 concluída"
   #canal de coordenação                                        "C: atualizando README"
   "A: iniciada refatoração auth"
   "B: revisando PR #42"
   "C: atualizando README"
```

Sem condições de corrida. Sem trabalho perdido. Sem surpresas no merge.

---

## O que você pode fazer

### Chat interativo (Mobile / Desktop)

Use o Claude Code de qualquer lugar onde o Discord funcione — telefone, tablet ou desktop. Cada mensagem cria ou continua uma thread, mapeada 1:1 para uma sessão persistente do Claude Code.

### Desenvolvimento paralelo

Abra múltiplas threads simultaneamente. Cada uma é uma sessão independente do Claude Code com seu próprio contexto, diretório de trabalho e git worktree. Padrões úteis:

- **Funcionalidade + revisão em paralelo**: Inicie uma funcionalidade numa thread enquanto o Claude revisa um PR em outra.
- **Múltiplos contribuidores**: Diferentes membros da equipe têm cada um sua própria thread; as sessões ficam cientes umas das outras pelo canal de coordenação.
- **Experimentar com segurança**: Tente uma abordagem na thread A enquanto mantém a thread B em código estável.

### Tarefas Agendadas (SchedulerCog)

Registre tarefas periódicas do Claude Code de uma conversa no Discord ou via REST API — sem mudanças de código, sem redeploys. As tarefas são armazenadas no SQLite e executadas em um agendamento configurável.

```
/skill name:goodmorning           → executa imediatamente
Claude chama POST /api/tasks      → registra uma tarefa periódica
SchedulerCog (loop mestre 30s)    → dispara tarefas devidas automaticamente
```

### Automação CI/CD

Dispare tarefas do Claude Code a partir do GitHub Actions via webhooks do Discord. Claude executa de forma autônoma — lê código, atualiza docs, cria PRs, habilita auto-merge.

```
GitHub Actions → Discord Webhook → Bridge → Claude Code CLI
                                                  ↓
GitHub PR ←── git push ←── Claude Code ──────────┘
```

**Exemplo real:** A cada push para `main`, Claude analisa o diff, atualiza documentação em inglês + japonês, cria um PR com resumo bilíngue e habilita auto-merge. Zero interação humana.

### Sincronização de sessões

Já usa o Claude Code CLI diretamente? Sincronize suas sessões de terminal existentes em threads do Discord com `/sync-sessions`. Preenche mensagens de conversa recentes para que você possa continuar uma sessão CLI do seu telefone sem perder contexto.

### AI Lounge

Um canal "sala de descanso" compartilhado onde todas as sessões simultâneas se anunciam, leem as atualizações umas das outras e se coordenam antes de operações destrutivas.

Cada sessão do Claude recebe automaticamente o contexto do lounge em seu prompt do sistema: mensagens recentes de outras sessões, mais a regra de verificação antes de qualquer operação destrutiva.

```bash
# Sessões publicam suas intenções antes de começar:
curl -X POST "$CCDB_API_URL/api/lounge" \
  -H "Content-Type: application/json" \
  -d '{"message": "Iniciando refatoração auth em feature/oauth — worktree-A", "label": "dev funcionalidade"}'

# Ler mensagens recentes do lounge (também injetadas automaticamente em cada sessão):
curl "$CCDB_API_URL/api/lounge"
```

O canal lounge também serve como feed de atividade visível para humanos — abra-o no Discord para ver de relance o que cada sessão ativa do Claude está fazendo atualmente.

### Criação programática de sessões

Crie novas sessões do Claude Code a partir de scripts, GitHub Actions ou outras sessões do Claude — sem interação de mensagens do Discord.

```bash
# De outra sessão do Claude ou um script CI:
curl -X POST "$CCDB_API_URL/api/spawn" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Executar varredura de segurança no repositório", "thread_name": "Varredura de segurança"}'
# Retorna imediatamente com o ID da thread; Claude executa em segundo plano
```

### Retomada na inicialização

Se o bot reiniciar no meio de uma sessão, as sessões do Claude interrompidas são automaticamente retomadas quando o bot volta online. As sessões são marcadas para retomada de três formas:

- **Automática (reinicialização de atualização)** — `AutoUpgradeCog` captura todas as sessões ativas logo antes de uma reinicialização de atualização de pacote e as marca automaticamente.
- **Automática (qualquer desligamento)** — `ClaudeChatCog.cog_unload()` marca todas as sessões em execução sempre que o bot para via qualquer mecanismo (`systemctl stop`, `bot.close()`, SIGTERM, etc.).
- **Manual** — Qualquer sessão pode chamar diretamente `POST /api/mark-resume`.

---

## Funcionalidades

### Chat interativo
- **Thread = Session** — Mapeamento 1:1 entre thread do Discord e sessão do Claude Code
- **Status em tempo real** — Reações emoji: 🧠 pensando, 🛠️ lendo arquivos, 💻 editando, 🌐 pesquisa web
- **Texto em streaming** — Texto intermediário do assistente aparece enquanto Claude trabalha
- **Embeds de resultado de ferramentas** — Resultados de chamadas de ferramentas ao vivo com tempo decorrido subindo a cada 10s
- **Pensamento estendido** — Raciocínio mostrado como embeds com tags spoiler (clique para revelar)
- **Persistência de sessão** — Retomar conversas entre mensagens via `--resume`
- **Execução de skills** — Comando `/skill` com autocompletação, argumentos opcionais, retomada na thread
- **Reload a quente** — Novos skills adicionados em `~/.claude/skills/` detectados automaticamente (atualização a cada 60s, sem reinicialização)
- **Sessões simultâneas** — Múltiplas sessões paralelas com limite configurável
- **Parar sem apagar** — `/stop` interrompe uma sessão preservando-a para retomada
- **Suporte a anexos** — Arquivos de texto adicionados automaticamente ao prompt (até 5 × 50 KB)
- **Notificações de timeout** — Embed com tempo decorrido e guia de retomada no timeout
- **Perguntas interativas** — `AskUserQuestion` renderizado como Botões do Discord ou Menu de seleção; sessão retoma com sua resposta; botões sobrevivem a reinicializações do bot
- **Painel de threads** — Embed fixado ao vivo mostrando quais threads estão ativas vs aguardando; @menção ao proprietário quando entrada é necessária
- **Uso de tokens** — Taxa de acerto de cache e contagens de tokens mostradas no embed de sessão concluída

### Concorrência e coordenação
- **Instruções de worktree auto-injetadas** — Cada sessão instruída a usar `git worktree` antes de tocar qualquer arquivo
- **Limpeza automática de worktrees** — Worktrees de sessão (`wt-{thread_id}`) removidos automaticamente ao fim da sessão e na inicialização do bot; worktrees sujos nunca são removidos automaticamente (invariante de segurança)
- **Registro de sessões ativas** — Registro em memória; cada sessão vê o que as outras estão fazendo
- **AI Lounge** — Canal "sala de descanso" compartilhado injetado em cada prompt de sessão; sessões publicam intenções, leem o status umas das outras e verificam antes de operações destrutivas; humanos veem como um feed de atividade ao vivo
- **Canal de coordenação** — Canal compartilhado opcional para transmissões de ciclo de vida entre sessões
- **Scripts de coordenação** — Claude pode chamar `coord_post.py` / `coord_read.py` de dentro de uma sessão para publicar e ler eventos

### Tarefas agendadas
- **SchedulerCog** — Executor de tarefas periódicas baseado em SQLite com um loop mestre de 30 segundos
- **Auto-registro** — Claude registra tarefas via `POST /api/tasks` durante uma sessão de chat
- **Sem mudanças de código** — Adicione, remova ou modifique tarefas em tempo de execução
- **Ativar/desativar** — Pause tarefas sem excluí-las (`PATCH /api/tasks/{id}`)

### Automação CI/CD
- **Gatilhos webhook** — Dispare tarefas do Claude Code a partir do GitHub Actions ou qualquer sistema CI/CD
- **Auto-atualização** — Atualize automaticamente o bot quando pacotes upstream são lançados
- **Reinicialização DrainAware** — Aguarda sessões ativas terminarem antes de reiniciar
- **Marcação auto-retomada** — Sessões ativas são automaticamente marcadas para retomada em qualquer desligamento; retomam de onde pararam após o bot voltar online
- **Aprovação de reinicialização** — Portal opcional para confirmar atualizações antes de aplicar

### Gerenciamento de sessões
- **Sincronização de sessões** — Importe sessões CLI como threads do Discord (`/sync-sessions`)
- **Lista de sessões** — `/sessions` com filtragem por origem (Discord / CLI / todos) e janela de tempo
- **Info de retomada** — `/resume-info` mostra o comando CLI para continuar a sessão atual num terminal
- **Retomada na inicialização** — Sessões interrompidas reiniciam automaticamente após qualquer reinicialização do bot
- **Criação programática** — `POST /api/spawn` cria uma nova thread do Discord + sessão Claude de qualquer script ou subprocesso Claude
- **Injeção de ID de thread** — A variável de env `DISCORD_THREAD_ID` é passada para cada subprocesso Claude, permitindo que sessões gerem sessões filhas via `$CCDB_API_URL/api/spawn`
- **Gerenciamento de worktrees** — `/worktree-list` mostra todos os worktrees de sessão ativos com status clean/dirty; `/worktree-cleanup` remove worktrees clean órfãos

### Segurança
- **Sem injeção de shell** — Apenas `asyncio.create_subprocess_exec`, nunca `shell=True`
- **Validação de ID de sessão** — Regex estrita antes de passar para `--resume`
- **Prevenção de injeção de flags** — Separador `--` antes de todos os prompts
- **Isolamento de segredos** — Token do bot removido do ambiente do subprocesso
- **Autorização de usuário** — `allowed_user_ids` restringe quem pode invocar o Claude

---

## Início rápido — Claude no Discord em 5 minutos

### Passo 1 — Pré-requisitos

- **Python 3.10+** e **[uv](https://docs.astral.sh/uv/)** instalados
- **[Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code)** instalado e autenticado (`claude --version` deve funcionar)
- Um **servidor Discord** onde você tem acesso de administrador

### Passo 2 — Criar um bot do Discord

1. Acesse [discord.com/developers/applications](https://discord.com/developers/applications) e clique em **New Application**
2. Navegue até **Bot** → clique em **Add Bot**
3. Em **Privileged Gateway Intents**, habilite **Message Content Intent**
4. Copie o **Token** do bot (você precisará em breve)
5. Vá para **OAuth2 → URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions: `Send Messages`, `Create Public Threads`, `Send Messages in Threads`, `Add Reactions`, `Manage Messages`, `Read Message History`
6. Abra a URL gerada no seu navegador e convide o bot para o seu servidor

### Passo 3 — Obter seus IDs do Discord

Habilite o **Modo desenvolvedor** no Discord (Configurações → Avançado → Modo desenvolvedor), então:

- **ID do canal**: Clique com o botão direito no canal onde Claude deve escutar → **Copiar ID do canal**
- **Seu ID de usuário**: Clique com o botão direito no seu nome de usuário → **Copiar ID do usuário**

### Passo 4 — Executar

```bash
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge
cp .env.example .env
```

Edite `.env`:

```env
DISCORD_BOT_TOKEN=your-bot-token-here
DISCORD_CHANNEL_ID=123456789012345678    # o canal copiado acima
DISCORD_OWNER_ID=987654321098765432      # seu ID de usuário (para @-menções)
CLAUDE_WORKING_DIR=/path/to/your/project
```

Em seguida inicie o bot:

```bash
uv run python -m claude_discord.main
```

Envie uma mensagem no canal configurado — Claude responderá em uma nova thread.

---

### Bot mínimo (instalar como pacote)

Se você já tem um bot discord.py, adicione ccdb como pacote:

```bash
uv add git+https://github.com/ebibibi/claude-code-discord-bridge.git
```

Crie um `bot.py`:

```python
import asyncio
import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
from claude_discord import ClaudeRunner, setup_bridge

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
runner = ClaudeRunner(
    command="claude",
    model="sonnet",
    working_dir="/path/to/your/project",
)

@bot.event
async def on_ready():
    print(f"Logado como {bot.user}")
    await setup_bridge(
        bot,
        runner,
        claude_channel_id=int(os.environ["DISCORD_CHANNEL_ID"]),
        allowed_user_ids={int(os.environ["DISCORD_OWNER_ID"])},
    )

asyncio.run(bot.start(os.environ["DISCORD_BOT_TOKEN"]))
```

`setup_bridge()` conecta todos os Cogs automaticamente. Atualizar para a versão mais recente:

```bash
uv lock --upgrade-package claude-code-discord-bridge && uv sync
```

---

## Configuração

| Variável | Descrição | Padrão |
|----------|-----------|--------|
| `DISCORD_BOT_TOKEN` | Seu token de bot do Discord | (obrigatório) |
| `DISCORD_CHANNEL_ID` | ID do canal para chat com Claude | (obrigatório) |
| `CLAUDE_COMMAND` | Caminho para o Claude Code CLI | `claude` |
| `CLAUDE_MODEL` | Modelo a usar | `sonnet` |
| `CLAUDE_PERMISSION_MODE` | Modo de permissão para CLI | `acceptEdits` |
| `CLAUDE_WORKING_DIR` | Diretório de trabalho para Claude | diretório atual |
| `MAX_CONCURRENT_SESSIONS` | Máx sessões paralelas | `3` |
| `SESSION_TIMEOUT_SECONDS` | Timeout de inatividade de sessão | `300` |
| `DISCORD_OWNER_ID` | ID de usuário para @-mencionar quando Claude precisa de entrada | (opcional) |
| `COORDINATION_CHANNEL_ID` | ID de canal para transmissões de eventos entre sessões | (opcional) |
| `CCDB_COORDINATION_CHANNEL_NAME` | Criar canal de coordenação automaticamente por nome | (opcional) |
| `WORKTREE_BASE_DIR` | Diretório base para escanear worktrees de sessão (ativa limpeza automática) | (opcional) |

---

## REST API

API REST opcional para notificações e gerenciamento de tarefas. Requer aiohttp:

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
| PATCH | `/api/tasks/{id}` | Atualizar uma tarefa (ativar/desativar, alterar agendamento) |
| POST | `/api/spawn` | Criar nova thread do Discord e iniciar sessão do Claude Code (não bloqueante) |
| POST | `/api/mark-resume` | Marcar uma thread para retomada automática na próxima inicialização do bot |
| GET | `/api/lounge` | Ler mensagens recentes do AI Lounge |
| POST | `/api/lounge` | Publicar mensagem no AI Lounge (com `label` opcional) |

---

## Testes

```bash
uv run pytest tests/ -v --cov=claude_discord
```

610+ testes cobrindo parser, chunker, repositório, runner, streaming, gatilhos webhook, auto-atualização, API REST, UI AskUserQuestion, painel de threads, tarefas agendadas, sincronização de sessões, AI Lounge e retomada na inicialização.

---

## Como este projeto foi construído

**Esta base de código é desenvolvida pelo [Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — o agente de codificação IA da Anthropic — sob a direção de [@ebibibi](https://github.com/ebibibi). O autor humano define os requisitos, revisa os pull requests e aprova todas as mudanças — Claude Code faz a implementação.

Isso significa:

- **A implementação é gerada por IA** — arquitetura, código, testes, documentação
- **Revisão humana aplicada no nível de PR** — cada mudança passa por pull requests do GitHub e CI antes do merge
- **Relatórios de bugs e PRs são bem-vindos** — Claude Code será usado para resolvê-los
- **Este é um exemplo real de software open source dirigido por humanos e implementado por IA**

O projeto começou em 2026-02-18 e continua a evoluir através de conversas iterativas com o Claude Code.

---

## Exemplo do mundo real

**[EbiBot](https://github.com/ebibibi/discord-bot)** — Um bot pessoal do Discord construído sobre este framework. Inclui sincronização automática de documentação (inglês + japonês), notificações push, watchdog do Todoist, verificações de saúde agendadas e CI/CD com GitHub Actions. Use como referência para construir seu próprio bot.

---

## Licença

MIT
