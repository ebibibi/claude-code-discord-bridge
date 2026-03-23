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

3. **AI Lounge** — Uma «sala de espera» compartilhada injetada no prompt de cada sessão. Antes de começar, cada sessão lê as mensagens recentes do Lounge para entender o que as outras estão fazendo. Antes de operações destrutivas (force push, reinício do bot, etc.), as sessões verificam o Lounge primeiro.

```
Thread A (feature)    ──→  Claude Code (worktree-A)  ─┐
Thread B (revisão PR) ──→  Claude Code (worktree-B)   ├─→  #ai-lounge
Thread C (docs)       ──→  Claude Code (worktree-C)  ─┘    "A: refactor auth em progresso"
                                                            "B: revisão PR #42 concluída"
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
- **Múltiplos colaboradores**: Diferentes membros do time têm sua própria thread; as sessões ficam cientes umas das outras via o AI Lounge.
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

#### 🔗 Sessão Básica
- **Thread = Session** — Mapeamento 1:1 entre thread do Discord e sessão do Claude Code
- **Persistência de sessão** — Retoma conversas entre mensagens via `--resume`
- **Sessões concorrentes** — Múltiplas sessões paralelas com limite configurável
- **Parar sem limpar** — `/stop` para uma sessão preservando-a para retomada
- **Interrupção de sessão** — Enviar uma nova mensagem a uma thread ativa envia SIGINT à sessão em execução e reinicia com a nova instrução; sem necessidade de `/stop` manual
- **Renomeação automática de threads** — Quando `THREAD_AUTO_RENAME=true`, cada nova thread é automaticamente renomeada com um título gerado pelo Claude baseado na primeira mensagem (tarefa em segundo plano, nunca atrasa o início da sessão)

#### 📡 Feedback em Tempo Real
- **Status em tempo real** — Reações emoji: 🧠 pensando, 🛠️ lendo arquivos, 💻 editando, 🌐 pesquisa web
- **Texto em streaming** — Texto intermediário do assistente aparece enquanto o Claude trabalha
- **Embeds de resultados de ferramentas** — Resultados ao vivo com tempo decorrido aumentando a cada 10s; resultados de uma linha exibidos diretamente, resultados de múltiplas linhas recolhidos atrás de um botão de expansão
- **Pensamento estendido** — Raciocínio exibido como embeds com spoiler (clique para revelar)
- **Painel de threads** — Embed fixado ao vivo mostrando quais threads estão ativas vs. aguardando; owner é @mencionado quando input é necessário

#### 🤝 Colaboração Humano-IA
- **Perguntas interativas** — `AskUserQuestion` renderiza como Botões do Discord ou Menu de Seleção; a sessão retoma com sua resposta; botões sobrevivem a reinícios do bot
- **Plan Mode** — Quando Claude chama `ExitPlanMode`, um embed do Discord exibe o plano completo com botões Aprovar/Cancelar; Claude prossegue somente após aprovação; cancelamento automático após 5 minutos
- **Solicitações de permissão de ferramenta** — Quando Claude precisa de permissão para executar uma ferramenta, o Discord exibe botões Permitir/Negar com o nome e a entrada da ferramenta; negação automática após 2 minutos
- **MCP Elicitation** — Servidores MCP podem solicitar entrada do usuário via Discord (modo formulário: até 5 campos Modal do esquema JSON; modo URL: botão URL + confirmação); timeout de 5 minutos
- **Progresso em tempo real do TodoWrite** — Quando Claude chama `TodoWrite`, um único embed do Discord é postado e editado in-place a cada atualização; mostra ✅ concluído, 🔄 ativo (com rótulo `activeForm`), ⬜ pendente

#### 📊 Observabilidade
- **Uso de tokens** — Taxa de acerto de cache e contagem de tokens exibidos no embed de sessão completa
- **Uso de contexto** — Percentual da janela de contexto (tokens de entrada + cache, excluindo saída) e capacidade restante até o auto-compact exibidos no embed de sessão concluída; ⚠️ aviso quando acima de 83,5%
- **Detecção de compactação** — Notifica na thread quando a compactação de contexto ocorre (tipo de gatilho + contagem de tokens antes da compactação)
- **Notificação de travamento** — Mensagem na thread quando não há atividade (pensamento estendido ou compressão de contexto); reinicia automaticamente quando Claude retoma. Os limites se adaptam ao modelo: 30 s para modelos padrão, 120 s para Opus (pausas de reflexão mais longas)
- **Notificações de timeout** — Embed com tempo decorrido e guia de retomada ao atingir timeout
- **Caixa de entrada de threads** — Quando `THREAD_INBOX_ENABLED=true`, o painel exibe uma seção 📬 persistente; após cada sessão terminar, o Claude classifica a última mensagem (`waiting`/`done`/`ambiguous`) via uma chamada leve a `claude -p`; threads aguardando resposta sobrevivem a reinícios do bot e são exibidas até você responder

#### 🔌 Entrada e Skills
- **Suporte a anexos** — Arquivos de texto adicionados automaticamente ao prompt (até 5 × 50 KB); imagens baixadas e passadas via `--image` (até 4 × 5 MB)
- **Execução de skills** — Comando `/skill` com autocomplete, argumentos opcionais, retomada dentro da thread
- **Hot reload** — Novos skills adicionados a `~/.claude/skills/` são detectados automaticamente (atualização a cada 60s, sem reinício)

### Concorrência e Coordenação
- **Instruções de worktree auto-injetadas** — Cada sessão recebe instruções para usar `git worktree` antes de tocar em qualquer arquivo
- **Limpeza automática de worktree** — Worktrees de sessão (`wt-{thread_id}`) são removidos automaticamente ao final da sessão e na inicialização do bot; worktrees com alterações nunca são removidos automaticamente (invariante de segurança)
- **Registro de sessões ativas** — Registro em memória; cada sessão vê o que as outras estão fazendo
- **AI Lounge** — Canal «sala de descanso» compartilhado; contexto injetado via `--append-system-prompt` (efêmero, nunca acumula no histórico) para que sessões longas nunca atinjam «Prompt is too long»; sessões publicam intenções, leem o status umas das outras e verificam antes de operações destrutivas; os humanos veem como um feed de atividade em tempo real
- **Canal de coordenação** — A variável de ambiente `COORDINATION_CHANNEL_ID` é usada como fallback padrão para o canal AI Lounge (notificações automáticas de ciclo de vida do bot foram removidas)

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
- **Sincronização de sessões** — Importa sessões CLI como threads do Discord (`/sync-sessions`); `/sync-settings` para visualizar ou alterar preferências de sincronização (estilo de thread, janela de tempo, resultados mínimos)
- **Lista de sessões** — `/sessions` com filtragem por origem (Discord / CLI / todas) e janela de tempo
- **Retomada de sessão** — `/resume` mostra um menu de seleção com sessões recentes (até 25) e retoma a selecionada em uma nova thread; funciona de qualquer canal ou thread — sempre cria uma nova thread no canal principal configurado
- **Informações de retomada** — `/resume-info` mostra o comando CLI para continuar a sessão atual em um terminal (apenas em threads)
- **Limpar sessão** — `/clear` redefine a sessão do Claude Code para a thread atual, começando do zero sem criar uma nova thread
- **Retomada ao iniciar** — Sessões interrompidas reiniciam automaticamente após qualquer reinício do bot; `AutoUpgradeCog` (reinícios por atualização) e `ClaudeChatCog.cog_unload()` (todos os outros encerramentos) as marcam automaticamente, ou use `POST /api/mark-resume` manualmente
- **Criação programática** — `POST /api/spawn` cria uma nova thread do Discord + sessão do Claude de qualquer script ou subprocesso do Claude; retorna um 201 não bloqueante imediatamente após a criação da thread
- **Injeção de ID da thread** — A variável de ambiente `DISCORD_THREAD_ID` é passada para cada subprocesso do Claude, permitindo que sessões criem sessões filhas via `$CCDB_API_URL/api/spawn`
- **Gerenciamento de worktree** — `/worktree-list` mostra todos os worktrees de sessão ativos com status limpo/sujo; `/worktree-cleanup` remove worktrees limpos órfãos (suporta preview com `dry_run`)
- **Rebobinar conversa** — `/rewind` redefine o histórico de conversa mantendo os arquivos de trabalho que o Claude criou; a mensagem de confirmação mostra o % de uso do contexto no momento do reset
- **Bifurcar conversa** — `/fork` usa `--fork-session` para criar uma nova thread que continua do mesmo estado de sessão, permitindo explorar uma direção diferente sem afetar a thread original
- **Visibilidade do contexto** — `/context` exibe o % de uso da janela de contexto com uma barra de progresso visual; mostra aviso ⚠️ de autocompactação ao se aproximar do limite de 83.5%
- **Monitoramento de rate limit** — `/usage` exibe a utilização do rate limit da API Claude com barra de percentual e contagem regressiva até o reset por tipo de limite
- **Ajuda integrada** — `/help` exibe todos os comandos slash disponíveis e uso básico (efêmero, visível apenas para quem invocou)
- **Troca de modelo em tempo de execução** — `/model-show` exibe o modelo global atual e o modelo de sessão por thread; `/model-set` altera o modelo para todas as novas sessões sem reiniciar
- **Permissões de ferramenta em tempo de execução** — `/tools-show` exibe as ferramentas atualmente permitidas; `/tools-set` abre um menu de seleção para ativar/desativar ferramentas; `/tools-reset` reverte ao padrão do `.env` — tudo sem reiniciar

### Segurança
- **Sem injeção de shell** — Apenas `asyncio.create_subprocess_exec`, nunca `shell=True`
- **Validação de ID de sessão** — Regex estrito antes de passar para `--resume`
- **Prevenção de injeção de flags** — Separador `--` antes de todos os prompts
- **Isolamento de segredos** — Token do bot removido do ambiente do subprocesso
- **Autorização de usuário** — `allowed_user_ids` restringe quem pode invocar o Claude
- **Prevenção de injeção em logs** — Valores de API fornecidos pelo usuário são sanitizados (remoção de quebras de linha e sequências de escape ANSI) antes de serem escritos nos logs

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

### Executar como serviço systemd (produção)

Em produção, gerenciar via systemd garante inicialização automática na boot e reinício em caso de falha.

O repositório inclui modelos prontos: `discord-bot.service` e `scripts/pre-start.sh`. Copie e ajuste os caminhos e o usuário:

```bash
# 1. Edite o arquivo de serviço — substitua /home/ebi e User=ebi pelo seu caminho/usuário
sudo cp discord-bot.service /etc/systemd/system/mybot.service
sudo nano /etc/systemd/system/mybot.service

