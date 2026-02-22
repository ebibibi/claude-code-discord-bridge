> **Note:** This is an auto-translated version of the original English documentation.
> If there are any discrepancies, the [English version](../../README.md) takes precedence.
> **Nota:** Esta es una versión autotraducida de la documentación original en inglés.
> En caso de discrepancias, la [versión en inglés](../../README.md) prevalece.

# claude-code-discord-bridge

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Ejecuta múltiples sesiones de Claude Code en paralelo — de forma segura — a través de Discord.**

Cada hilo de Discord se convierte en una sesión aislada de Claude Code. Abre tantas como necesites: trabaja en una funcionalidad en un hilo, revisa un PR en otro, ejecuta una tarea programada en un tercero. El bridge gestiona la coordinación automáticamente para que las sesiones simultáneas no interfieran entre sí.

**[English](../../README.md)** | **[日本語](../ja/README.md)** | **[简体中文](../zh-CN/README.md)** | **[한국어](../ko/README.md)** | **[Português](../pt-BR/README.md)** | **[Français](../fr/README.md)**

> **Descargo de responsabilidad:** Este proyecto no está afiliado, respaldado ni conectado oficialmente con Anthropic. "Claude" y "Claude Code" son marcas registradas de Anthropic, PBC. Esta es una herramienta de código abierto independiente que interactúa con Claude Code CLI.

