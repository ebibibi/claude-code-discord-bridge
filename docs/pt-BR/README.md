> **Note:** This is an auto-translated version of the original English documentation.
> If there are any discrepancies, the [English version](../../README.md) takes precedence.
> **Nota:** Esta é uma versão autotraduzida da documentação original em inglês.
> Em caso de discrepâncias, a [versão em inglês](../../README.md) prevalece.

# claude-code-discord-bridge

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Conecte [Claude Code](https://docs.anthropic.com/en/docs/claude-code) ao Discord e GitHub. Um framework que faz a ponte entre Claude Code CLI e Discord para **chat interativo, automação CI/CD e integração com fluxos de trabalho do GitHub**.

Claude Code é ótimo no terminal — mas pode fazer muito mais. Esta ponte permite **usar Claude Code no seu fluxo de desenvolvimento com GitHub**: sincronizar documentação automaticamente, revisar e mesclar PRs, e executar qualquer tarefa do Claude Code acionada pelo GitHub Actions. Tudo usando Discord como a cola universal.

**[English](../../README.md)** | **[日本語](../ja/README.md)** | **[简体中文](../zh-CN/README.md)** | **[한국어](../ko/README.md)** | **[Español](../es/README.md)** | **[Français](../fr/README.md)**

> **Aviso:** Este projeto não é afiliado, endossado ou oficialmente conectado à Anthropic. "Claude" e "Claude Code" são marcas registradas da Anthropic, PBC. Esta é uma ferramenta open source independente que interage com o Claude Code CLI.

> **Construído inteiramente pelo Claude Code.** Este projeto foi projetado, implementado, testado e documentado pelo próprio Claude Code — o agente de codificação com IA da Anthropic. O autor humano não leu o código fonte. Veja [Como este projeto foi construído](#como-este-projeto-foi-construído) para detalhes.

## Duas formas de usar

### 1. Chat interativo (Mobile / Desktop)

Use Claude Code do seu celular ou qualquer dispositivo com Discord. Cada conversa se torna uma thread com persistência completa de sessão.

```
Você (Discord)  →  Bridge  →  Claude Code CLI
      ↑                               ↓
      ←──── saída stream-json ────────←
```

### 2. Automação CI/CD (GitHub → Discord → Claude Code → GitHub)

Acione tarefas do Claude Code a partir do GitHub Actions via webhooks do Discord. Claude Code roda autonomamente — lendo código, atualizando docs, criando PRs e habilitando auto-merge.

```
GitHub Actions  →  Discord Webhook  →  Bridge  →  Claude Code CLI
                                                         ↓
GitHub PR (auto-merge)  ←  git push  ←  Claude Code  ←──┘
```

**Exemplo real:** A cada push para main, Claude Code analisa automaticamente as mudanças, atualiza documentação em inglês e japonês, cria um PR com resumo bilíngue e habilita auto-merge. Sem intervenção humana.

## Funcionalidades

### Chat interativo
- **Thread = Session** — Cada tarefa tem sua própria thread no Discord, mapeada 1:1 para uma sessão do Claude Code
- **Status em tempo real** — Reações emoji mostram o que Claude está fazendo (🧠 pensando, 🛠️ lendo arquivos, 💻 editando, 🌐 pesquisa web)
- **Texto em streaming** — Texto intermediário aparece enquanto Claude trabalha
- **Exibição de resultados de ferramentas** — Resultados mostrados como embeds em tempo real
- **Pensamento estendido** — O raciocínio de Claude aparece em embeds com spoiler (clique para revelar)
- **Persistência de sessão** — Continue conversas entre mensagens via `--resume`
- **Execução de skills** — Execute skills do Claude Code (`/skill goodmorning`) via comandos slash com autocomplete
- **Sessões concorrentes** — Execute múltiplas sessões em paralelo (limite configurável)

### Automação CI/CD
- **Gatilhos webhook** — Acione tarefas do Claude Code a partir do GitHub Actions ou qualquer sistema CI/CD
- **Auto-atualização** — Atualize automaticamente o bot quando pacotes upstream são publicados
- **REST API** — Notificações push para Discord de ferramentas externas (opcional, requer aiohttp)

### Segurança
- **Sem injeção de shell** — Apenas `asyncio.create_subprocess_exec`, nunca `shell=True`
- **Validação de ID de sessão** — Regex estrito antes de passar para `--resume`
- **Prevenção de injeção de flags** — Separador `--` antes de todos os prompts
- **Isolamento de segredos** — Token do bot e segredos removidos do ambiente do subprocesso
- **Autorização de usuário** — `allowed_user_ids` restringe quem pode invocar Claude

## Início rápido

### Requisitos

- Python 3.10+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) instalado e autenticado
- Token de bot Discord com Message Content intent habilitado
- [uv](https://docs.astral.sh/uv/) (recomendado) ou pip

### Execução independente

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
from claude_discord import ClaudeChatCog, ClaudeRunner, SessionRepository
from claude_discord.database.models import init_db

# Inicializar
await init_db("data/sessions.db")
repo = SessionRepository("data/sessions.db")
runner = ClaudeRunner(command="claude", model="sonnet")

# Adicionar ao bot existente
await bot.add_cog(ClaudeChatCog(bot, repo, runner))
```

Atualizar para a última versão:

```bash
uv lock --upgrade-package claude-code-discord-bridge && uv sync
```

## Testes

```bash
uv run pytest tests/ -v --cov=claude_discord
```

131 testes cobrindo parser, chunker, repositório, runner, streaming, webhook triggers, auto-upgrade e REST API.

## Como este projeto foi construído

**Todo o código foi escrito pelo [Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — o agente de codificação com IA da Anthropic. O autor humano ([@ebibibi](https://github.com/ebibibi)) forneceu requisitos e direção em linguagem natural, mas não leu ou editou manualmente o código fonte.

Isso significa:

- **Todo o código foi gerado por IA** — arquitetura, implementação, testes, documentação
- **O autor humano não pode garantir correção no nível do código** — revise o fonte se precisar de certeza
- **Relatórios de bugs e PRs são bem-vindos** — Claude Code provavelmente será usado para resolvê-los
- **Este é um exemplo real de software open source escrito por IA** — use como referência do que Claude Code pode construir

O projeto começou em 2026-02-18 e continua evoluindo através de conversas iterativas com Claude Code.

## Exemplo real

**[EbiBot](https://github.com/ebibibi/discord-bot)** — Um bot pessoal do Discord que usa claude-code-discord-bridge como dependência. Inclui sincronização automática de documentação (inglês + japonês), notificações push, watchdog do Todoist e integração CI/CD com GitHub Actions.

## Licença

MIT