# 2. Habilitar e iniciar
sudo systemctl daemon-reload
sudo systemctl enable mybot.service
sudo systemctl start mybot.service

# 3. Verificar status
sudo systemctl status mybot.service
journalctl -u mybot.service -f
```

**O que `scripts/pre-start.sh` faz** (executado como `ExecStartPre` antes do processo do bot):

1. **`git pull --ff-only`** — obtém o código mais recente de `origin main`
2. **`uv sync`** — sincroniza dependências conforme `uv.lock`
3. **Validação de importação** — verifica se `claude_discord.main` importa corretamente
4. **Rollback automático** — se a importação falhar, reverte para o commit anterior e tenta novamente; envia notificação via Discord webhook
5. **Limpeza de worktrees** — remove git worktrees órfãos de sessões que falharam

O script detecta dinamicamente a raiz do repositório via `readlink -f $0`, então não é necessário editar caminhos no script independentemente de onde o clone foi feito. O binário `uv` também é auto-detectado do `PATH`; use a variável `CCDB_UV_BIN` para especificar um caminho personalizado.

Configure `DISCORD_WEBHOOK_URL` no `.env` para receber notificações de falha (opcional).

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
| `CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS` | Pular todas as verificações de permissão (use com cuidado) | `false` |
| `CLAUDE_WORKING_DIR` | Diretório de trabalho para o Claude | diretório atual |
| `MAX_CONCURRENT_SESSIONS` | Máximo de sessões paralelas | `3` |
| `SESSION_TIMEOUT_SECONDS` | Timeout de inatividade da sessão | `300` |
| `DISCORD_OWNER_ID` | ID do usuário para @mencionar quando o Claude precisa de input | (opcional) |
| `COORDINATION_CHANNEL_ID` | ID do canal usado como fallback padrão para o canal AI Lounge | (opcional) |
| `WORKTREE_BASE_DIR` | Diretório base para escanear worktrees de sessão (ativa limpeza automática) | (opcional) |
| `CLI_SESSIONS_PATH` | Caminho para `~/.claude/projects` para descoberta de sessões CLI (habilita `/sync-sessions`) | (opcional) |
| `MENTION_ONLY_CHANNEL_IDS` | IDs de canal separados por vírgula onde o bot responde apenas quando @mencionado | (opcional) |
| `INLINE_REPLY_CHANNEL_IDS` | IDs de canal separados por vírgula onde o bot responde inline (sem criar thread) | (opcional) |
| `THREAD_INBOX_ENABLED` | Ativa a caixa de entrada persistente de threads (classifica sessões como `waiting`/`done`/`ambiguous` via `claude -p`; exibido no painel de threads) | `false` |
| `THREAD_AUTO_RENAME` | Renomeia automaticamente títulos de novas threads com Claude AI — gera um título curto e descritivo da primeira mensagem do usuário via chamada `claude -p` em segundo plano (sem atrasar o início da sessão) | `false` |

### Modos de Permissão — O Que Funciona no Modo `-p`

O Claude Code CLI é executado em **modo `-p` (não-interativo)** quando usado através do ccdb. Neste modo, o CLI **não pode solicitar permissões** — ferramentas que requerem aprovação são rejeitadas imediatamente. Esta é uma [restrição de design do CLI](https://code.claude.com/docs/en/headless), não uma limitação do ccdb.

| Modo | Comportamento no modo `-p` | Recomendação |
|------|----------------------|----------------|
| `default` | ❌ **Todas as ferramentas rejeitadas** — inutilizável | Não usar |
| `acceptEdits` | ⚠️ Edit/Write aprovados automaticamente, Bash rejeitado (Claude usa Write para operações de arquivo) | Opção mínima viável |
| `bypassPermissions` | ✅ Todas as ferramentas aprovadas | Funciona, mas prefira a opção abaixo |
| **`CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS=true`** | ✅ **Todas as ferramentas aprovadas** | **Recomendado** — ccdb já restringe o acesso via `allowed_user_ids` |

**Nossa recomendação:** Configure `CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS=true`. Como o ccdb controla quem pode interagir com o Claude via `allowed_user_ids`, as verificações de permissão no nível do CLI adicionam fricção sem benefício real de segurança. O «dangerously» no nome reflete o aviso geral do CLI; no contexto do ccdb onde o acesso já é controlado, é a escolha prática.

**Para controle granular**, use `CLAUDE_ALLOWED_TOOLS` para permitir ferramentas específicas sem bypassar completamente as permissões:

```env
# Exemplo: permitir operações de arquivo e execução de código, mas não acesso à web
CLAUDE_ALLOWED_TOOLS=Bash,Read,Write,Edit,Glob,Grep

