> **Note:** This is an auto-translated version of the original English documentation.
> If there are any discrepancies, the [English version](../../README.md) takes precedence.
> **Nota:** Esta es una versión autotraducida de la documentación original en inglés.
> En caso de discrepancias, la [versión en inglés](../../README.md) prevalece.

# Claude & Codex Discord Bridge

*Nombre del paquete: `claude-code-discord-bridge` (kebab-case)*

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![CodeQL](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/codeql.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/codeql.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Usa Claude Code _o_ OpenAI Codex desde tu teléfono. Múltiples hilos. Todo a la vez. Desarrollo real incluido.**

Abre Claude Code o OpenAI Codex desde la aplicación Discord de tu smartphone, inicia múltiples hilos y ejecuta sesiones de desarrollo en paralelo — todo sin tocar un teclado. Cada hilo de Discord se convierte en una sesión de IA completamente aislada. Trabaja en una función en un hilo, revisa un PR en otro y ejecuta una tarea en segundo plano en un tercero — simultáneamente, incluso mezclando backends por hilo. El bridge gestiona toda la coordinación para que las sesiones nunca se interfieran entre sí.

**Usa tus suscripciones existentes. Sin configuración de API key.** ccdb funciona sobre las CLIs oficiales — Claude Code (incluida en tu [suscripción Claude Pro/Max](https://claude.ai/pricing)) y OpenAI Codex (incluida en [ChatGPT Plus/Pro/Business](https://chatgpt.com)). Cambia de backend con `/backend` o configura por hilo — tu equipo accede a ambas IAs a través de Discord a un costo predecible.

**[English](../../README.md)** | **[日本語](../ja/README.md)** | **[简体中文](../zh-CN/README.md)** | **[한국어](../ko/README.md)** | **[Português](../pt-BR/README.md)** | **[Français](../fr/README.md)**

> **Descargo de responsabilidad:** Este proyecto no está afiliado, respaldado ni tiene relación oficial con Anthropic u OpenAI. "Claude" y "Claude Code" son marcas comerciales de Anthropic, PBC; "OpenAI", "Codex" y "ChatGPT" son marcas comerciales de OpenAI. Esta es una herramienta de código abierto independiente que interactúa con Claude Code CLI y OpenAI Codex CLI.

> **Construido enteramente por Claude Code.** Todo este codebase — arquitectura, implementación, pruebas, documentación — fue escrito por Claude Code. El autor humano proporcionó requisitos y dirección. Ver [Cómo se construyó este proyecto](#cómo-se-construyó-este-proyecto).

---

## La Gran Idea: Sesiones Paralelas Sin Miedo

Cuando envías tareas a Claude Code en hilos de Discord separados, el bridge hace cuatro cosas automáticamente:

1. **Inyección de aviso de concurrencia** — El prompt del sistema de cada sesión incluye instrucciones obligatorias: crear un git worktree, trabajar solo dentro de él, nunca tocar el directorio de trabajo principal directamente.

2. **Registro de sesiones activas** — Cada sesión en ejecución sabe de las demás. Si dos sesiones van a tocar el mismo repositorio, pueden coordinarse en lugar de entrar en conflicto.

3. **AI Lounge** — Un "sala de descanso" inyectada en cada prompt. Antes de empezar, cada sesión lee los mensajes recientes del lounge para ver qué están haciendo las otras. Antes de operaciones destructivas (force push, reinicio del bot, eliminación de DB), las sesiones verifican el lounge primero.

```
Hilo A (función)   ──→  Claude Code (worktree-A)  ─┐
Hilo B (PR review) ──→  Claude Code (worktree-B)   ├─→  #ai-lounge
Hilo C (docs)      ──→  Claude Code (worktree-C)  ─┘    "A: refactor auth en progreso"
                                                         "B: revisión PR #42 lista"
                                                         "C: actualizando README"
```

Sin condiciones de carrera. Sin trabajo perdido. Sin sorpresas en los merges.

---

## Qué Puedes Hacer

### Chat Interactivo (Móvil / Escritorio)

Usa Claude Code desde cualquier lugar donde Discord funcione — teléfono, tablet o escritorio. Cada mensaje crea o continúa un hilo, mapeando 1:1 a una sesión persistente de Claude Code.

### Desarrollo Paralelo

Abre múltiples hilos simultáneamente. Cada uno es una sesión independiente de Claude Code con su propio contexto, directorio de trabajo y git worktree. Patrones útiles:

- **Función + revisión en paralelo**: Inicia una función en un hilo mientras Claude revisa un PR en otro.
- **Múltiples contribuidores**: Diferentes miembros del equipo tienen sus propios hilos; las sesiones se coordinan a través del AI Lounge.
- **Experimenta con seguridad**: Prueba un enfoque en el hilo A mientras mantienes el hilo B en código estable.

### Tareas Programadas (SchedulerCog)

Registra tareas periódicas de Claude Code desde una conversación de Discord o mediante REST API — sin cambios de código, sin redeployments. Las tareas se almacenan en SQLite y se ejecutan en un horario configurable.

```
/skill name:goodmorning         → ejecutar inmediatamente
Claude llama POST /api/tasks    → registrar tarea periódica
SchedulerCog (ciclo 30s)        → dispara tareas vencidas automáticamente
```

### Automatización CI/CD

Dispara tareas de Claude Code desde GitHub Actions a través de webhooks de Discord. Claude se ejecuta de forma autónoma — lee código, actualiza documentación, crea PRs, habilita auto-merge.

**Ejemplo real:** En cada push a `main`, Claude analiza el diff, actualiza la documentación en inglés + japonés, crea un PR bilingüe y habilita auto-merge. Cero interacción humana.

### Sincronización de Sesiones

¿Ya usas Claude Code CLI directamente? Sincroniza tus sesiones de terminal existentes en hilos de Discord con `/sync-sessions`. Rellena los mensajes de conversación recientes para que puedas continuar una sesión CLI desde tu teléfono sin perder el contexto.

### AI Lounge

Un canal compartido "sala de descanso" donde todas las sesiones concurrentes se anuncian, leen las actualizaciones de las demás y se coordinan antes de operaciones destructivas.

---

## Características

### Chat Interactivo

#### 🔗 Conceptos Básicos de Sesión
- **Modo solo chat** — `CHAT_ONLY_CHANNEL_IDS` muestra solo respuestas de texto de Claude; se ocultan embeds de herramientas, bloques de pensamiento, embeds de sesión y listas de tareas
- **Hilo = Sesión** — Mapeo 1:1 entre hilo de Discord y sesión de Claude Code
- **Seguimiento de objetivos** — `/goal <condición>` establece condición de finalización; Claude sigue trabajando hasta cumplirla
- **Persistencia de sesión** — Continúa conversaciones entre mensajes mediante `--resume`
- **Sesiones concurrentes** — Múltiples sesiones paralelas con límite configurable
- **Detener sin borrar** — `/stop` detiene una sesión preservándola para reanudar
- **Interrupción de sesión** — Enviar mensaje nuevo a hilo activo envía SIGINT y comienza con nueva instrucción
- **Auto-renombramiento de hilos** — Con `THREAD_AUTO_RENAME=true`, cada nuevo hilo se renombra automáticamente

#### 📡 Retroalimentación en Tiempo Real
- **Estado en tiempo real** — Reacciones emoji: 🧠 pensando, 🛠️ leyendo archivos, 💻 editando, 🌐 búsqueda web
- **Texto en streaming** — El texto intermedio aparece mientras Claude trabaja
- **Embeds de resultados de herramientas** — Resultados de llamadas de herramientas en vivo con tiempo transcurrido
- **Pensamiento extendido** — Razonamiento mostrado como embeds con etiqueta spoiler
- **Panel de hilos** — Embed fijado en vivo mostrando qué hilos están activos vs. esperando

#### 🤝 Human-in-the-Loop
- **Preguntas interactivas** — `AskUserQuestion` se renderiza como botones o menú de selección de Discord
- **Modo Plan** — `ExitPlanMode` muestra embed de Discord con botones Aprobar/Cancelar; 5 minutos de timeout
- **Solicitudes de permisos de herramientas** — Botones Permitir/Denegar; auto-rechazo después de 2 minutos
- **MCP Elicitation** — Los servidores MCP pueden solicitar entrada del usuario a través de Discord; 5 minutos de timeout
- **Progreso TodoWrite en vivo** — Embed único de Discord actualizado en su lugar

#### 📊 Observabilidad
- **Uso de tokens** — Tasa de aciertos en caché y conteo de tokens en embed de sesión completa
- **Uso de contexto** — Porcentaje de ventana de contexto; advertencia ⚠️ por encima del 83.5%
- **Detección de compresión** — Notificación en hilo cuando ocurre compresión de contexto
- **Notificación de bloqueo prolongado** — Mensaje en hilo tras inactividad (30s estándar, 120s para Opus)
- **Notificaciones de timeout** — Embed con tiempo transcurrido y guía de reanudación
- **Visualización de StatusLine** — Muestra la línea de estado de Claude después de cada sesión
- **Bandeja de entrada de hilos** — Con `THREAD_INBOX_ENABLED=true`, sección 📬 en el panel

#### 🔌 Entrada y Habilidades
- **Soporte de archivos adjuntos** — Archivos de texto añadidos automáticamente (hasta 5 archivos, 200 KB c/u); imágenes como URLs de CDN (hasta 4 × 5 MB)
- **Entrega de archivos bajo demanda** — Claude escribe ruta en `.ccdb-attachments`; el bot la envía como adjunto
- **Ejecución de habilidades** — Comando `/skill` con autocompletado; habilidades de plugins instalados también descubiertas
- **Recarga en caliente** — Nuevas habilidades en `~/.claude/skills/` detectadas automáticamente (60s de actualización)

### Concurrencia y Coordinación
- **Instrucciones de Worktree auto-inyectadas** — Cada sesión instada a usar `git worktree`
- **Limpieza automática de worktree** — Worktrees de sesión eliminados automáticamente; los sucios nunca se eliminan automáticamente
- **Registro de sesiones activas** — Registro en memoria; cada sesión ve lo que hacen las demás
- **AI Lounge** — Canal compartido; contexto inyectado mediante `--append-system-prompt` (no acumula en historial)
- **Canal de coordinación** — `COORDINATION_CHANNEL_ID` como fallback predeterminado para AI Lounge

### Tareas Programadas
- **SchedulerCog** — Ejecutor de tareas periódicas respaldado por SQLite, ciclo maestro de 30 segundos
- **Auto-registro** — Claude registra tareas a través de `POST /api/tasks`
- **Sin cambios de código** — Añade, elimina o modifica tareas en tiempo de ejecución
- **Activar/desactivar** — Pausa tareas sin eliminarlas (`PATCH /api/tasks/{id}`)

### Automatización CI/CD
- **Disparadores de Webhook** — Dispara tareas desde GitHub Actions o cualquier sistema CI/CD
- **Auto-actualización** — Actualiza el bot automáticamente cuando se publican paquetes upstream
- **Reinicio DrainAware** — Espera a que las sesiones activas terminen antes de reiniciar
- **Marcado automático de reanudación** — Las sesiones activas se marcan automáticamente en cualquier apagado
- **Disparador manual de actualización** — Comando `/upgrade` (opt-in mediante `slash_command_enabled=True`)

### Gestión de Sesiones
- **Ayuda integrada** — `/help` muestra todos los comandos slash disponibles (efímero)
- **Sincronización de sesiones** — Importa sesiones CLI como hilos de Discord (`/sync-sessions`)
- **Lista de sesiones** — `/sessions` con filtrado por origen y ventana de tiempo
- **Reanudar sesión** — `/resume` muestra menú de selección y reanuda en nuevo hilo
- **Borrar sesión** — `/clear` reinicia la sesión de Claude Code del hilo actual
- **Reanudación al inicio** — Las sesiones interrumpidas se reanudan automáticamente tras cualquier reinicio del bot
- **Generación programática** — `POST /api/spawn` crea nuevo hilo + sesión desde cualquier script
- **Gestión de Worktree** — `/worktree-list` y `/worktree-cleanup`
- **Cambio de modelo en tiempo de ejecución** — `/model-show` y `/model-set`, sin reiniciar
- **Rebobinado de conversación** — `/rewind` trunca la sesión al turno seleccionado
- **Bifurcación de conversación** — `/fork` crea copia independiente de sesión en nuevo hilo

### Seguridad
- **Sin inyección de shell** — Solo `asyncio.create_subprocess_exec`, nunca `shell=True`
- **Validación de ID de sesión** — Regex estricta antes de pasar a `--resume`
- **Prevención de inyección de flags** — Separador `--` antes de todos los prompts
- **Aislamiento de secretos** — Token del bot eliminado del entorno del subproceso
- **Autorización de usuarios** — `allowed_user_ids` restringe quién puede invocar a Claude
- **Prevención de inyección en logs** — Valores de API proporcionados por usuarios saneados antes de escribir en logs

---

## Inicio Rápido — Claude en Discord en 5 Minutos

**Prerrequisitos:** Python 3.10+, [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) instalado y autenticado.

**Soporte de plataformas:** Principalmente desarrollado y probado en **Linux**. macOS y Windows son soportados y pasan CI, pero reciben menos pruebas en el mundo real.

### Paso 1 — Crear un Bot de Discord (una vez, ~2 minutos)

1. Ve a [discord.com/developers/applications](https://discord.com/developers/applications) → **New Application**
2. Navega a **Bot** → habilita **Message Content Intent** en Privileged Gateway Intents
3. Copia el **Token** del bot
4. Ve a **OAuth2 → URL Generator**: Scopes `bot` + `applications.commands`, Permisos: Send Messages, Create Public Threads, Send Messages in Threads, Add Reactions, Manage Messages, Read Message History
5. Abre la URL generada → invita el bot a tu servidor

### Paso 2 — Ejecutar el Asistente de Configuración

Sin necesidad de clonar ni editar `.env` — el asistente lo hace todo:

```bash
# Con uvx (sin necesidad de instalación):
uvx --from "git+https://github.com/ebibibi/claude-code-discord-bridge.git" ccdb setup

# O después de clonar:
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge
uv run ccdb setup
```

### Iniciar / Detener

```bash
ccdb start    # iniciar el bot (lee .env en el directorio actual)
ccdb start --env /path/to/.env   # ubicación personalizada de .env
```

Envía un mensaje en el canal configurado — Claude responderá en un nuevo hilo.

### Ejecutar como Servicio systemd (Producción)

```bash
sudo cp discord-bot.service /etc/systemd/system/mybot.service
sudo nano /etc/systemd/system/mybot.service
sudo systemctl daemon-reload
sudo systemctl enable mybot.service
sudo systemctl start mybot.service
journalctl -u mybot.service -f
```

### Cogs Personalizados (Extiende Sin Hacer Fork)

Añade tus propias características dejando archivos Python en un directorio — sin fork, sin subclase, sin paquete:

```bash
ccdb start --cogs-dir ./my-cogs/
# O: CUSTOM_COGS_DIR=./my-cogs ccdb start
```

Cada archivo `.py` debe exponer `async def setup(bot, runner, components)`.

---

### Bot Mínimo (Instalar como Paquete)

```bash
uv add git+https://github.com/ebibibi/claude-code-discord-bridge.git
```

Crea `bot.py`:

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

`setup_bridge()` conecta todos los Cogs automáticamente. Actualizar a la última versión:

```bash
uv lock --upgrade-package claude-code-discord-bridge && uv sync
```

---

## Configuración

| Variable | Descripción | Por defecto |
|----------|-------------|-------------|
| `DISCORD_BOT_TOKEN` | Token del bot de Discord | (requerido) |
| `DISCORD_CHANNEL_ID` | ID de canal para chat de Claude | (requerido) |
| `CCDB_BACKEND` | Backend CLI a usar: `claude` o `codex` | `claude` |
| `CCDB_COMMAND` | Ruta o nombre del binario CLI (reemplaza `CLAUDE_COMMAND`) | _(auto)_ |
| `CCDB_MODEL` | Modelo a usar (reemplaza `CLAUDE_MODEL`) | `sonnet` |
| `CCDB_PERMISSION_MODE` | Modo de permisos CLI (reemplaza `CLAUDE_PERMISSION_MODE`) | `acceptEdits` |
| `CCDB_DANGEROUSLY_SKIP_PERMISSIONS` | Omitir todas las verificaciones de permisos | `false` |
| `CCDB_WORKING_DIR` | Directorio de trabajo CLI | directorio actual |
| `CCDB_ALLOWED_TOOLS` | Lista separada por comas de herramientas permitidas | (opcional) |
| `CCDB_CHANNEL_IDS` | IDs de canal adicionales para configuración multi-canal | (opcional) |
| `CLAUDE_COMMAND` | Ruta del CLI de Claude (nombre heredado — preferir `CCDB_COMMAND`) | `claude` |
| `CLAUDE_MODEL` | Modelo (nombre heredado — preferir `CCDB_MODEL`) | `sonnet` |
| `CLAUDE_PERMISSION_MODE` | Modo de permisos (nombre heredado — preferir `CCDB_PERMISSION_MODE`) | `acceptEdits` |
| `CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS` | Omitir permisos (nombre heredado) | `false` |
| `CLAUDE_WORKING_DIR` | Directorio de trabajo (nombre heredado) | directorio actual |
| `MAX_CONCURRENT_SESSIONS` | Máximo de sesiones CLI paralelas | `3` |
| `SESSION_TIMEOUT_SECONDS` | Timeout de inactividad de sesión | `300` |
| `DISCORD_OWNER_ID` | ID de usuario a @mencionar cuando Claude necesita input | (opcional) |
| `COORDINATION_CHANNEL_ID` | ID de canal como fallback predeterminado para AI Lounge | (opcional) |
| `MENTION_ONLY_CHANNEL_IDS` | IDs de canal donde el bot solo responde cuando se @menciona (separados por coma) | (opcional) |
| `INLINE_REPLY_CHANNEL_IDS` | IDs de canal para respuesta inline (separados por coma, sin crear hilo) | (opcional) |
| `CHAT_ONLY_CHANNEL_IDS` | IDs de canal en modo solo chat (separados por coma) | (opcional) |
| `WORKTREE_BASE_DIR` | Directorio base para escanear worktrees de sesión | (opcional) |
| `CLI_SESSIONS_PATH` | Ruta para descubrimiento de sesiones CLI (`~/.claude/projects`) | (opcional) |
| `CUSTOM_COGS_DIR` | Directorio con archivos Cog personalizados | (opcional) |
| `THREAD_INBOX_ENABLED` | Habilitar bandeja de entrada persistente de hilos | `false` |
| `THREAD_AUTO_RENAME` | Auto-renombrar hilos con título generado por Claude | `false` |
| `CCDB_CLI_ENV_FILE` | Ruta a archivo `KEY=VALUE` fusionado en entorno del subproceso CLI | (opcional) |
| `CCDB_LOG_FILE` | Ruta al archivo de log. Si se configura, se añade un manejador de archivo rotativo (10 MB por archivo, 5 copias) junto al handler stdout predeterminado. Útil para monitoreo y alertas | (opcional) |
| `API_HOST` | Dirección de enlace de REST API | `127.0.0.1` |
| `API_PORT` | Puerto de REST API (habilita REST API cuando se configura) | (opcional) |

---

## REST API

REST API opcional para notificaciones y gestión de tareas. Requiere aiohttp:

```bash
uv add "claude-code-discord-bridge[api]"
```

### Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/api/health` | Verificación de salud |
| POST | `/api/notify` | Enviar notificación inmediata |
| POST | `/api/schedule` | Programar notificación |
| GET | `/api/scheduled` | Listar notificaciones pendientes |
| DELETE | `/api/scheduled/{id}` | Cancelar notificación |
| POST | `/api/tasks` | Registrar tarea periódica de Claude Code |
| GET | `/api/tasks` | Listar tareas registradas |
| DELETE | `/api/tasks/{id}` | Eliminar tarea |
| PATCH | `/api/tasks/{id}` | Actualizar tarea |
| POST | `/api/spawn` | Crear nuevo hilo de Discord e iniciar sesión de Claude Code (no bloqueante) |
| POST | `/api/mark-resume` | Marcar hilo para reanudación automática en próximo inicio del bot |
| GET | `/api/lounge` | Leer mensajes recientes del AI Lounge |
| POST | `/api/lounge` | Publicar mensaje en AI Lounge |

---

## Arquitectura

```
claude_code_core/          # Biblioteca central compartida (independiente del backend)
  backend.py               # Protocolo SessionBackend + fábrica create_backend()
  codex_runner.py          # Backend OpenAI Codex CLI
  runner.py                # Gestor de subproceso Claude CLI
  parser.py                # Analizador de eventos stream-json
  types.py                 # Definiciones de tipos para mensajes SDK
claude_discord/
  main.py                  # Punto de entrada independiente
  cli.py                   # Punto de entrada CLI (comandos ccdb setup/start)
  setup.py                 # setup_bridge() — configuración de Cogs en una llamada
  cogs/
    claude_chat.py         # Chat interactivo
    skill_command.py       # Comando slash /skill
    session_manage.py      # Gestión de sesiones
    scheduler.py           # Ejecutor de tareas periódicas
    webhook_trigger.py     # Webhook → ejecución de tareas Claude Code
    auto_upgrade.py        # Auto-actualización + reinicio con drenaje
  ext/
    api_server.py          # REST API (opcional)
examples/
  ebibot/                  # Ejemplo del mundo real
```

### Filosofía de Diseño

- **Spawn de CLI, no API** — Invoca `claude -p --output-format stream-json`, obteniendo todas las características de Claude Code sin reimplementarlas. Sin API key, sin facturación por token.
- **Concurrencia primero** — Múltiples sesiones simultáneas son el caso esperado
- **Discord como pegamento** — Discord proporciona UI, hilos, reacciones, webhooks y notificaciones persistentes
- **Framework, no aplicación** — Instala como paquete, añade Cogs a tu bot existente
- **Extensibilidad sin código** — Añade tareas programadas y disparadores de webhook sin tocar el código fuente
- **Seguridad por simplicidad** — ~8000 líneas de Python auditable; solo subprocess exec, sin expansión de shell

---

## Pruebas

```bash
uv run pytest tests/ -v --cov=claude_discord
```

Más de 1365 pruebas cubriendo analizador, chunker, repositorio, runner, streaming, disparadores de webhook, auto-actualización, REST API, AskUserQuestion UI, panel de hilos, tareas programadas, sincronización de sesiones, AI Lounge, reanudación al inicio, cambio de modelo, detección de compresión, embeds de progreso TodoWrite, cargador de Cogs personalizados, protocolo SessionBackend, CodexRunner y fábrica de backends.

---

## Cómo se Construyó este Proyecto

**Este codebase es desarrollado por [Claude Code](https://docs.anthropic.com/en/docs/claude-code)**, el agente de codificación AI de Anthropic, bajo la dirección de [@ebibibi](https://github.com/ebibibi). El autor humano define requisitos, revisa pull requests y aprueba todos los cambios — Claude Code hace la implementación.

El proyecto comenzó el 2026-02-18 y continúa evolucionando a través de conversaciones iterativas con Claude Code.

---

## Ejemplo del Mundo Real

**[`examples/ebibot/`](examples/ebibot/)** — Un bot personal de Discord construido sobre este framework, incluido directamente en este repositorio. Demuestra el cargador de Cogs personalizado con:

- **ReminderCog** — Comando slash `/remind HH:MM "mensaje"` + bucle de envío de 30 segundos
- **WatchdogCog** — Monitor de tareas vencidas de Todoist
- **AutoUpgradeCog** — Auto-actualización mediante GitHub webhook + systemctl restart
- **DocsSyncCog** — Auto-traducción de documentación en cada push
- **AlertResponderCog** — Cog de monitoreo de alertas genérico

Ejecutar con: `ccdb start --cogs-dir examples/ebibot/cogs/`

---

## Inspirado Por

- [OpenClaw](https://github.com/openclaw/openclaw) — Reacciones emoji de estado, debouncing de mensajes, chunking consciente de fence
- [claude-code-discord-bot](https://github.com/timoconnellaus/claude-code-discord-bot) — Enfoque CLI spawn + stream-json
- [claude-code-discord](https://github.com/zebbern/claude-code-discord) — Patrones de control de permisos
- [claude-sandbox-bot](https://github.com/RhysSullivan/claude-sandbox-bot) — Modelo de conversación por hilo

---

## Licencia

MIT
