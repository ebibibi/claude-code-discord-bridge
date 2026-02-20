> **Note:** This is an auto-translated version of the original English documentation.
> If there are any discrepancies, the [English version](../../README.md) takes precedence.
> **Nota:** Esta es una versión autotraducida de la documentación original en inglés.
> En caso de discrepancias, la [versión en inglés](../../README.md) prevalece.

# claude-code-discord-bridge

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Conecta [Claude Code](https://docs.anthropic.com/en/docs/claude-code) a Discord y GitHub. Un framework que une Claude Code CLI con Discord para **chat interactivo, automatización CI/CD e integración de flujos de trabajo con GitHub**.

Claude Code es excelente en la terminal, pero puede hacer mucho más. Este puente te permite **usar Claude Code en tu flujo de desarrollo con GitHub**: sincronizar documentación automáticamente, revisar y fusionar PRs, y ejecutar cualquier tarea de Claude Code activada desde GitHub Actions. Todo a través de Discord como pegamento universal.

**[English](../../README.md)** | **[日本語](../ja/README.md)** | **[简体中文](../zh-CN/README.md)** | **[한국어](../ko/README.md)** | **[Português](../pt-BR/README.md)** | **[Français](../fr/README.md)**

> **Aviso legal:** Este proyecto no está afiliado, respaldado ni oficialmente conectado a Anthropic. "Claude" y "Claude Code" son marcas registradas de Anthropic, PBC. Esta es una herramienta de código abierto independiente que interactúa con el Claude Code CLI.

> **Construido completamente por Claude Code.** Este proyecto fue diseñado, implementado, probado y documentado por el propio Claude Code — el agente de codificación con IA de Anthropic. El autor humano no ha leído el código fuente. Consulta [Cómo se construyó este proyecto](#cómo-se-construyó-este-proyecto) para más detalles.

## Dos formas de usarlo

### 1. Chat interactivo (Móvil / Escritorio)

Usa Claude Code desde tu teléfono o cualquier dispositivo con Discord. Cada conversación se convierte en un hilo con persistencia de sesión completa.

```
Tú (Discord)  →  Bridge  →  Claude Code CLI
    ↑                              ↓
    ←──── salida stream-json ──────←
```

### 2. Automatización CI/CD (GitHub → Discord → Claude Code → GitHub)

Activa tareas de Claude Code desde GitHub Actions mediante webhooks de Discord. Claude Code se ejecuta de forma autónoma — leyendo código, actualizando docs, creando PRs y habilitando fusión automática.

```
GitHub Actions  →  Discord Webhook  →  Bridge  →  Claude Code CLI
                                                         ↓
GitHub PR (auto-merge)  ←  git push  ←  Claude Code  ←──┘
```

**Ejemplo real:** En cada push a main, Claude Code analiza automáticamente los cambios, actualiza la documentación en inglés y japonés, crea un PR con un resumen bilingüe y habilita la fusión automática. Sin intervención humana.

## Características

### Chat interactivo
- **Thread = Session** — Cada tarea tiene su propio hilo de Discord, mapeado 1:1 a una sesión de Claude Code
- **Estado en tiempo real** — Las reacciones con emojis muestran qué está haciendo Claude (🧠 pensando, 🛠️ leyendo archivos, 💻 editando, 🌐 búsqueda web)
- **Texto en streaming** — El texto intermedio aparece mientras Claude trabaja, no solo al final
- **Visualización de resultados de herramientas** — Los resultados del uso de herramientas se muestran como embeds en tiempo real
- **Temporización de herramientas en vivo** — Los embeds de herramientas en progreso actualizan el tiempo transcurrido cada 10s para comandos de larga duración (autenticación, compilaciones), para que siempre sepas que Claude sigue trabajando
- **Pensamiento extendido** — El razonamiento de Claude aparece como embeds con etiqueta spoiler (haz clic para revelar)
- **Persistencia de sesión** — Continúa conversaciones entre mensajes con `--resume`
- **Ejecución de skills** — Ejecuta skills de Claude Code con `/skill` con autocompletado, argumentos opcionales y reanudación en hilo
- **Sesiones concurrentes** — Ejecuta múltiples sesiones en paralelo (límite configurable)
- **Detener sin borrar** — `/stop` detiene una sesión en curso preservándola para reanudar
- **Soporte de archivos adjuntos** — Los adjuntos de texto se añaden automáticamente al prompt (hasta 5 archivos, 50 KB cada uno)
- **Notificaciones de tiempo de espera** — Embed dedicado con segundos transcurridos y guía cuando una sesión expira
- **Preguntas interactivas** — Cuando Claude llama a `AskUserQuestion`, el bot renderiza Botones de Discord o un Select Menu y reanuda la sesión con tu respuesta
- **Panel de estado de sesión** — Un embed fijo en vivo en el canal principal muestra qué hilos están procesando vs. esperando entrada; el propietario recibe @mention cuando Claude necesita una respuesta
- **Coordinación multisesión** — Con `COORDINATION_CHANNEL_ID` configurado, cada sesión difunde eventos de inicio/fin a un canal compartido para que las sesiones concurrentes se mantengan informadas

### Tareas programadas (SchedulerCog)
- **Tareas periódicas de Claude Code** — Registra tareas vía chat de Discord o API REST; se ejecutan en un intervalo configurable
- **Respaldado por SQLite** — Las tareas persisten entre reinicios; gestionadas mediante endpoints `/api/tasks`
- **Programación sin código** — Claude Code puede auto-registrar nuevas tareas con la herramienta Bash durante una sesión; sin reinicios del bot ni cambios de código
- **Único bucle maestro** — Un bucle `discord.ext.tasks` de 30 segundos despacha todas las tareas, manteniendo baja la sobrecarga

### Automatización CI/CD
- **Activadores de webhooks** — Activa tareas de Claude Code desde GitHub Actions o cualquier sistema CI/CD
- **Actualización automática** — Actualiza automáticamente el bot cuando se publican paquetes upstream
- **API REST** — Envía notificaciones y gestiona tareas programadas desde herramientas externas (opcional, requiere aiohttp)

### Seguridad
- **Sin inyección de shell** — Solo `asyncio.create_subprocess_exec`, nunca `shell=True`
- **Validación de ID de sesión** — Regex estricta antes de pasar a `--resume`
- **Prevención de inyección de flags** — Separador `--` antes de todos los prompts
- **Aislamiento de secretos** — Token del bot y secretos eliminados del entorno del subproceso
- **Autorización de usuarios** — `allowed_user_ids` restringe quién puede invocar a Claude

## Skills

Ejecuta [skills de Claude Code](https://docs.anthropic.com/en/docs/claude-code) directamente desde Discord mediante el comando de barra `/skill`.

```
/skill name:goodmorning                      → ejecuta /goodmorning
/skill name:todoist args:filter "today"      → ejecuta /todoist filter "today"
/skills                                      → lista todas las skills disponibles
```

**Características:**
- **Autocompletado** — Escribe para filtrar; nombres y descripciones son buscables
- **Argumentos** — Pasa argumentos adicionales mediante el parámetro `args`
- **Reanudación en hilo** — Usa `/skill` dentro de un hilo de Claude existente para ejecutar la skill en la sesión actual en lugar de crear un nuevo hilo
- **Recarga en caliente** — Las nuevas skills añadidas a `~/.claude/skills/` se detectan automáticamente (intervalo de actualización de 60s, sin reinicio necesario)

## Inicio rápido

### Requisitos

- Python 3.10+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) instalado y autenticado
- Token de bot de Discord con Message Content intent habilitado
- [uv](https://docs.astral.sh/uv/) (recomendado) o pip

### Ejecutar de forma autónoma

```bash
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge

cp .env.example .env
# Edita .env con tu token de bot y el ID del canal

uv run python -m claude_discord.main
```

### Instalar como paquete

Si ya tienes un bot de discord.py en ejecución (Discord solo permite una conexión Gateway por token):

```bash
uv add git+https://github.com/ebibibi/claude-code-discord-bridge.git
```

```python
from claude_discord import ClaudeRunner, setup_bridge

runner = ClaudeRunner(command="claude", model="sonnet")

# Una llamada registra todos los Cogs — las nuevas características se incluyen automáticamente
await setup_bridge(
    bot,
    runner,
    session_db_path="data/sessions.db",
    claude_channel_id=YOUR_CHANNEL_ID,
    allowed_user_ids={YOUR_USER_ID},
)
```

`setup_bridge()` conecta automáticamente `ClaudeChatCog`, `SkillCommandCog`, `SessionManageCog` y `SchedulerCog`. Cuando se añaden nuevos Cogs a ccdb, aparecen automáticamente — sin cambios de código en el consumidor.

<details>
<summary>Conexión manual (avanzado)</summary>

```python
from claude_discord import ClaudeChatCog, ClaudeRunner, SessionRepository
from claude_discord.database.models import init_db

await init_db("data/sessions.db")
repo = SessionRepository("data/sessions.db")
runner = ClaudeRunner(command="claude", model="sonnet")

await bot.add_cog(ClaudeChatCog(bot, repo, runner))
```
</details>

Actualizar a la última versión:

```bash
uv lock --upgrade-package claude-code-discord-bridge && uv sync
```

## Configuración

| Variable | Descripción | Por defecto |
|----------|-------------|-------------|
| `DISCORD_BOT_TOKEN` | Token de bot de Discord | (requerido) |
| `DISCORD_CHANNEL_ID` | ID de canal para chat de Claude | (requerido) |
| `CLAUDE_COMMAND` | Ruta al Claude Code CLI | `claude` |
| `CLAUDE_MODEL` | Modelo a usar | `sonnet` |
| `CLAUDE_PERMISSION_MODE` | Modo de permisos para CLI | `acceptEdits` |
| `CLAUDE_WORKING_DIR` | Directorio de trabajo para Claude | directorio actual |
| `MAX_CONCURRENT_SESSIONS` | Máximo de sesiones paralelas | `3` |
| `SESSION_TIMEOUT_SECONDS` | Tiempo de espera por inactividad | `300` |
| `DISCORD_OWNER_ID` | ID de usuario de Discord para @mention cuando Claude necesita entrada | (opcional) |
| `COORDINATION_CHANNEL_ID` | ID de canal para difusión de coordinación multisesión | (opcional) |

## Configuración del bot de Discord

1. Crea una nueva aplicación en el [Portal de desarrolladores de Discord](https://discord.com/developers/applications)
2. Crea un bot y copia el token
3. Habilita **Message Content Intent** en Privileged Gateway Intents
4. Invita al bot a tu servidor con estos permisos:
   - Send Messages
   - Create Public Threads
   - Send Messages in Threads
   - Add Reactions
   - Manage Messages (para limpiar reacciones)
   - Read Message History

## Automatización GitHub + Claude Code

El sistema de activadores de webhooks te permite construir flujos de trabajo CI/CD completamente autónomos donde Claude Code actúa como un agente inteligente — no solo ejecutando scripts, sino entendiendo los cambios de código y tomando decisiones.

### Ejemplo: Sincronización automática de documentación

En cada push a main, Claude Code:
1. Obtiene los últimos cambios y analiza el diff
2. Actualiza la documentación en inglés si cambió el código fuente
3. Traduce al japonés (o cualquier idioma objetivo)
4. Crea un PR con un resumen bilingüe
5. Habilita la fusión automática — el PR se fusiona automáticamente cuando pasa CI

**Flujo de trabajo de GitHub Actions:**

```yaml
# .github/workflows/docs-sync.yml
name: Documentation Sync
on:
  push:
    branches: [main]
jobs:
  trigger:
    # Omite los commits del propio docs-sync (prevención de bucle infinito)
    if: "!contains(github.event.head_commit.message, '[docs-sync]')"
    runs-on: ubuntu-latest
    steps:
      - run: |
          curl -X POST "${{ secrets.DISCORD_WEBHOOK_URL }}" \
            -H "Content-Type: application/json" \
            -d '{"content": "🔄 docs-sync"}'
```

**Configuración del bot:**

```python
from claude_discord import WebhookTriggerCog, WebhookTrigger, ClaudeRunner

runner = ClaudeRunner(command="claude", model="sonnet")

triggers = {
    "🔄 docs-sync": WebhookTrigger(
        prompt="Analiza cambios, actualiza docs, crea un PR con resumen bilingüe, habilita auto-merge.",
        working_dir="/home/user/my-project",
        timeout=600,
    ),
    "🚀 deploy": WebhookTrigger(
        prompt="Despliega al entorno de staging.",
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

**Seguridad:** Solo se procesan los mensajes de webhook. `allowed_webhook_ids` opcional para control más estricto. Los prompts se definen en el servidor — los webhooks solo seleccionan qué activador disparar.

### Ejemplo: Auto-aprobación de PRs del propietario

Aprueba y fusiona automáticamente tus propios PRs después de que pase CI:

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

## Tareas programadas

`SchedulerCog` ejecuta tareas periódicas de Claude Code almacenadas en SQLite. Las tareas se registran en tiempo de ejecución mediante la API REST — sin cambios de código ni reinicios del bot.

### Registrar una tarea (vía API REST)

```bash
curl -X POST http://localhost:8080/api/tasks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secret-token" \
  -d '{
    "name": "daily-standup",
    "prompt": "Revisa los issues abiertos de GitHub y publica un resumen breve en Discord.",
    "interval_seconds": 86400,
    "channel_id": 123456789
  }'
```

### Registrar una tarea (Claude se auto-registra durante una sesión)

Claude Code puede registrar sus propias tareas recurrentes usando la herramienta Bash — sin configuración manual:

```
# Dentro de una sesión de Claude Code, Claude ejecuta:
curl -X POST $CCDB_API_URL/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"name": "health-check", "prompt": "Ejecuta el conjunto de pruebas e informa los resultados.", "interval_seconds": 3600}'
```

`CCDB_API_URL` se inyecta automáticamente en el entorno del subproceso de Claude cuando `api_port` está configurado en el `ClaudeRunner`.

## Actualización automática

Actualiza automáticamente el bot cuando se publica un paquete upstream.

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

**Pipeline:** Push upstream → CI webhook → `🔄 bot-upgrade` → `uv lock --upgrade-package` → `uv sync` → reinicio del servicio.

### Drenado elegante (DrainAware)

Antes de reiniciar, AutoUpgradeCog espera a que terminen todas las sesiones activas. Cualquier Cog que implemente una propiedad `active_count` (cumpliendo el protocolo `DrainAware`) se descubre automáticamente — sin necesidad de lambda `drain_check` manual.

Cogs DrainAware incorporados: `ClaudeChatCog`, `WebhookTriggerCog`.

Para hacer tu propio Cog compatible con el drenado, simplemente añade una propiedad `active_count`:

```python
class MyCog(commands.Cog):
    @property
    def active_count(self) -> int:
        return len(self._running_tasks)
```

Aún puedes pasar un callable `drain_check` explícito para anular el autodescubrimiento.

### Aprobación de reinicio

Para escenarios de auto-actualización (ej. actualizar el bot desde su propia sesión de Discord), habilita `restart_approval` para prevenir reinicios automáticos:

```python
config = UpgradeConfig(
    package_name="claude-code-discord-bridge",
    trigger_prefix="🔄 bot-upgrade",
    working_dir="/home/user/my-bot",
    restart_command=["sudo", "systemctl", "restart", "my-bot.service"],
    restart_approval=True,
)
```

Con `restart_approval=True`, tras actualizar el paquete el bot publica un mensaje solicitando aprobación. Reacciona con ✅ para activar el reinicio. El bot envía recordatorios periódicos hasta que se apruebe.

## API REST

API REST opcional para enviar notificaciones a Discord desde herramientas externas. Requiere aiohttp:

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
    api_secret="your-secret-token",  # Autenticación Bearer opcional
)
await api.start()
```

### Endpoints

**Notificaciones**

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/api/health` | Verificación de estado |
| POST | `/api/notify` | Enviar notificación inmediata |
| POST | `/api/schedule` | Programar notificación para más tarde |
| GET | `/api/scheduled` | Listar notificaciones pendientes |
| DELETE | `/api/scheduled/{id}` | Cancelar una notificación programada |

**Tareas programadas** (requiere `SchedulerCog`)

| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/api/tasks` | Registrar una nueva tarea periódica de Claude Code |
| GET | `/api/tasks` | Listar todas las tareas registradas |
| DELETE | `/api/tasks/{id}` | Eliminar una tarea programada |
| PATCH | `/api/tasks/{id}` | Actualizar tarea (habilitar/deshabilitar, prompt, intervalo) |

### Ejemplos

```bash
# Verificación de estado
curl http://localhost:8080/api/health

# Enviar notificación
curl -X POST http://localhost:8080/api/notify \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secret-token" \
  -d '{"message": "¡Build exitoso!", "title": "CI/CD"}'

# Programar notificación
curl -X POST http://localhost:8080/api/schedule \
  -H "Content-Type: application/json" \
  -d '{"message": "Hora de revisar los PRs", "scheduled_at": "2026-01-01T09:00:00"}'
```

## Arquitectura

```
claude_discord/
  main.py                  # Punto de entrada autónomo
  bot.py                   # Clase Discord Bot
  setup.py                 # setup_bridge() — fábrica de un solo uso para todos los Cogs
  cogs/
    claude_chat.py         # Chat interactivo (creación de hilos, manejo de mensajes)
    skill_command.py       # Comando de barra /skill con autocompletado
    webhook_trigger.py     # Webhook → ejecución de tarea Claude Code (CI/CD)
    auto_upgrade.py        # Webhook → actualización del paquete + reinicio
    scheduler.py           # Tareas periódicas Claude Code (respaldado por SQLite, bucle maestro de 30s)
    _run_helper.py         # Lógica de ejecución compartida del Claude CLI
  claude/
    runner.py              # Gestor de subprocesos Claude CLI
    parser.py              # Parser de eventos stream-json
    types.py               # Definiciones de tipos para mensajes SDK
  database/
    models.py              # Esquema SQLite
    repository.py          # Operaciones CRUD de sesiones
    ask_repo.py            # CRUD de AskUserQuestion pendientes (recuperación tras reinicio)
    notification_repo.py   # CRUD de notificaciones programadas
    task_repo.py           # CRUD de tareas programadas (SchedulerCog)
  coordination/
    service.py             # CoordinationService — publica eventos de ciclo de vida de sesión en canal compartido
  discord_ui/
    status.py              # Gestor de estado de reacciones con emojis (con debounce)
    chunker.py             # División de mensajes con conciencia de bloques de código y tablas
    embeds.py              # Constructores de embeds de Discord
    ask_view.py            # Botones de Discord/Select Menus para AskUserQuestion
    ask_bus.py             # Enrutamiento de bus para botones AskView persistentes (sobrevive reinicios)
    thread_dashboard.py    # Embed fijo en vivo que muestra estados de sesión por hilo
  ext/
    api_server.py          # Servidor API REST (opcional, requiere aiohttp)
                           # Incluye endpoints /api/tasks para SchedulerCog
  utils/
    logger.py              # Configuración de logging
```

### Filosofía de diseño

- **Spawn de CLI, no API** — Invocamos `claude -p --output-format stream-json`, obteniendo todas las funciones de Claude Code (CLAUDE.md, skills, herramientas, memoria) gratis
- **Discord como pegamento** — Discord proporciona la interfaz, el threading, las notificaciones y la infraestructura de webhooks
- **Framework, no aplicación** — Instala como paquete, añade Cogs a tu bot existente, configura mediante código
- **Seguridad por simplicidad** — ~2500 líneas de Python auditable, sin ejecución de shell, sin rutas de código arbitrarias

## Pruebas

```bash
uv run pytest tests/ -v --cov=claude_discord
```

473 pruebas cubriendo parser, chunker, repositorio, runner, streaming, webhook triggers, auto-upgrade, REST API, AskUserQuestion UI, panel de estado de hilos, SchedulerCog y repositorio de tareas.

## Cómo se construyó este proyecto

**Todo este código base fue escrito por [Claude Code](https://docs.anthropic.com/en/docs/claude-code)**, el agente de codificación con IA de Anthropic. El autor humano ([@ebibibi](https://github.com/ebibibi)) proporcionó requisitos y dirección en lenguaje natural, pero no leyó ni editó manualmente el código fuente.

Esto significa:

- **Todo el código fue generado por IA** — arquitectura, implementación, pruebas, documentación
- **El autor humano no puede garantizar la corrección a nivel de código** — revisa el código fuente si necesitas certeza
- **Los reportes de bugs y PRs son bienvenidos** — Claude Code probablemente será usado para abordarlos también
- **Este es un ejemplo real de software de código abierto escrito por IA** — úsalo como referencia de lo que Claude Code puede construir

El proyecto comenzó el 2026-02-18 y continúa evolucionando a través de conversaciones iterativas con Claude Code.

## Ejemplo del mundo real

**[EbiBot](https://github.com/ebibibi/discord-bot)** — Un bot personal de Discord que usa claude-code-discord-bridge como dependencia de paquete. Incluye sincronización automática de documentación (inglés + japonés), notificaciones push, watchdog de Todoist e integración CI/CD con GitHub Actions. Úsalo como referencia para construir tu propio bot sobre este framework.

## Inspirado en

- [OpenClaw](https://github.com/openclaw/openclaw) — Reacciones de estado con emojis, debouncing de mensajes, chunking con conciencia de bloques de código
- [claude-code-discord-bot](https://github.com/timoconnellaus/claude-code-discord-bot) — Enfoque CLI spawn + stream-json
- [claude-code-discord](https://github.com/zebbern/claude-code-discord) — Patrones de control de permisos
- [claude-sandbox-bot](https://github.com/RhysSullivan/claude-sandbox-bot) — Modelo de hilo por conversación

## Licencia

MIT