> **Construido completamente por Claude Code.** Arquitectura, implementación, pruebas, documentación — toda esta base de código fue escrita por Claude Code. El autor humano proporcionó los requisitos y la dirección en lenguaje natural. Ver [Cómo se construyó este proyecto](#cómo-se-construyó-este-proyecto) para más detalles.

---

## La idea principal: sesiones paralelas sin miedo

Cuando envías tareas a Claude Code en hilos de Discord separados, el bridge hace cuatro cosas automáticamente:

1. **Inyección automática de instrucciones de concurrencia** — El prompt del sistema de cada sesión incluye instrucciones obligatorias: crear un git worktree, trabajar solo dentro de él, nunca tocar directamente el directorio de trabajo principal.

2. **Registro de sesiones activas** — Cada sesión en ejecución conoce a las demás. Si dos sesiones están a punto de tocar el mismo repositorio, pueden coordinarse en lugar de conflictuar.

3. **Canal de coordinación** — Un canal de Discord compartido donde las sesiones transmiten eventos de inicio/fin. Tanto Claude como los humanos pueden ver de un vistazo qué está pasando en todos los hilos activos.

4. **AI Lounge** — Una "sala de descanso" de sesión a sesión inyectada en cada prompt. Antes de comenzar, cada sesión lee los mensajes recientes del lounge para ver qué están haciendo otras sesiones. Antes de operaciones destructivas (force push, reinicio del bot, eliminación de DB), las sesiones verifican el lounge primero para no pisotear el trabajo de las demás.

```
Hilo A (funcionalidad) ──→  Claude Code (worktree-A)  ─┐
Hilo B (revisión PR)   ──→  Claude Code (worktree-B)   ├─→  #ai-lounge
Hilo C (docs)          ──→  Claude Code (worktree-C)  ─┘    "A: refactor auth en progreso"
           ↓ eventos de ciclo de vida                        "B: revisión PR #42 completada"
   #canal de coordinación                                    "C: actualizando README"
   "A: iniciado refactor auth"
   "B: revisando PR #42"
   "C: actualizando README"
```

Sin condiciones de carrera. Sin trabajo perdido. Sin sorpresas en el merge.

---

## Qué puedes hacer

### Chat interactivo (Móvil / Escritorio)

Usa Claude Code desde cualquier lugar donde funcione Discord — teléfono, tablet o escritorio. Cada mensaje crea o continúa un hilo, mapeado 1:1 a una sesión persistente de Claude Code.

### Desarrollo paralelo

Abre múltiples hilos simultáneamente. Cada uno es una sesión independiente de Claude Code con su propio contexto, directorio de trabajo y git worktree. Patrones útiles:

- **Funcionalidad + revisión en paralelo**: Inicia una funcionalidad en un hilo mientras Claude revisa un PR en otro.
- **Múltiples contribuidores**: Diferentes miembros del equipo tienen cada uno su propio hilo; las sesiones se mantienen al tanto de las demás a través del canal de coordinación.
- **Experimentar de forma segura**: Prueba un enfoque en el hilo A mientras mantienes el hilo B en código estable.

### Tareas programadas (SchedulerCog)

Registra tareas periódicas de Claude Code desde una conversación de Discord o via REST API — sin cambios de código, sin redeploys. Las tareas se almacenan en SQLite y se ejecutan según un horario configurable.

```
/skill name:goodmorning          → se ejecuta inmediatamente
Claude llama a POST /api/tasks   → registra una tarea periódica
SchedulerCog (bucle maestro 30s) → dispara tareas pendientes automáticamente
```

### Automatización CI/CD

Dispara tareas de Claude Code desde GitHub Actions a través de webhooks de Discord. Claude se ejecuta de forma autónoma — lee código, actualiza documentación, crea PRs, habilita auto-merge.

```
GitHub Actions → Discord Webhook → Bridge → Claude Code CLI
                                                  ↓
GitHub PR ←── git push ←── Claude Code ──────────┘
```

**Ejemplo real:** En cada push a `main`, Claude analiza el diff, actualiza documentación en inglés + japonés, crea un PR con resumen bilingüe, y habilita auto-merge. Cero interacción humana.

### Sincronización de sesiones

¿Ya usas Claude Code CLI directamente? Sincroniza tus sesiones de terminal existentes en hilos de Discord con `/sync-sessions`. Rellena los mensajes de conversación recientes para que puedas continuar una sesión CLI desde tu teléfono sin perder contexto.

### AI Lounge

Un canal "sala de descanso" compartido donde todas las sesiones simultáneas se anuncian, leen las actualizaciones de las demás y se coordinan antes de operaciones destructivas.

Cada sesión de Claude recibe automáticamente el contexto del lounge en su prompt del sistema: mensajes recientes de otras sesiones, más la regla de verificación antes de cualquier operación destructiva.

```bash
# Las sesiones publican sus intenciones antes de comenzar:
curl -X POST "$CCDB_API_URL/api/lounge" \
  -H "Content-Type: application/json" \
  -d '{"message": "Iniciando refactor auth en feature/oauth — worktree-A", "label": "dev funcionalidad"}'

# Leer mensajes recientes del lounge (también inyectados automáticamente en cada sesión):
curl "$CCDB_API_URL/api/lounge"
```

El canal del lounge también funciona como feed de actividad visible para humanos — ábrelo en Discord para ver de un vistazo qué está haciendo cada sesión activa de Claude.

### Creación programática de sesiones

Crea nuevas sesiones de Claude Code desde scripts, GitHub Actions u otras sesiones de Claude — sin interacción de mensajes de Discord.

```bash
# Desde otra sesión de Claude o un script CI:
curl -X POST "$CCDB_API_URL/api/spawn" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Ejecutar escaneo de seguridad en el repositorio", "thread_name": "Escaneo de seguridad"}'
# Retorna inmediatamente con el ID del hilo; Claude se ejecuta en segundo plano
```

### Reanudación al inicio

Si el bot se reinicia a mitad de sesión, las sesiones interrumpidas de Claude se reanudan automáticamente cuando el bot vuelve a estar en línea. Las sesiones se marcan para reanudar de tres formas:

- **Automática (reinicio de actualización)** — `AutoUpgradeCog` captura todas las sesiones activas justo antes de un reinicio de actualización de paquete y las marca automáticamente.
- **Automática (cualquier parada)** — `ClaudeChatCog.cog_unload()` marca todas las sesiones en ejecución cada vez que el bot se detiene a través de cualquier mecanismo (`systemctl stop`, `bot.close()`, SIGTERM, etc.).
- **Manual** — Cualquier sesión puede llamar directamente a `POST /api/mark-resume`.

---

## Características

### Chat interactivo
- **Thread = Session** — Correspondencia 1:1 entre hilo de Discord y sesión de Claude Code
- **Estado en tiempo real** — Reacciones emoji: 🧠 pensando, 🛠️ leyendo archivos, 💻 editando, 🌐 búsqueda web
- **Texto en streaming** — El texto intermedio del asistente aparece mientras Claude trabaja
- **Embeds de resultados de herramientas** — Resultados de llamadas de herramientas en vivo con tiempo transcurrido subiendo cada 10s
- **Pensamiento extendido** — Razonamiento mostrado como embeds con etiquetas spoiler (clic para revelar)
- **Persistencia de sesión** — Reanudar conversaciones entre mensajes via `--resume`
- **Ejecución de skills** — Comando `/skill` con autocompletado, argumentos opcionales, reanudación en el hilo
- **Recarga en caliente** — Nuevos skills añadidos a `~/.claude/skills/` detectados automáticamente (refresco 60s, sin reinicio)
- **Sesiones simultáneas** — Múltiples sesiones paralelas con límite configurable
- **Detener sin borrar** — `/stop` detiene una sesión preservándola para reanudar
- **Soporte de adjuntos** — Archivos de texto adjuntados automáticamente al prompt (hasta 5 × 50 KB)
- **Notificaciones de timeout** — Embed con tiempo transcurrido y guía de reanudación en timeout
- **Preguntas interactivas** — `AskUserQuestion` renderizado como Botones de Discord o Menú de selección; la sesión reanuda con tu respuesta; los botones sobreviven a reinicios del bot
- **Panel de hilos** — Embed anclado en vivo mostrando qué hilos están activos vs esperando; @mención al propietario cuando se necesita entrada
- **Uso de tokens** — Tasa de aciertos de caché y conteos de tokens mostrados en el embed de sesión completada

### Concurrencia y coordinación
- **Instrucciones de worktree auto-inyectadas** — Cada sesión instruida a usar `git worktree` antes de tocar cualquier archivo
- **Limpieza automática de worktrees** — Los worktrees de sesión (`wt-{thread_id}`) se eliminan automáticamente al finalizar la sesión y al iniciar el bot; los worktrees sucios nunca se eliminan automáticamente (invariante de seguridad)
- **Registro de sesiones activas** — Registro en memoria; cada sesión ve lo que hacen las demás
- **AI Lounge** — Canal "sala de descanso" compartido inyectado en cada prompt de sesión; las sesiones publican intenciones, leen el estado de las demás y verifican antes de operaciones destructivas; los humanos lo ven como un feed de actividad en vivo
- **Canal de coordinación** — Canal compartido opcional para transmisiones de ciclo de vida inter-sesiones
- **Scripts de coordinación** — Claude puede llamar a `coord_post.py` / `coord_read.py` desde una sesión para publicar y leer eventos

### Tareas programadas
- **SchedulerCog** — Ejecutor de tareas periódicas basado en SQLite con un bucle maestro de 30 segundos
- **Auto-registro** — Claude registra tareas via `POST /api/tasks` durante una sesión de chat
- **Sin cambios de código** — Añade, elimina o modifica tareas en tiempo de ejecución
- **Activar/desactivar** — Pausa tareas sin eliminarlas (`PATCH /api/tasks/{id}`)

### Automatización CI/CD
- **Disparadores webhook** — Dispara tareas de Claude Code desde GitHub Actions o cualquier sistema CI/CD
- **Auto-actualización** — Actualiza automáticamente el bot cuando se publican paquetes upstream
- **Reinicio DrainAware** — Espera a que las sesiones activas terminen antes de reiniciar
- **Marcado auto-reanudación** — Las sesiones activas se marcan automáticamente para reanudación en cualquier parada; reanudan donde lo dejaron después de que el bot vuelve en línea
- **Aprobación de reinicio** — Puerta opcional para confirmar actualizaciones antes de aplicar

### Gestión de sesiones
- **Sincronización de sesiones** — Importa sesiones CLI como hilos de Discord (`/sync-sessions`)
- **Lista de sesiones** — `/sessions` con filtrado por origen (Discord / CLI / todos) y ventana de tiempo
- **Info de reanudación** — `/resume-info` muestra el comando CLI para continuar la sesión actual en un terminal
- **Reanudación al inicio** — Las sesiones interrumpidas se reinician automáticamente después de cualquier reinicio del bot
- **Creación programática** — `POST /api/spawn` crea un nuevo hilo de Discord + sesión de Claude desde cualquier script o subproceso de Claude
- **Inyección de ID de hilo** — La variable de env `DISCORD_THREAD_ID` se pasa a cada subproceso de Claude, permitiendo que las sesiones generen sesiones hijas via `$CCDB_API_URL/api/spawn`
- **Gestión de worktrees** — `/worktree-list` muestra todos los worktrees de sesión activos con estado clean/dirty; `/worktree-cleanup` elimina worktrees clean huérfanos

### Seguridad
- **Sin inyección de shell** — Solo `asyncio.create_subprocess_exec`, nunca `shell=True`
- **Validación de ID de sesión** — Regex estricta antes de pasar a `--resume`
- **Prevención de inyección de flags** — Separador `--` antes de todos los prompts
- **Aislamiento de secretos** — Token del bot eliminado del entorno del subproceso
- **Autorización de usuario** — `allowed_user_ids` restringe quién puede invocar a Claude

---

## Inicio rápido — Claude en Discord en 5 minutos

### Paso 1 — Prerrequisitos

- **Python 3.10+** y **[uv](https://docs.astral.sh/uv/)** instalados
- **[Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code)** instalado y autenticado (`claude --version` debe funcionar)
- Un **servidor de Discord** donde tienes acceso de administrador

### Paso 2 — Crear un bot de Discord

1. Ve a [discord.com/developers/applications](https://discord.com/developers/applications) y haz clic en **New Application**
2. Navega a **Bot** → haz clic en **Add Bot**
3. En **Privileged Gateway Intents**, habilita **Message Content Intent**
4. Copia el **Token** del bot (lo necesitarás pronto)
5. Ve a **OAuth2 → URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions: `Send Messages`, `Create Public Threads`, `Send Messages in Threads`, `Add Reactions`, `Manage Messages`, `Read Message History`
6. Abre la URL generada en tu navegador e invita al bot a tu servidor

### Paso 3 — Obtener tus IDs de Discord

Habilita el **Modo desarrollador** en Discord (Configuración → Avanzado → Modo desarrollador), luego:

- **ID de canal**: Clic derecho en el canal donde Claude debe escuchar → **Copiar ID del canal**
- **Tu ID de usuario**: Clic derecho en tu nombre de usuario → **Copiar ID de usuario**

### Paso 4 — Ejecutarlo

```bash
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge
cp .env.example .env
```

Edita `.env`:

```env
DISCORD_BOT_TOKEN=your-bot-token-here
DISCORD_CHANNEL_ID=123456789012345678    # el canal copiado arriba
DISCORD_OWNER_ID=987654321098765432      # tu ID de usuario (para @-menciones)
CLAUDE_WORKING_DIR=/path/to/your/project
```

Luego inicia el bot:

```bash
uv run python -m claude_discord.main
```

Envía un mensaje en el canal configurado — Claude responderá en un nuevo hilo.

---

### Bot mínimo (instalar como paquete)

Si ya tienes un bot discord.py, añade ccdb como paquete en su lugar:

```bash
uv add git+https://github.com/ebibibi/claude-code-discord-bridge.git
```

Crea un `bot.py`:

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
    print(f"Conectado como {bot.user}")
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

| Variable | Descripción | Predeterminado |
|----------|-------------|----------------|
| `DISCORD_BOT_TOKEN` | Tu token de bot de Discord | (requerido) |
| `DISCORD_CHANNEL_ID` | ID de canal para el chat de Claude | (requerido) |
| `CLAUDE_COMMAND` | Ruta a Claude Code CLI | `claude` |
| `CLAUDE_MODEL` | Modelo a usar | `sonnet` |
| `CLAUDE_PERMISSION_MODE` | Modo de permisos para CLI | `acceptEdits` |
| `CLAUDE_WORKING_DIR` | Directorio de trabajo para Claude | directorio actual |
| `MAX_CONCURRENT_SESSIONS` | Máx sesiones paralelas | `3` |
| `SESSION_TIMEOUT_SECONDS` | Timeout de inactividad de sesión | `300` |
| `DISCORD_OWNER_ID` | ID de usuario para @-mencionar cuando Claude necesita entrada | (opcional) |
| `COORDINATION_CHANNEL_ID` | ID de canal para transmisiones de eventos inter-sesiones | (opcional) |
| `CCDB_COORDINATION_CHANNEL_NAME` | Crear canal de coordinación automáticamente por nombre | (opcional) |
| `WORKTREE_BASE_DIR` | Directorio base para escanear worktrees de sesión (activa limpieza automática) | (opcional) |

---

## REST API

API REST opcional para notificaciones y gestión de tareas. Requiere aiohttp:

```bash
uv add "claude-code-discord-bridge[api]"
```

### Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/api/health` | Verificación de salud |
| POST | `/api/notify` | Enviar notificación inmediata |
| POST | `/api/schedule` | Programar una notificación |
| GET | `/api/scheduled` | Listar notificaciones pendientes |
| DELETE | `/api/scheduled/{id}` | Cancelar una notificación |
| POST | `/api/tasks` | Registrar una tarea de Claude Code programada |
| GET | `/api/tasks` | Listar tareas registradas |
| DELETE | `/api/tasks/{id}` | Eliminar una tarea |
| PATCH | `/api/tasks/{id}` | Actualizar una tarea (activar/desactivar, cambiar horario) |
| POST | `/api/spawn` | Crear nuevo hilo de Discord e iniciar sesión de Claude Code (no bloqueante) |
| POST | `/api/mark-resume` | Marcar un hilo para reanudación automática al siguiente inicio del bot |
| GET | `/api/lounge` | Leer mensajes recientes del AI Lounge |
| POST | `/api/lounge` | Publicar un mensaje en el AI Lounge (con `label` opcional) |

---

## Pruebas

```bash
uv run pytest tests/ -v --cov=claude_discord
```

610+ pruebas cubriendo parser, chunker, repositorio, runner, streaming, disparadores webhook, auto-actualización, API REST, UI AskUserQuestion, panel de hilos, tareas programadas, sincronización de sesiones, AI Lounge y reanudación al inicio.

---

## Cómo se construyó este proyecto

**Esta base de código es desarrollada por [Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — el agente de codificación IA de Anthropic — bajo la dirección de [@ebibibi](https://github.com/ebibibi). El autor humano define los requisitos, revisa los pull requests y aprueba todos los cambios — Claude Code hace la implementación.

Esto significa:

- **La implementación es generada por IA** — arquitectura, código, pruebas, documentación
- **La revisión humana se aplica a nivel de PR** — cada cambio pasa por pull requests de GitHub y CI antes de hacer merge
- **Los reportes de bugs y PRs son bienvenidos** — Claude Code será utilizado para abordarlos
- **Este es un ejemplo del mundo real de software open source dirigido por humanos e implementado por IA**

El proyecto comenzó el 2026-02-18 y continúa evolucionando a través de conversaciones iterativas con Claude Code.

---

## Ejemplo del mundo real

**[EbiBot](https://github.com/ebibibi/discord-bot)** — Un bot personal de Discord construido sobre este framework. Incluye sincronización automática de documentación (inglés + japonés), notificaciones push, vigilancia de Todoist, verificaciones de salud programadas y CI/CD con GitHub Actions. Úsalo como referencia para construir tu propio bot.

---

## Licencia

MIT