# Exemplo: modo somente leitura — Claude pode explorar mas não modificar
CLAUDE_ALLOWED_TOOLS=Read,Glob,Grep
```

Nomes de ferramentas comuns: `Bash`, `Read`, `Write`, `Edit`, `Glob`, `Grep`, `WebFetch`, `WebSearch`, `NotebookEdit`. Configure `CLAUDE_PERMISSION_MODE=default` ao usar isso (outros modos podem sobrescrever).

> **Por que os botões de permissão não aparecem no Discord?** O modo `-p` do CLI nunca emite eventos `permission_request`, então não há nada para o ccdb exibir. Os botões `AskUserQuestion` que você vê (prompts de seleção do Claude) são um mecanismo diferente que funciona corretamente. Veja [#210](https://github.com/ebibibi/claude-code-discord-bridge/issues/210) para a investigação completa.

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
  main.py                  # Ponto de entrada autônomo (setup_bridge + carregador de Cogs personalizados)
  cli.py                   # Ponto de entrada CLI (comandos ccdb setup/start)
  setup.py                 # setup_bridge() — conexão de Cogs com uma chamada
  cog_loader.py            # Carregador dinâmico de Cogs personalizados (CUSTOM_COGS_DIR)
  bot.py                   # Classe Discord Bot
  protocols.py             # Protocolos compartilhados (DrainAware)
  concurrency.py           # Instruções de worktree + registro de sessões ativas
  lounge.py                # Construtor de prompts para AI Lounge
  session_sync.py          # Descoberta e importação de sessões CLI
  worktree.py              # WorktreeManager — ciclo de vida seguro de git worktree
  cogs/
    claude_chat.py         # Chat interativo (criação de threads, manipulação de mensagens)
    skill_command.py       # Comando slash /skill com autocomplete
    session_manage.py      # /sessions, /sync-sessions, /resume, /resume-info, /sync-settings
    session_sync.py        # Lógica de criação de threads e publicação para sync-sessions
    prompt_builder.py      # build_prompt_and_images() — função pura, sem estado Cog/Bot
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
  database/
    models.py              # Schema SQLite
    repository.py          # CRUD de sessões
    task_repo.py           # CRUD de tarefas agendadas
    ask_repo.py            # CRUD de AskUserQuestion pendentes
    notification_repo.py   # CRUD de notificações agendadas
    lounge_repo.py         # CRUD de mensagens do AI Lounge
    resume_repo.py         # CRUD de retomada ao iniciar
    settings_repo.py       # Configurações por servidor
  discord_ui/
    status.py              # Gerenciador de reações emoji (com debounce)
    chunker.py             # Divisão de mensagens com conhecimento de blocos e tabelas
    embeds.py              # Construtores de embeds do Discord
    views.py               # Botão de parada e componentes UI compartilhados
    ask_bus.py             # Bus de eventos para comunicação AskUserQuestion
    ask_view.py            # Botões/Menus de Seleção para AskUserQuestion
    ask_handler.py         # collect_ask_answers() — UI + ciclo de vida DB de AskUserQuestion
    streaming_manager.py   # StreamingMessageManager — edições de mensagem in-place com debounce
    tool_timer.py          # LiveToolTimer — contador de tempo decorrido para ferramentas longas
    thread_dashboard.py    # Embed fixado ao vivo mostrando estados de sessão
    plan_view.py           # Botões Aprovar/Cancelar para Plan Mode (ExitPlanMode)
    permission_view.py     # Botões Permitir/Negar para solicitações de permissão de ferramenta
    elicitation_view.py    # Interface Discord para MCP Elicitation (formulário Modal ou botão URL)
    file_sender.py         # Entrega de arquivos via .ccdb-attachments
  ext/
    api_server.py          # REST API (opcional, requer aiohttp)
  utils/
    logger.py              # Configuração de logging
```

