> **Note:** This is an auto-translated version of the original English documentation.
> If there are any discrepancies, the [English version](../../README.md) takes precedence.
> **Nota:** Esta es una versión autotraducida de la documentación original en inglés.
> En caso de discrepancias, la [versión en inglés](../../README.md) prevalece.

# claude-code-discord-bridge

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Conecta [Claude Code](https://docs.anthropic.com/en/docs/claude-code) con Discord y GitHub. Un framework que conecta Claude Code CLI con Discord para **chat interactivo, automatización CI/CD e integración con flujos de trabajo de GitHub**.

Claude Code es genial en la terminal, pero puede hacer mucho más. Este puente te permite **usar Claude Code en tu flujo de desarrollo con GitHub**: sincronizar documentación automáticamente, revisar y fusionar PRs, y ejecutar cualquier tarea de Claude Code activada por GitHub Actions. Todo usando Discord como el pegamento universal.

**[English](../../README.md)** | **[日本語](../ja/README.md)** | **[简体中文](../zh-CN/README.md)** | **[한국어](../ko/README.md)** | **[Português](../pt-BR/README.md)** | **[Français](../fr/README.md)**

> **Descargo de responsabilidad:** Este proyecto no está afiliado, respaldado ni conectado oficialmente con Anthropic. "Claude" y "Claude Code" son marcas registradas de Anthropic, PBC. Esta es una herramienta de código abierto independiente que interactúa con Claude Code CLI.

> **Construido completamente por Claude Code.** Este proyecto fue diseñado, implementado, probado y documentado por Claude Code, el agente de codificación con IA de Anthropic. El autor humano no ha leído el código fuente. Ver [Cómo se construyó este proyecto](#cómo-se-construyó-este-proyecto) para más detalles.

## Dos formas de usarlo

### 1. Chat interactivo (Móvil / Escritorio)

Usa Claude Code desde tu teléfono o cualquier dispositivo con Discord. Cada conversación se convierte en un hilo con persistencia completa de sesión.

```
Tú (Discord)  →  Bridge  →  Claude Code CLI
    ↑                              ↓
    ←──── salida stream-json ─────←
```

### 2. Automatización CI/CD (GitHub → Discord → Claude Code → GitHub)

Activa tareas de Claude Code desde GitHub Actions mediante webhooks de Discord. Claude Code funciona de forma autónoma: lee código, actualiza documentación, crea PRs y habilita auto-merge.

```
GitHub Actions  →  Discord Webhook  →  Bridge  →  Claude Code CLI
                                                         ↓
GitHub PR (auto-merge)  ←  git push  ←  Claude Code  ←──┘
```

**Ejemplo real:** En cada push a main, Claude Code analiza automáticamente los cambios, actualiza la documentación en inglés y japonés, crea un PR con resumen bilingüe y habilita auto-merge. Sin intervención humana.

## Características

### Chat interactivo
- **Thread = Session** — Cada tarea tiene su propio hilo de Discord, mapeado 1:1 con una sesión de Claude Code
- **Estado en tiempo real** — Reacciones emoji muestran qué está haciendo Claude (🧠 pensando, 🛠️ leyendo archivos, 💻 editando, 🌐 búsqueda web)
- **Texto en streaming** — El texto intermedio aparece mientras Claude trabaja
- **Visualización de resultados de herramientas** — Resultados mostrados como embeds en tiempo real
- **Pensamiento extendido** — El razonamiento de Claude aparece en embeds con spoiler (clic para revelar)
- **Persistencia de sesión** — Continúa conversaciones entre mensajes via `--resume`
- **Ejecución de skills** — Ejecuta skills de Claude Code (`/skill goodmorning`) via comandos slash con autocompletado
- **Sesiones concurrentes** — Ejecuta múltiples sesiones en paralelo (límite configurable)

### Automatización CI/CD
- **Disparadores webhook** — Activa tareas de Claude Code desde GitHub Actions o cualquier sistema CI/CD
- **Auto-actualización** — Actualiza automáticamente el bot cuando se publica un paquete upstream
- **REST API** — Notificaciones push a Discord desde herramientas externas (opcional, requiere aiohttp)

### Seguridad
- **Sin inyección de shell** — Solo `asyncio.create_subprocess_exec`, nunca `shell=True`
- **Validación de ID de sesión** — Regex estricto antes de pasar a `--resume`
- **Prevención de inyección de flags** — Separador `--` antes de todos los prompts
- **Aislamiento de secretos** — Token del bot y secretos eliminados del entorno del subproceso
- **Autorización de usuario** — `allowed_user_ids` restringe quién puede invocar a Claude

## Inicio rápido

### Requisitos

- Python 3.10+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) instalado y autenticado
- Token de Discord bot con Message Content intent habilitado
- [uv](https://docs.astral.sh/uv/) (recomendado) o pip

### Ejecución independiente

```bash
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge

cp .env.example .env
# Edita .env con tu token de bot y ID de canal

uv run python -m claude_discord.main
```

### Instalar como paquete

Si ya tienes un bot de discord.py en ejecución (Discord solo permite una conexión Gateway por token):

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

# Agregar a tu bot existente
await bot.add_cog(ClaudeChatCog(bot, repo, runner))
```

Actualizar a la última versión:

```bash
uv lock --upgrade-package claude-code-discord-bridge && uv sync
```

## Pruebas

```bash
uv run pytest tests/ -v --cov=claude_discord
```

131 pruebas cubriendo parser, chunker, repositorio, runner, streaming, webhook triggers, auto-upgrade y REST API.

## Cómo se construyó este proyecto

**Todo el código fue escrito por [Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — el agente de codificación con IA de Anthropic. El autor humano ([@ebibibi](https://github.com/ebibibi)) proporcionó requisitos y dirección en lenguaje natural, pero no leyó ni editó manualmente el código fuente.

Esto significa:

- **Todo el código fue generado por IA** — arquitectura, implementación, pruebas, documentación
- **El autor humano no puede garantizar la corrección a nivel de código** — revisa el código fuente si necesitas certeza
- **Reportes de bugs y PRs son bienvenidos** — Claude Code probablemente será usado para abordarlos
- **Este es un ejemplo real de software open source escrito por IA** — úsalo como referencia de lo que Claude Code puede construir

El proyecto comenzó el 2026-02-18 y continúa evolucionando a través de conversaciones iterativas con Claude Code.

## Ejemplo real

**[EbiBot](https://github.com/ebibibi/discord-bot)** — Un bot personal de Discord que usa claude-code-discord-bridge como dependencia. Incluye sincronización automática de documentación (inglés + japonés), notificaciones push, watchdog de Todoist e integración CI/CD con GitHub Actions.

## Licencia

MIT
