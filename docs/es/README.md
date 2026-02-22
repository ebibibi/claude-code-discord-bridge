> **Note:** This is an auto-translated version of the original English documentation.
> If there are any discrepancies, the [English version](../../README.md) takes precedence.
> **Nota:** Esta es una versión autotraducida de la documentación original en inglés.
> En caso de discrepancias, la [versión en inglés](../../README.md) prevalece.

# claude-code-discord-bridge

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Ejecuta múltiples sesiones de Claude Code en paralelo — de forma segura — a través de Discord.**

Cada hilo de Discord se convierte en una sesión aislada de Claude Code. Inicia tantas como necesites: trabaja en una funcionalidad en un hilo, revisa un PR en otro, ejecuta una tarea programada en un tercero. El bridge gestiona la coordinación automáticamente para que las sesiones concurrentes no interfieran entre sí.

**[English](../../README.md)** | **[日本語](../ja/README.md)** | **[简体中文](../zh-CN/README.md)** | **[한국어](../ko/README.md)** | **[Português](../pt-BR/README.md)** | **[Français](../fr/README.md)**

> **Aviso legal:** Este proyecto no está afiliado, respaldado ni conectado oficialmente con Anthropic. "Claude" y "Claude Code" son marcas registradas de Anthropic, PBC. Esta es una herramienta de código abierto independiente que interactúa con Claude Code CLI.