### Filosofia de Design

- **Invocação CLI, não API** — Invoca `claude -p --output-format stream-json`, dando recursos completos do Claude Code (CLAUDE.md, skills, ferramentas, memória) sem reimplementá-los
- **Concorrência primeiro** — Múltiplas sessões simultâneas são o caso esperado, não um edge case; cada sessão recebe instruções de worktree, o registro e o AI Lounge cuidam do resto
- **Discord como cola** — Discord fornece UI, threads, reações, webhooks e notificações persistentes; sem frontend personalizado necessário
- **Framework, não aplicação** — Instale como pacote, adicione Cogs ao seu bot existente, configure via código
- **Extensibilidade sem código** — Adicione tarefas agendadas e disparadores webhook sem tocar no código fonte
- **Segurança pela simplicidade** — ~3000 linhas de Python auditáveis; apenas subprocess exec, sem expansão de shell

---

## Testes

```bash
uv run pytest tests/ -v --cov=claude_discord
```

1050+ testes cobrindo parser, chunker, repositório, runner, streaming, disparadores webhook, auto-atualização (incluindo o comando `/upgrade`, invocação de thread e botão de aprovação), REST API, UI do AskUserQuestion, painel de threads, tarefas agendadas, sincronização de sessões, AI Lounge, retomada na inicialização, troca de modelo, detecção de compactação, embeds de progresso do TodoWrite, e análise de eventos de permissão/elicitation/plan-mode.

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
