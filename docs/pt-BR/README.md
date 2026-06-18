> **Note:** This is an auto-translated version of the original English documentation.
> If there are any discrepancies, the [English version](../../README.md) takes precedence.
> **Nota:** Esta é uma versão autotraduzida da documentação original em inglês.
> Em caso de discrepâncias, a [versão em inglês](../../README.md) prevalece.

# Claude & Codex Discord Bridge

*Nome do pacote: `claude-code-discord-bridge` (kebab-case)*

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![CodeQL](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/codeql.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/codeql.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Use Claude Code _ou_ OpenAI Codex no seu celular. Múltiplas threads. Tudo ao mesmo tempo. Desenvolvimento real incluído.**

Abra Claude Code ou OpenAI Codex no Discord do seu smartphone, inicie múltiplas threads e execute sessões de desenvolvimento em paralelo — tudo sem tocar em um teclado. Cada thread do Discord se torna uma sessão de IA completamente isolada. Trabalhe em um recurso em uma thread, revise um PR em outra e execute uma tarefa em segundo plano em uma terceira — simultaneamente, misturando backends por thread. A bridge cuida de toda a coordenação para que as sessões nunca se sobreponham.

**Use suas assinaturas existentes. Sem configuração de API key.** ccdb roda sobre as CLIs oficiais — Claude Code (inclusa na sua [assinatura Claude Pro/Max](https://claude.ai/pricing)) e OpenAI Codex (inclusa no [ChatGPT Plus/Pro/Business](https://chatgpt.com)). Troque backends com `/backend` ou configure por thread — seu time acessa ambas as IAs pelo Discord a custo previsível.

**[English](../../README.md)** | **[日本語](../ja/README.md)** | **[简体中文](../zh-CN/README.md)** | **[한국어](../ko/README.md)** | **[Español](../es/README.md)** | **[Français](../fr/README.md)**

> **Aviso:** Este projeto não é afiliado, endossado ou oficialmente conectado à Anthropic ou OpenAI. "Claude" e "Claude Code" são marcas registradas da Anthropic, PBC; "OpenAI", "Codex" e "ChatGPT" são marcas registradas da OpenAI. Esta é uma ferramenta de código aberto independente que faz interface com o Claude Code CLI e o OpenAI Codex CLI.

> **Construído inteiramente pelo Claude Code.** Todo este codebase — arquitetura, implementação, testes, documentação — foi escrito pelo próprio Claude Code. O autor humano forneceu requisitos e direcionamento. Veja [Como Este Projeto Foi Construído](#como-este-projeto-foi-construído).

---

## A Grande Ideia: Sessões Paralelas Sem Medo

Quando você envia tarefas para o Claude Code em threads separadas do Discord, a bridge faz quatro coisas automaticamente:

1. **Injeção de aviso de concorrência** — O system prompt de cada sessão inclui instruções obrigatórias: criar um git worktree, trabalhar apenas dentro dele, nunca tocar o diretório de trabalho principal diretamente.

2. **Registro de sessões ativas** — Cada sessão em execução sabe das outras. Se duas sessões forem tocar o mesmo repositório, elas podem coordenar em vez de conflitar.

3. **AI Lounge** — Um "saguão" injetado em cada prompt. Antes de começar, cada sessão lê as mensagens recentes do lounge para ver o que as outras estão fazendo. Antes de operações destrutivas (force push, reinício do bot, drop de DB), as sessões verificam o lounge primeiro.

```
Thread A (feature)   ──→  Claude Code (worktree-A)  ─┐
Thread B (PR review) ──→  Claude Code (worktree-B)   ├─→  #ai-lounge
Thread C (docs)      ──→  Claude Code (worktree-C)  ─┘    "A: refactor auth em andamento"
                                                           "B: revisão PR #42 concluída"
                                                           "C: atualizando README"
```

Sem race conditions. Sem trabalho perdido. Sem surpresas no merge.

---

## O Que Você Pode Fazer

### Chat Interativo (Mobile / Desktop)

Use Claude Code de qualquer lugar que o Discord funcione — celular, tablet ou desktop. Cada mensagem cria ou continua uma thread, mapeando 1:1 a uma sessão persistente do Claude Code.

### Desenvolvimento Paralelo

Abra múltiplas threads simultaneamente. Cada uma é uma sessão independente do Claude Code com seu próprio contexto, diretório de trabalho e git worktree. Padrões úteis:

- **Feature + revisão em paralelo**: Inicie um recurso em uma thread enquanto o Claude revisa um PR em outra.
- **Múltiplos contribuidores**: Diferentes membros da equipe têm suas próprias threads; sessões ficam cientes umas das outras via AI Lounge.
- **Experimente com segurança**: Tente uma abordagem na thread A mantendo a thread B em código estável.

### Tarefas Agendadas (SchedulerCog)

Registre tarefas periódicas do Claude Code de uma conversa do Discord ou via REST API — sem alterações de código, sem redeploys.

```
/skill name:goodmorning         → executa imediatamente
Claude chama POST /api/tasks    → registra tarefa periódica
SchedulerCog (loop 30s)         → dispara tarefas vencidas automaticamente
```

### Automação CI/CD

Dispare tarefas do Claude Code a partir do GitHub Actions via webhooks do Discord. Claude roda autonomamente — lê código, atualiza documentação, cria PRs, habilita auto-merge.

**Exemplo real:** A cada push para `main`, Claude analisa o diff, atualiza documentação em inglês + japonês, cria um PR bilíngue e habilita auto-merge. Zero interação humana.

### Sincronização de Sessões

Já usa Claude Code CLI diretamente? Sincronize suas sessões de terminal existentes em threads do Discord com `/sync-sessions`. Retroalimenta mensagens de conversa recentes para que você possa continuar uma sessão CLI do seu celular sem perder contexto.

### AI Lounge

Um canal compartilhado de "sala de descanso" onde todas as sessões concorrentes se anunciam, leem as atualizações das outras e se coordenam antes de operações destrutivas.

### Criação de Sessão Programática

Crie novas sessões do Claude Code a partir de scripts, GitHub Actions ou outras sessões do Claude — sem interação com mensagens do Discord.

```bash
# A partir de outra sessão Claude ou de um script CI:
curl -X POST "$CCDB_API_URL/api/spawn" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Executar varredura de segurança no repositório", "thread_name": "Security Scan"}'
# Retorna imediatamente com o ID da thread; Claude executa em segundo plano
```

**Início adiado (`auto_start=false`)** — Crie uma thread e publique uma mensagem semente sem iniciar o Claude imediatamente. Claude inicia apenas quando um usuário responde. Útil para fluxos de notificação.

### Ingestão Externa Autenticada e Recuperação de Resultados (`/api/ingest`)

`POST /api/ingest` é o **spawn autenticado e compatível com anexos** para clientes externos não confiáveis (extensões de navegador, atalhos móveis, webhooks). Ao contrário de `/api/spawn` (confiável, localhost), requer um `ingest_token` dedicado (configure `CCDB_INGEST_TOKEN`; independente de `api_secret`) e pode carregar anexos base64 que são gravados em disco para que a sessão criada os leia. Cria uma thread real do Discord, mantendo toda a interação observável.

A sessão é **interativa** (uma thread real do Discord onde você pode continuar respondendo) — mas ainda pode obter a resposta final programaticamente. Quando a recuperação de resultados está configurada (conectada automaticamente via `setup_bridge()`), a resposta inclui um `result_id`, e `GET /api/ingest/{result_id}` faz polling da resposta final da sessão.

```bash
# Publicar trabalho (com anexos opcionais); retorna imediatamente
curl -X POST "$CCDB_API_URL/api/ingest" \
  -H "Authorization: Bearer $CCDB_INGEST_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content": "Resuma esta thread e rascunhe uma resposta",
       "attachments": [{"filename": "thread.txt", "data": "<base64>"}]}'
# → {"status": "spawned", "thread_id": "…", "result_id": "ab12…", "attachments_saved": 1}

# Polling da resposta final
curl "$CCDB_API_URL/api/ingest/ab12…" -H "Authorization: Bearer $CCDB_INGEST_TOKEN"
# → {"status": "done", "result": "…", "error": null, "thread_id": "…", "thread_name": "…"}
```

O endpoint é opt-in: sem `ingest_token` configurado, `POST` responde `503`. Os resultados estão limitados a 200 linhas.

### Retomada na Inicialização

Se o bot reiniciar durante uma sessão, as sessões Claude interrompidas são automaticamente retomadas quando o bot volta online. As sessões são marcadas para retomada de três formas:

- **Automático (reinício por atualização)** — `AutoUpgradeCog` captura todas as sessões ativas antes de um reinício por atualização e as marca automaticamente.
- **Automático (qualquer desligamento)** — `ClaudeChatCog.cog_unload()` marca as sessões em execução quando o bot é desligado por qualquer mecanismo.
- **Manual** — Qualquer sessão pode chamar `POST /api/mark-resume` diretamente.

---

## Funcionalidades

### Chat Interativo

#### 🔗 Básico de Sessão
- **Modo somente chat** — `CHAT_ONLY_CHANNEL_IDS` mostra apenas respostas de texto do Claude; embeds de ferramentas, blocos de pensamento, embeds de sessão e listas de tarefas ficam ocultos
- **Thread = Sessão** — Mapeamento 1:1 entre thread do Discord e sessão do Claude Code
- **Acompanhamento de objetivo** — `/goal <condição>` define condição de conclusão; Claude continua trabalhando até a condição ser atendida
- **Persistência de sessão** — Continue conversas entre mensagens via `--resume`
- **Sessões concorrentes** — Múltiplas sessões paralelas com limite configurável
- **Parar sem limpar** — `/stop` para uma sessão preservando-a para retomada
- **Interrupção de sessão** — Enviar nova mensagem para thread ativa envia SIGINT e começa com nova instrução
- **Auto-renomear threads** — Com `THREAD_AUTO_RENAME=true`, cada nova thread é automaticamente renomeada

#### 📡 Feedback em Tempo Real
- **Status em tempo real** — Reações emoji: 🧠 pensando, 🛠️ lendo arquivos, 💻 editando, 🌐 busca na web
- **Texto em streaming** — Texto intermediário aparece enquanto o Claude trabalha
- **Embeds de resultado de ferramenta** — Resultados de chamadas de ferramentas ao vivo com tempo decorrido
- **Pensamento estendido** — Raciocínio mostrado como embeds com tag spoiler (clique para revelar)
- **Dashboard de thread** — Embed fixado ao vivo mostrando quais threads estão ativas vs. aguardando

#### 🤝 Human-in-the-Loop
- **Perguntas interativas** — `AskUserQuestion` renderizado como Botões ou Menu de Seleção do Discord; solicitante @mencionado quando input é necessário
- **Modo Plan** — `ExitPlanMode` mostra embed com botões Aprovar/Cancelar; solicitante @mencionado no prompt; 5 minutos de timeout
- **Solicitações de permissão de ferramenta** — Botões Permitir/Negar; solicitante @mencionado; auto-negação após 2 minutos
- **MCP Elicitation** — Servidores MCP podem solicitar entrada do usuário via Discord; solicitante @mencionado; 5 minutos de timeout
- **Progresso TodoWrite ao vivo** — Embed único do Discord editado no lugar; mostra ✅ concluído, 🔄 ativo, ⬜ pendente

#### 📊 Observabilidade
- **Uso de tokens** — Taxa de acerto de cache e contagens de tokens no embed de sessão concluída
- **Uso de contexto** — Percentual da janela de contexto; aviso ⚠️ acima de 83.5%
- **Detecção de compactação** — Notifica na thread quando compactação de contexto ocorre
- **Notificação de parada longa** — Mensagem na thread após inatividade (30s padrão, 120s para Opus)
- **Notificações de timeout** — Embed com tempo decorrido e guia de retomada
- **Exibição de StatusLine** — Exibe o status do Claude após cada sessão
- **Caixa de entrada de thread** — Com `THREAD_INBOX_ENABLED=true`, seção 📬 no dashboard

#### 🔌 Entrada e Habilidades
- **Suporte a anexos** — Arquivos de texto adicionados automaticamente (até 5 arquivos, 200 KB cada); imagens como URLs de CDN (até 4 × 5 MB)
- **Entrega de arquivos sob demanda** — Claude escreve caminho em `.ccdb-attachments`; enviado como anexo do Discord na conclusão da sessão
- **Execução de habilidades** — Comando `/skill` com autocompletar; habilidades de plugins instalados também descobertas
- **Hot reload** — Novas habilidades em `~/.claude/skills/` detectadas automaticamente (atualização de 60s)

### Concorrência e Coordenação
- **Instruções de Worktree auto-injetadas** — Cada sessão instruída a usar `git worktree`
- **Limpeza automática de worktree** — Worktrees de sessão removidos automaticamente; worktrees sujos nunca são removidos automaticamente
- **Registro de sessões ativas** — Registro em memória; cada sessão vê o que as outras estão fazendo
- **AI Lounge** — Canal compartilhado; contexto injetado via `--append-system-prompt` (nunca acumula no histórico)
- **Canal de coordenação** — `COORDINATION_CHANNEL_ID` como fallback padrão para AI Lounge

### Tarefas Agendadas
- **SchedulerCog** — Executor de tarefas periódicas com suporte SQLite, loop mestre de 30 segundos
- **Auto-registro** — Claude registra tarefas via `POST /api/tasks`
- **Sem alterações de código** — Adicione, remova ou modifique tarefas em tempo de execução
- **Ativar/desativar** — Pause tarefas sem excluir (`PATCH /api/tasks/{id}`)

### Automação CI/CD
- **Gatilhos de Webhook** — Dispare tarefas do GitHub Actions ou qualquer sistema CI/CD
- **Auto-upgrade** — Atualiza o bot automaticamente quando pacotes upstream são lançados
- **Reinício DrainAware** — Aguarda sessões ativas terminarem antes de reiniciar
- **Marcação automática de retomada** — Sessões ativas marcadas automaticamente em qualquer desligamento
- **Gatilho manual de upgrade** — Comando `/upgrade` (opt-in via `slash_command_enabled=True`)

### Gerenciamento de Sessão
- **Ajuda integrada** — `/help` mostra todos os comandos slash disponíveis (efêmero)
- **Sincronização de sessão** — Importa sessões CLI como threads do Discord (`/sync-sessions`)
- **Lista de sessões** — `/sessions` com filtragem por origem e janela de tempo
- **Retomar sessão** — `/resume` mostra menu de seleção e retoma em nova thread
- **Limpar sessão** — `/clear` redefine a sessão do Claude Code da thread atual
- **Retomada na inicialização** — Sessões interrompidas retomam automaticamente após qualquer reinicialização do bot
- **Spawn programático** — `POST /api/spawn` cria nova thread + sessão a partir de qualquer script
- **Gerenciamento de Worktree** — `/worktree-list` e `/worktree-cleanup`
- **Troca de modelo em tempo de execução** — `/model-show` e `/model-set`, sem reiniciar
- **Rebobinagem de conversa** — `/rewind` trunca a sessão no turno selecionado
- **Bifurcação de conversa** — `/fork` cria cópia independente de sessão em nova thread

### Segurança
- **Sem injeção de shell** — Apenas `asyncio.create_subprocess_exec`, nunca `shell=True`
- **Validação de ID de sessão** — Regex estrita antes de passar para `--resume`
- **Prevenção de injeção de flags** — Separador `--` antes de todos os prompts
- **Isolamento de secrets** — Token do bot removido do ambiente do subprocesso
- **Autorização de usuário** — `allowed_user_ids` restringe quem pode invocar Claude
- **Prevenção de injeção de log** — Valores de API fornecidos pelo usuário sanitizados antes de escrever nos logs

---

## Início Rápido — Claude no Discord em 5 Minutos

**Pré-requisitos:** Python 3.10+, [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) instalado e autenticado.

**Suporte de plataforma:** Principalmente desenvolvido e testado no **Linux**. macOS e Windows são suportados e passam no CI, mas recebem menos testes no mundo real.

### Passo 1 — Criar um Bot do Discord (uma vez, ~2 minutos)

1. Vá para [discord.com/developers/applications](https://discord.com/developers/applications) → **New Application**
2. Navegue para **Bot** → habilite **Message Content Intent** em Privileged Gateway Intents
3. Copie o **Token** do bot
4. Vá para **OAuth2 → URL Generator**: Escopos `bot` + `applications.commands`, Permissões: Send Messages, Create Public Threads, Send Messages in Threads, Add Reactions, Manage Messages, Read Message History
5. Abra a URL gerada → convide o bot para seu servidor

### Passo 2 — Execute o Assistente de Configuração

Sem necessidade de clonar ou editar `.env` — o assistente faz tudo:

```bash
# Com uvx (sem necessidade de instalação):
uvx --from "git+https://github.com/ebibibi/claude-code-discord-bridge.git" ccdb setup

# Ou após clonar:
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge
uv run ccdb setup
```

### Iniciar / Parar

```bash
ccdb start    # iniciar o bot (lê .env no diretório atual)
ccdb start --env /path/to/.env   # localização personalizada do .env
```

Envie uma mensagem no canal configurado — Claude responderá em uma nova thread.

### Executar como Serviço systemd (Produção)

```bash
sudo cp discord-bot.service /etc/systemd/system/mybot.service
sudo nano /etc/systemd/system/mybot.service
sudo systemctl daemon-reload
sudo systemctl enable mybot.service
sudo systemctl start mybot.service
journalctl -u mybot.service -f
```

### Cogs Personalizados (Estenda Sem Fork)

Adicione suas próprias funcionalidades colocando arquivos Python em um diretório — sem fork, sem subclasse, sem pacote:

```bash
ccdb start --cogs-dir ./my-cogs/
# Ou: CUSTOM_COGS_DIR=./my-cogs ccdb start
```

Cada arquivo `.py` deve expor `async def setup(bot, runner, components)`.

---

### Bot Mínimo (Instalar como Pacote)

```bash
uv add git+https://github.com/ebibibi/claude-code-discord-bridge.git
```

Crie `bot.py`:

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
    print(f"Logged in as {bot.user}")
    await setup_bridge(
        bot,
        runner,
        claude_channel_id=int(os.environ["DISCORD_CHANNEL_ID"]),
        allowed_user_ids={int(os.environ["DISCORD_OWNER_ID"])},
    )

asyncio.run(bot.start(os.environ["DISCORD_BOT_TOKEN"]))
```

`setup_bridge()` conecta todos os Cogs automaticamente. Atualizar para a última versão:

```bash
uv lock --upgrade-package claude-code-discord-bridge && uv sync
```

---

## Configuração

| Variável | Descrição | Padrão |
|----------|-----------|--------|
| `DISCORD_BOT_TOKEN` | Token do bot do Discord | (obrigatório) |
| `DISCORD_CHANNEL_ID` | ID do canal para chat do Claude | (obrigatório) |
| `CCDB_BACKEND` | Backend CLI a usar: `claude` ou `codex` | `claude` |
| `CCDB_COMMAND` | Caminho ou nome do binário CLI (substitui `CLAUDE_COMMAND`) | _(auto)_ |
| `CCDB_MODEL` | Modelo a usar (substitui `CLAUDE_MODEL`) | `sonnet` |
| `CCDB_PERMISSION_MODE` | Modo de permissão CLI (substitui `CLAUDE_PERMISSION_MODE`) | `acceptEdits` |
| `CCDB_DANGEROUSLY_SKIP_PERMISSIONS` | Pular todas as verificações de permissão | `false` |
| `CCDB_WORKING_DIR` | Diretório de trabalho CLI | diretório atual |
| `CCDB_ALLOWED_TOOLS` | Lista separada por vírgula de ferramentas permitidas | (opcional) |
| `CCDB_CHANNEL_IDS` | IDs de canal adicionais para configuração multi-canal | (opcional) |
| `CLAUDE_COMMAND` | Caminho do CLI Claude (nome legado — preferir `CCDB_COMMAND`) | `claude` |
| `CLAUDE_MODEL` | Modelo (nome legado — preferir `CCDB_MODEL`) | `sonnet` |
| `CLAUDE_PERMISSION_MODE` | Modo de permissão (nome legado — preferir `CCDB_PERMISSION_MODE`) | `acceptEdits` |
| `CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS` | Pular permissões (nome legado) | `false` |
| `CLAUDE_WORKING_DIR` | Diretório de trabalho (nome legado) | diretório atual |
| `MAX_CONCURRENT_SESSIONS` | Máximo de sessões CLI paralelas | `3` |
| `SESSION_TIMEOUT_SECONDS` | Timeout de inatividade de sessão | `300` |
| `DISCORD_OWNER_ID` | ID de usuário para @mencionar quando Claude precisar de entrada | (opcional) |
| `COORDINATION_CHANNEL_ID` | ID de canal como fallback padrão para AI Lounge | (opcional) |
| `MENTION_ONLY_CHANNEL_IDS` | IDs de canal onde o bot só responde quando @mencionado (separados por vírgula) | (opcional) |
| `INLINE_REPLY_CHANNEL_IDS` | IDs de canal de resposta inline (separados por vírgula, sem criar thread) | (opcional) |
| `CHAT_ONLY_CHANNEL_IDS` | IDs de canal em modo somente chat (separados por vírgula) | (opcional) |
| `WORKTREE_BASE_DIR` | Diretório base para escanear worktrees de sessão | (opcional) |
| `CLI_SESSIONS_PATH` | Caminho para descoberta de sessões CLI (`~/.claude/projects`) | (opcional) |
| `CUSTOM_COGS_DIR` | Diretório contendo arquivos Cog personalizados | (opcional) |
| `THREAD_INBOX_ENABLED` | Habilitar caixa de entrada de thread persistente | `false` |
| `THREAD_AUTO_RENAME` | Auto-renomear novas threads com título gerado pelo Claude | `false` |
| `CCDB_CLI_ENV_FILE` | Caminho para arquivo `KEY=VALUE` mesclado no ambiente do subprocesso CLI | (opcional) |
| `CCDB_LOG_FILE` | Caminho para arquivo de log. Quando definido, um manipulador de arquivo rotativo (10 MB × 5 backups) é adicionado ao stdout padrão. Útil para monitoramento e alertas | (opcional) |
| `API_HOST` | Endereço de bind da REST API | `127.0.0.1` |
| `API_PORT` | Porta da REST API (habilita REST API quando configurada) | (opcional) |

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
| POST | `/api/schedule` | Agendar notificação |
| GET | `/api/scheduled` | Listar notificações pendentes |
| DELETE | `/api/scheduled/{id}` | Cancelar notificação |
| POST | `/api/tasks` | Registrar tarefa periódica do Claude Code |
| GET | `/api/tasks` | Listar tarefas registradas |
| DELETE | `/api/tasks/{id}` | Remover tarefa |
| PATCH | `/api/tasks/{id}` | Atualizar tarefa |
| POST | `/api/spawn` | Criar nova thread do Discord e iniciar sessão do Claude Code (não bloqueante) |
| POST | `/api/ingest` | Spawn externo autenticado (extensão de navegador/webhook) com anexos base64; retorna `result_id` quando recuperação de resultados está configurada |
| GET | `/api/ingest/{result_id}` | Polling da resposta final da sessão criada (`status`/`result`/`error`/`thread_id`) |
| POST | `/api/mark-resume` | Marcar thread para retomada automática na próxima inicialização do bot |
| GET | `/api/lounge` | Ler mensagens recentes do AI Lounge |
| POST | `/api/lounge` | Publicar mensagem no AI Lounge |

---

## Arquitetura

```
claude_code_core/          # Biblioteca central compartilhada (independente de backend)
  backend.py               # Protocolo SessionBackend + fábrica create_backend()
  codex_runner.py          # Backend OpenAI Codex CLI
  runner.py                # Gerenciador de subprocesso Claude CLI
  parser.py                # Analisador de eventos stream-json
  types.py                 # Definições de tipo para mensagens SDK
claude_discord/
  main.py                  # Ponto de entrada independente
  cli.py                   # Ponto de entrada CLI (comandos ccdb setup/start)
  setup.py                 # setup_bridge()
  cogs/
    claude_chat.py         # Chat interativo
    skill_command.py       # Comando slash /skill
    session_manage.py      # Gerenciamento de sessão
    scheduler.py           # Executor de tarefas periódicas
    webhook_trigger.py     # Webhook → execução de tarefa Claude Code
    auto_upgrade.py        # Auto-upgrade + reinício com drenagem
  ext/
    api_server.py          # REST API (opcional)
examples/
  ebibot/                  # Exemplo do mundo real
```

### Filosofia de Design

- **CLI spawn, não API** — Invoca `claude -p --output-format stream-json`, obtendo todos os recursos do Claude Code sem reimplementá-los. Sem API key, sem cobrança por token.
- **Concorrência primeiro** — Múltiplas sessões simultâneas são o caso esperado, não um caso especial
- **Discord como cola** — Discord fornece UI, threading, reações, webhooks e notificações persistentes
- **Framework, não aplicação** — Instale como pacote, adicione Cogs ao seu bot existente
- **Extensibilidade sem código** — Adicione tarefas agendadas e gatilhos de webhook sem tocar no código-fonte
- **Segurança por simplicidade** — ~8000 linhas de Python auditável; apenas subprocess exec, sem expansão de shell

---

## Testes

```bash
uv run pytest tests/ -v --cov=claude_discord
```

Mais de 1365 testes cobrindo analisador, chunker, repositório, runner, streaming, gatilhos de webhook, auto-upgrade, REST API, AskUserQuestion UI, dashboard de thread, tarefas agendadas, sincronização de sessão, AI Lounge, retomada na inicialização, troca de modelo, detecção de compactação, embeds de progresso TodoWrite, carregador de Cogs personalizados, protocolo SessionBackend, CodexRunner e fábrica de backends.

---

## Como Este Projeto Foi Construído

**Este codebase é desenvolvido pelo [Claude Code](https://docs.anthropic.com/en/docs/claude-code)**, o agente de codificação AI da Anthropic, sob a direção de [@ebibibi](https://github.com/ebibibi). O autor humano define requisitos, revisa pull requests e aprova todas as mudanças — Claude Code faz a implementação.

O projeto começou em 2026-02-18 e continua evoluindo através de conversas iterativas com o Claude Code.

---

## Exemplo do Mundo Real

**[`examples/ebibot/`](examples/ebibot/)** — Um bot pessoal do Discord construído sobre este framework, incluído diretamente neste repositório. Demonstra o carregador de Cog personalizado com:

- **ReminderCog** — Comando slash `/remind HH:MM "message"` + loop de envio de 30 segundos
- **WatchdogCog** — Monitor de tarefas vencidas do Todoist
- **AutoUpgradeCog** — Auto-atualização via webhook do GitHub + systemctl restart
- **DocsSyncCog** — Sincronização automática de documentação no push
- **AlertResponderCog** — Cog genérico de monitoramento de alertas

Execute com: `ccdb start --cogs-dir examples/ebibot/cogs/`

---

## Inspirado Por

- [OpenClaw](https://github.com/openclaw/openclaw) — Reações de status emoji, debouncing de mensagens, chunking ciente de fence
- [claude-code-discord-bot](https://github.com/timoconnellaus/claude-code-discord-bot) — Abordagem CLI spawn + stream-json
- [claude-code-discord](https://github.com/zebbern/claude-code-discord) — Padrões de controle de permissão
- [claude-sandbox-bot](https://github.com/RhysSullivan/claude-sandbox-bot) — Modelo de conversa por thread

---

## Licença

MIT