> **Construido completamente por Claude Code.** Todo este código base — arquitectura, implementación, pruebas, documentación — fue escrito por Claude Code. El autor humano proporcionó requisitos y dirección en lenguaje natural, pero no leyó ni editó manualmente el código fuente. Ver [Cómo se construyó este proyecto](#cómo-se-construyó-este-proyecto).

---

## La Gran Idea: Sesiones Paralelas Sin Miedo

Cuando envías tareas a Claude Code en hilos separados de Discord, el bridge hace tres cosas automáticamente:

1. **Inyección de aviso de concurrencia** — El prompt de sistema de cada sesión incluye instrucciones obligatorias: crea un git worktree, trabaja solo dentro de él, nunca toques el directorio de trabajo principal directamente.

2. **Registro de sesiones activas** — Cada sesión en ejecución conoce las demás. Si dos sesiones están a punto de modificar el mismo repositorio, pueden coordinarse en lugar de entrar en conflicto.

3. **Canal de coordinación** — Un canal de Discord compartido donde las sesiones transmiten eventos de inicio/fin. Tanto Claude como los humanos pueden ver de un vistazo lo que ocurre en todos los hilos activos.

```
Hilo A (funcionalidad) ──→  Claude Code (worktree-A)
Hilo B (revisión PR)   ──→  Claude Code (worktree-B)
Hilo C (docs)          ──→  Claude Code (worktree-C)
           ↓ eventos de ciclo de vida
   #canal-coordinación
   "A: iniciando refactor de autenticación"
   "B: revisando PR #42"
   "C: actualizando README"
```

Sin condiciones de carrera. Sin trabajo perdido. Sin sorpresas al hacer merge.

---

## Qué Puedes Hacer

### Chat Interactivo (Móvil / Escritorio)

Usa Claude Code desde cualquier lugar donde funcione Discord — teléfono, tablet o escritorio. Cada mensaje crea o continúa un hilo, mapeado 1:1 a una sesión persistente de Claude Code.

### Desarrollo Paralelo

Abre múltiples hilos simultáneamente. Cada uno es una sesión independiente de Claude Code con su propio contexto, directorio de trabajo y git worktree. Patrones útiles:

- **Funcionalidad + revisión en paralelo**: Inicia una funcionalidad en un hilo mientras Claude revisa un PR en otro.
- **Múltiples colaboradores**: Diferentes miembros del equipo tienen su propio hilo; las sesiones se mantienen al tanto entre sí a través del canal de coordinación.
- **Experimenta con seguridad**: Prueba un enfoque en el hilo A mientras el hilo B se mantiene en código estable.

### Tareas Programadas (SchedulerCog)

Registra tareas periódicas de Claude Code desde una conversación de Discord o vía REST API — sin cambios de código, sin redeploys. Las tareas se almacenan en SQLite y se ejecutan según un horario configurable. Claude puede auto-registrar tareas durante una sesión usando `POST /api/tasks`.

```
/skill name:goodmorning         → se ejecuta inmediatamente
Claude llama POST /api/tasks   → registra tarea periódica
SchedulerCog (bucle cada 30s)  → ejecuta tareas cuando toca
```

### Automatización CI/CD

Activa tareas de Claude Code desde GitHub Actions vía webhooks de Discord. Claude se ejecuta de forma autónoma — lee código, actualiza docs, crea PRs, activa auto-merge.

```
GitHub Actions → Discord Webhook → Bridge → Claude Code CLI
                                                  ↓
GitHub PR ←── git push ←── Claude Code ──────────┘
```

**Ejemplo real:** En cada push a `main`, Claude analiza el diff, actualiza documentación en inglés + japonés, crea un PR con resumen bilingüe y activa auto-merge. Cero interacción humana.

### Sincronización de Sesiones

¿Ya usas Claude Code CLI directamente? Sincroniza tus sesiones de terminal existentes en hilos de Discord con `/sync-sessions`. Rellena mensajes de conversación recientes para que puedas continuar una sesión CLI desde tu teléfono sin perder contexto.

### Creación Programática de Sesiones

Crea nuevas sesiones de Claude Code desde scripts, GitHub Actions u otras sesiones de Claude — sin interacción con mensajes de Discord.

```bash
# Desde otra sesión de Claude o un script CI:
curl -X POST "$CCDB_API_URL/api/spawn" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Ejecutar análisis de seguridad en el repositorio", "thread_name": "Análisis de Seguridad"}'
# Devuelve inmediatamente con el ID del hilo; Claude corre en segundo plano
```

Los subprocesos de Claude reciben `DISCORD_THREAD_ID` como variable de entorno, por lo que una sesión en ejecución puede crear sesiones hijas para paralelizar el trabajo.

### Reanudación al Inicio

Si el bot se reinicia a mitad de sesión, las sesiones de Claude interrumpidas se reanudan automáticamente cuando el bot vuelve a estar en línea. Las sesiones se marcan para reanudar de tres formas:

- **Automático (reinicio por actualización)** — `AutoUpgradeCog` toma una instantánea de todas las sesiones activas justo antes de un reinicio por actualización de paquete y las marca automáticamente.
- **Automático (cualquier apagado)** — `ClaudeChatCog.cog_unload()` marca todas las sesiones en ejecución cuando el bot se apaga por cualquier mecanismo (`systemctl stop`, `bot.close()`, SIGTERM, etc.).
- **Manual** — Cualquier sesión puede llamar a `POST /api/mark-resume` directamente.

---

## Características

### Chat Interactivo
- **Thread = Session** — Mapeo 1:1 entre hilo de Discord y sesión de Claude Code
- **Estado en tiempo real** — Reacciones emoji: 🧠 pensando, 🛠️ leyendo archivos, 💻 editando, 🌐 búsqueda web
- **Texto en streaming** — El texto intermedio aparece mientras Claude trabaja
- **Embeds de resultados de herramientas** — Resultados en vivo con tiempo transcurrido que aumenta cada 10s
- **Pensamiento extendido** — Razonamiento mostrado como embeds con spoiler (clic para revelar)
- **Persistencia de sesión** — Reanuda conversaciones entre mensajes via `--resume`
- **Ejecución de skills** — Comando `/skill` con autocompletado, argumentos opcionales, reanudación en hilo
- **Hot reload** — Los nuevos skills añadidos a `~/.claude/skills/` se detectan automáticamente (refresco cada 60s, sin reinicio)
- **Sesiones concurrentes** — Múltiples sesiones en paralelo con límite configurable
- **Parar sin borrar** — `/stop` detiene una sesión preservándola para reanudar
- **Soporte de adjuntos** — Archivos de texto añadidos automáticamente al prompt (hasta 5 × 50 KB)
- **Notificaciones de timeout** — Embed con tiempo transcurrido y guía de reanudación al agotar tiempo
- **Preguntas interactivas** — `AskUserQuestion` se renderiza como Botones de Discord o Menú de Selección; la sesión se reanuda con tu respuesta; los botones sobreviven reinicios del bot
- **Panel de hilos** — Embed fijo en vivo mostrando qué hilos están activos vs. en espera; el propietario es @mencionado cuando se necesita entrada
- **Uso de tokens** — Tasa de aciertos de caché y recuento de tokens mostrados en el embed de sesión completada

### Concurrencia y Coordinación
- **Instrucciones de worktree auto-inyectadas** — Cada sesión recibe instrucciones para usar `git worktree` antes de tocar cualquier archivo
- **Limpieza automática de worktrees** — Los worktrees de sesión (`wt-{thread_id}`) se eliminan automáticamente al terminar la sesión y al iniciar el bot; los worktrees con cambios nunca se eliminan automáticamente (invariante de seguridad)
- **Registro de sesiones activas** — Registro en memoria; cada sesión ve lo que hacen las demás
- **Canal de coordinación** — Canal compartido opcional para transmisiones de ciclo de vida entre sesiones
- **Scripts de coordinación** — Claude puede llamar a `coord_post.py` / `coord_read.py` desde una sesión para publicar y leer eventos

### Tareas Programadas
- **SchedulerCog** — Ejecutor de tareas periódicas respaldado por SQLite con un bucle maestro de 30 segundos
- **Auto-registro** — Claude registra tareas via `POST /api/tasks` durante una sesión de chat
- **Sin cambios de código** — Añade, elimina o modifica tareas en tiempo de ejecución
- **Activar/desactivar** — Pausa tareas sin eliminarlas (`PATCH /api/tasks/{id}`)

### Automatización CI/CD
- **Disparadores webhook** — Activa tareas de Claude Code desde GitHub Actions o cualquier sistema CI/CD
- **Auto-actualización** — Actualiza automáticamente el bot cuando se publican paquetes upstream
- **Reinicio con drenaje** — Espera a que las sesiones activas terminen antes de reiniciar
- **Marcado automático de reanudación** — Las sesiones activas se marcan automáticamente para reanudar en cualquier apagado (reinicio por actualización via `AutoUpgradeCog`, o cualquier otro apagado via `ClaudeChatCog.cog_unload()`); se reanudan donde las dejaron tras el reinicio del bot
- **Aprobación de reinicio** — Compuerta opcional para confirmar actualizaciones antes de aplicarlas

### Gestión de Sesiones
- **Sincronización de sesiones** — Importa sesiones CLI como hilos de Discord (`/sync-sessions`)
- **Lista de sesiones** — `/sessions` con filtrado por origen (Discord / CLI / todas) y ventana de tiempo
- **Información de reanudación** — `/resume-info` muestra el comando CLI para continuar la sesión actual en un terminal
- **Reanudación al inicio** — Las sesiones interrumpidas se reinician automáticamente tras cualquier reinicio del bot; `AutoUpgradeCog` (reinicios por actualización) y `ClaudeChatCog.cog_unload()` (todos los demás apagados) las marcan automáticamente, o usa `POST /api/mark-resume` manualmente
- **Creación programática** — `POST /api/spawn` crea un nuevo hilo de Discord + sesión de Claude desde cualquier script o subproceso de Claude; devuelve un 201 no bloqueante inmediatamente tras la creación del hilo
- **Inyección de ID de hilo** — La variable de entorno `DISCORD_THREAD_ID` se pasa a cada subproceso de Claude, permitiendo que las sesiones creen sesiones hijas via `$CCDB_API_URL/api/spawn`
- **Gestión de worktrees** — `/worktree-list` muestra todos los worktrees de sesión activos con estado limpio/sucio; `/worktree-cleanup` elimina worktrees limpios huérfanos (admite vista previa con `dry_run`)

### Seguridad
- **Sin inyección de shell** — Solo `asyncio.create_subprocess_exec`, nunca `shell=True`
- **Validación de ID de sesión** — Regex estricto antes de pasar a `--resume`
- **Prevención de inyección de flags** — Separador `--` antes de todos los prompts
- **Aislamiento de secretos** — El token del bot se elimina del entorno del subproceso
- **Autorización de usuario** — `allowed_user_ids` restringe quién puede invocar a Claude

---

## Inicio Rápido

### Requisitos

- Python 3.10+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) instalado y autenticado
- Token de bot Discord con Message Content intent habilitado
- [uv](https://docs.astral.sh/uv/) (recomendado) o pip

### Ejecución autónoma

```bash
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge

cp .env.example .env
# Edita .env con tu token de bot y ID de canal

uv run python -m claude_discord.main
```

### Instalar como paquete

Si ya tienes un bot discord.py en ejecución (Discord solo permite una conexión Gateway por token):

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

`setup_bridge()` conecta todos los Cogs automáticamente. Los nuevos Cogs añadidos a ccdb se incluyen sin cambios en el código del consumidor.

Actualizar a la última versión:

```bash
uv lock --upgrade-package claude-code-discord-bridge && uv sync
```

---

## Configuración

| Variable | Descripción | Por defecto |
|----------|-------------|-------------|
| `DISCORD_BOT_TOKEN` | Tu token de bot Discord | (requerido) |
| `DISCORD_CHANNEL_ID` | ID del canal para el chat de Claude | (requerido) |
| `CLAUDE_COMMAND` | Ruta al Claude Code CLI | `claude` |
| `CLAUDE_MODEL` | Modelo a usar | `sonnet` |
| `CLAUDE_PERMISSION_MODE` | Modo de permisos del CLI | `acceptEdits` |
| `CLAUDE_WORKING_DIR` | Directorio de trabajo para Claude | directorio actual |
| `MAX_CONCURRENT_SESSIONS` | Máximo de sesiones paralelas | `3` |
| `SESSION_TIMEOUT_SECONDS` | Timeout de inactividad de sesión | `300` |
| `DISCORD_OWNER_ID` | ID de usuario para @mencionar cuando Claude necesita entrada | (opcional) |
| `COORDINATION_CHANNEL_ID` | ID del canal para transmisiones de eventos entre sesiones | (opcional) |
| `CCDB_COORDINATION_CHANNEL_NAME` | Crear automáticamente canal de coordinación por nombre | (opcional) |
| `WORKTREE_BASE_DIR` | Directorio base para escanear worktrees de sesión (activa limpieza automática) | (opcional) |

---

## Configuración del Bot de Discord

1. Crea una nueva aplicación en el [Portal de Desarrolladores de Discord](https://discord.com/developers/applications)
2. Crea un bot y copia el token
3. Activa **Message Content Intent** en Privileged Gateway Intents
4. Invita al bot con estos permisos:
   - Send Messages
   - Create Public Threads
   - Send Messages in Threads
   - Add Reactions
   - Manage Messages (para limpiar reacciones)
   - Read Message History

---

## GitHub + Automatización con Claude Code

### Ejemplo: Sincronización Automática de Documentación

En cada push a `main`, Claude Code:
1. Obtiene los últimos cambios y analiza el diff
2. Actualiza la documentación en inglés
3. Traduce al japonés (o cualquier idioma objetivo)
4. Crea un PR con resumen bilingüe
5. Activa auto-merge — se fusiona automáticamente cuando CI pasa

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

**Configuración del bot:**

```python
from claude_discord import WebhookTriggerCog, WebhookTrigger, ClaudeRunner

runner = ClaudeRunner(command="claude", model="sonnet")

triggers = {
    "🔄 docs-sync": WebhookTrigger(
        prompt="Analiza cambios, actualiza docs, crea un PR con resumen bilingüe, activa auto-merge.",
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

**Seguridad:** Los prompts se definen en el lado del servidor. Los webhooks solo seleccionan qué disparador activar — sin inyección arbitraria de prompts.

### Ejemplo: Auto-aprobación de PRs del propietario

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

## Tareas Programadas

Registra tareas periódicas de Claude Code en tiempo de ejecución — sin cambios de código, sin redeploys.

Desde una sesión de Discord, Claude puede registrar una tarea:

```bash
# Claude llama esto dentro de una sesión:
curl -X POST "$CCDB_API_URL/api/tasks" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Verificar dependencias desactualizadas y abrir un issue si se encuentran", "interval_seconds": 604800}'
```

O registra desde tus propios scripts:

```bash
curl -X POST http://localhost:8080/api/tasks \
  -H "Authorization: Bearer your-secret" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Análisis de seguridad semanal", "interval_seconds": 604800}'
```

El bucle maestro de 30 segundos detecta las tareas pendientes y crea sesiones de Claude Code automáticamente.

---

## Auto-actualización

Actualiza automáticamente el bot cuando se publica una nueva versión:

```python
from claude_discord import AutoUpgradeCog, UpgradeConfig

config = UpgradeConfig(
    package_name="claude-code-discord-bridge",
    trigger_prefix="🔄 bot-upgrade",
    working_dir="/home/user/my-bot",
    restart_command=["sudo", "systemctl", "restart", "my-bot.service"],
    restart_approval=True,  # Reacciona con ✅ para confirmar el reinicio
)

await bot.add_cog(AutoUpgradeCog(bot, config))
```

Antes de reiniciar, `AutoUpgradeCog`:

1. **Toma instantánea de sesiones activas** — Recopila todos los hilos con sesiones de Claude en ejecución (duck typing: cualquier Cog con dict `_active_runners` se descubre automáticamente).
2. **Drena** — Espera a que las sesiones activas terminen naturalmente.
3. **Marca para reanudar** — Guarda los IDs de hilos activos en la tabla de reanudaciones pendientes. En el próximo inicio, esas sesiones se reanudan automáticamente con un prompt "bot reiniciado, por favor continúa".
4. **Reinicia** — Ejecuta el comando de reinicio configurado.

Cualquier Cog con una propiedad `active_count` se descubre automáticamente y se drena:

```python
class MyCog(commands.Cog):
    @property
    def active_count(self) -> int:
        return len(self._running_tasks)
```

> **Cobertura:** `AutoUpgradeCog` cubre los reinicios por actualización. Para *todos los demás* apagados (`systemctl stop`, `bot.close()`, SIGTERM), `ClaudeChatCog.cog_unload()` proporciona una segunda red de seguridad automática.

---

## REST API

REST API opcional para notificaciones y gestión de tareas. Requiere aiohttp:

```bash
uv add "claude-code-discord-bridge[api]"
```

### Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/api/health` | Comprobación de estado |
| POST | `/api/notify` | Enviar notificación inmediata |
| POST | `/api/schedule` | Programar una notificación |
| GET | `/api/scheduled` | Listar notificaciones pendientes |
| DELETE | `/api/scheduled/{id}` | Cancelar una notificación |
| POST | `/api/tasks` | Registrar una tarea de Claude Code programada |
| GET | `/api/tasks` | Listar tareas registradas |
| DELETE | `/api/tasks/{id}` | Eliminar una tarea |
| PATCH | `/api/tasks/{id}` | Actualizar una tarea (activar/desactivar, cambiar horario) |
| POST | `/api/spawn` | Crear un nuevo hilo de Discord e iniciar una sesión de Claude Code (no bloqueante) |
| POST | `/api/mark-resume` | Marcar un hilo para reanudación automática en el próximo inicio del bot |

```bash
# Enviar notificación
curl -X POST http://localhost:8080/api/notify \
  -H "Authorization: Bearer your-secret" \
  -H "Content-Type: application/json" \
  -d '{"message": "¡Build exitoso!", "title": "CI/CD"}'

# Registrar tarea recurrente
curl -X POST http://localhost:8080/api/tasks \
  -H "Authorization: Bearer your-secret" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Resumen diario de standup", "interval_seconds": 86400}'
```

---

## Arquitectura

```
claude_discord/
  main.py                  # Punto de entrada autónomo
  setup.py                 # setup_bridge() — conexión de Cogs con una sola llamada
  bot.py                   # Clase Discord Bot
  concurrency.py           # Instrucciones de worktree + registro de sesiones activas
  cogs/
    claude_chat.py         # Chat interactivo (creación de hilos, manejo de mensajes)
    skill_command.py       # Comando slash /skill con autocompletado
    session_manage.py      # /sessions, /sync-sessions, /resume-info
    scheduler.py           # Ejecutor de tareas periódicas de Claude Code
    webhook_trigger.py     # Webhook → tarea de Claude Code (CI/CD)
    auto_upgrade.py        # Webhook → actualización de paquete + reinicio con drenaje
    event_processor.py     # EventProcessor — máquina de estados para eventos stream-json
    run_config.py          # RunConfig dataclass — agrupa todos los parámetros de ejecución CLI
    _run_helper.py         # Capa de orquestación delgada
  claude/
    runner.py              # Gestor de subprocesos Claude CLI
    parser.py              # Parser de eventos stream-json
    types.py               # Definiciones de tipos para mensajes SDK
  coordination/
    service.py             # Publica eventos de ciclo de vida de sesión en canal compartido
  database/
    models.py              # Esquema SQLite
    repository.py          # CRUD de sesiones
    task_repo.py           # CRUD de tareas programadas
    ask_repo.py            # CRUD de AskUserQuestion pendientes
    notification_repo.py   # CRUD de notificaciones programadas
    resume_repo.py         # CRUD de reanudación al inicio
    settings_repo.py       # Configuración por servidor
  discord_ui/
    status.py              # Gestor de reacciones emoji (con debounce)
    chunker.py             # División de mensajes con conocimiento de bloques y tablas
    embeds.py              # Constructores de embeds de Discord
    ask_view.py            # Botones/Menús de Selección para AskUserQuestion
    ask_handler.py         # collect_ask_answers() — UI + ciclo de vida DB de AskUserQuestion
    streaming_manager.py   # StreamingMessageManager — ediciones de mensaje en sitio con debounce
    tool_timer.py          # LiveToolTimer — contador de tiempo transcurrido para herramientas largas
    thread_dashboard.py    # Embed fijo en vivo mostrando estados de sesión
  session_sync.py          # Descubrimiento e importación de sesiones CLI
  worktree.py              # WorktreeManager — ciclo de vida seguro de git worktree
  ext/
    api_server.py          # REST API (opcional, requiere aiohttp)
  utils/
    logger.py              # Configuración de logging
```

### Filosofía de Diseño

- **Invocación CLI, no API** — Invoca `claude -p --output-format stream-json`, dando características completas de Claude Code (CLAUDE.md, skills, herramientas, memoria) sin reimplementarlas
- **Concurrencia primero** — Múltiples sesiones simultáneas son el caso esperado, no un caso límite; cada sesión recibe instrucciones de worktree, el registro y el canal de coordinación manejan el resto
- **Discord como pegamento** — Discord proporciona UI, hilos, reacciones, webhooks y notificaciones persistentes; sin frontend personalizado necesario
- **Framework, no aplicación** — Instala como paquete, añade Cogs a tu bot existente, configura via código
- **Extensibilidad sin código** — Añade tareas programadas y disparadores webhook sin tocar el código fuente
- **Seguridad por simplicidad** — ~3000 líneas de Python auditables; solo subprocess exec, sin expansión de shell

---

## Pruebas

```bash
uv run pytest tests/ -v --cov=claude_discord
```

470+ pruebas cubriendo parser, chunker, repositorio, runner, streaming, disparadores webhook, auto-actualización, REST API, UI de AskUserQuestion, panel de hilos, tareas programadas y sincronización de sesiones.

---

## Cómo Se Construyó Este Proyecto

**Todo este código base fue escrito por [Claude Code](https://docs.anthropic.com/en/docs/claude-code)**, el agente de codificación con IA de Anthropic. El autor humano ([@ebibibi](https://github.com/ebibibi)) proporcionó requisitos y dirección en lenguaje natural, pero no leyó ni editó manualmente el código fuente.

Esto significa:

- **Todo el código fue generado por IA** — arquitectura, implementación, pruebas, documentación
- **El autor humano no puede garantizar la corrección a nivel de código** — revisa el código fuente si necesitas certeza
- **Los reportes de bugs y PRs son bienvenidos** — Claude Code será usado para abordarlos
- **Este es un ejemplo real de software open source escrito por IA**

El proyecto comenzó el 2026-02-18 y continúa evolucionando a través de conversaciones iterativas con Claude Code.

---

## Ejemplo Real

**[EbiBot](https://github.com/ebibibi/discord-bot)** — Un bot personal de Discord construido sobre este framework. Incluye sincronización automática de documentación (inglés + japonés), notificaciones push, watchdog de Todoist, comprobaciones de salud programadas y CI/CD con GitHub Actions. Úsalo como referencia para construir tu propio bot.

---

## Inspirado en

- [OpenClaw](https://github.com/openclaw/openclaw) — Reacciones emoji de estado, debounce de mensajes, división con conocimiento de bloques
- [claude-code-discord-bot](https://github.com/timoconnellaus/claude-code-discord-bot) — Enfoque de invocación CLI + stream-json
- [claude-code-discord](https://github.com/zebbern/claude-code-discord) — Patrones de control de permisos
- [claude-sandbox-bot](https://github.com/RhysSullivan/claude-sandbox-bot) — Modelo de hilo por conversación

---

## Licencia

MIT
