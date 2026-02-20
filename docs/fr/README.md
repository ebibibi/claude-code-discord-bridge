> **Note:** This is an auto-translated version of the original English documentation.
> If there are any discrepancies, the [English version](../../README.md) takes precedence.
> **Remarque :** Ceci est une version traduite automatiquement de la documentation originale en anglais.
> En cas de divergence, la [version anglaise](../../README.md) fait foi.

# claude-code-discord-bridge

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Connectez [Claude Code](https://docs.anthropic.com/en/docs/claude-code) à Discord et GitHub. Un framework qui relie Claude Code CLI à Discord pour le **chat interactif, l'automatisation CI/CD et l'intégration des workflows GitHub**.

Claude Code est excellent dans le terminal — mais il peut faire bien plus. Ce pont vous permet d'**utiliser Claude Code dans votre workflow de développement GitHub** : synchroniser automatiquement la documentation, réviser et fusionner des PR, et exécuter n'importe quelle tâche Claude Code déclenchée par GitHub Actions. Tout via Discord comme colle universelle.

**[English](../../README.md)** | **[日本語](../ja/README.md)** | **[简体中文](../zh-CN/README.md)** | **[한국어](../ko/README.md)** | **[Español](../es/README.md)** | **[Português](../pt-BR/README.md)**

> **Avertissement :** Ce projet n'est pas affilié à Anthropic, ni approuvé ou officiellement connecté à Anthropic. "Claude" et "Claude Code" sont des marques déposées d'Anthropic, PBC. Il s'agit d'un outil open source indépendant qui s'interface avec le Claude Code CLI.

> **Entièrement construit par Claude Code.** Ce projet a été conçu, implémenté, testé et documenté par Claude Code lui-même — l'agent de codification IA d'Anthropic. L'auteur humain n'a pas lu le code source. Voir [Comment ce projet a été construit](#comment-ce-projet-a-été-construit) pour plus de détails.

## Deux façons de l'utiliser

### 1. Chat interactif (Mobile / Bureau)

Utilisez Claude Code depuis votre téléphone ou n'importe quel appareil avec Discord. Chaque conversation devient un fil avec une persistance de session complète.

```
Vous (Discord)  →  Bridge  →  Claude Code CLI
     ↑                              ↓
     ←──── sortie stream-json ──────←
```

### 2. Automatisation CI/CD (GitHub → Discord → Claude Code → GitHub)

Déclenchez des tâches Claude Code depuis GitHub Actions via des webhooks Discord. Claude Code s'exécute de manière autonome — lisant le code, mettant à jour les docs, créant des PR et activant la fusion automatique.

```
GitHub Actions  →  Discord Webhook  →  Bridge  →  Claude Code CLI
                                                         ↓
GitHub PR (auto-merge)  ←  git push  ←  Claude Code  ←──┘
```

**Exemple concret :** À chaque push sur main, Claude Code analyse automatiquement les changements, met à jour la documentation en anglais et en japonais, crée une PR avec un résumé bilingue et active la fusion automatique. Aucune intervention humaine requise.

## Fonctionnalités

### Chat interactif
- **Thread = Session** — Chaque tâche obtient son propre fil Discord, mappé 1:1 à une session Claude Code
- **Statut en temps réel** — Les réactions emoji montrent ce que fait Claude (🧠 réflexion, 🛠️ lecture de fichiers, 💻 édition, 🌐 recherche web)
- **Texte en streaming** — Le texte intermédiaire apparaît au fur et à mesure que Claude travaille, pas seulement à la fin
- **Affichage des résultats d'outils** — Les résultats d'utilisation d'outils affichés sous forme d'embeds en temps réel
- **Chronométrage des outils en direct** — Les embeds d'outils en cours mettent à jour le temps écoulé toutes les 10s pour les commandes longues (authentification, builds), pour que vous sachiez toujours que Claude travaille encore
- **Réflexion étendue** — Le raisonnement de Claude apparaît sous forme d'embeds avec balise spoiler (cliquez pour révéler)
- **Persistance de session** — Continuez les conversations entre les messages via `--resume`
- **Exécution de skills** — Exécutez des skills Claude Code avec `/skill` avec l'autocomplétion, les arguments optionnels et la reprise dans le fil
- **Sessions simultanées** — Exécutez plusieurs sessions en parallèle (limite configurable)
- **Arrêt sans effacement** — `/stop` arrête une session en cours tout en la préservant pour la reprise
- **Support des pièces jointes** — Les pièces jointes textuelles sont automatiquement ajoutées au prompt (jusqu'à 5 fichiers, 50 Ko chacun)
- **Notifications de délai d'attente** — Embed dédié avec les secondes écoulées et des conseils actionnables lors de l'expiration d'une session
- **Questions interactives** — Quand Claude appelle `AskUserQuestion`, le bot affiche des Boutons Discord ou un Select Menu et reprend la session avec votre réponse
- **Tableau de bord de statut de session** — Un embed épinglé en direct dans le canal principal montre quels fils sont en cours de traitement vs. en attente d'entrée ; le propriétaire est @mentionné quand Claude a besoin d'une réponse
- **Coordination multi-session** — Avec `COORDINATION_CHANNEL_ID` configuré, chaque session diffuse les événements de début/fin vers un canal partagé pour que les sessions simultanées restent informées les unes des autres

### Tâches planifiées (SchedulerCog)
- **Tâches périodiques Claude Code** — Enregistrez des tâches via le chat Discord ou l'API REST ; elles s'exécutent selon un intervalle configurable
- **Basé sur SQLite** — Les tâches persistent entre les redémarrages ; gérées via les endpoints `/api/tasks`
- **Planification sans code** — Claude Code peut auto-enregistrer de nouvelles tâches avec l'outil Bash pendant une session ; sans redémarrages du bot ni modifications de code
- **Boucle maîtresse unique** — Une boucle `discord.ext.tasks` de 30 secondes dispatche toutes les tâches, maintenant la surcharge basse

### Automatisation CI/CD
- **Déclencheurs webhooks** — Déclenchez des tâches Claude Code depuis GitHub Actions ou n'importe quel système CI/CD
- **Mise à jour automatique** — Mettez automatiquement à jour le bot quand les paquets upstream sont publiés
- **API REST** — Envoyez des notifications et gérez les tâches planifiées depuis des outils externes (optionnel, nécessite aiohttp)

### Sécurité
- **Pas d'injection shell** — Seulement `asyncio.create_subprocess_exec`, jamais `shell=True`
- **Validation de l'ID de session** — Regex stricte avant de passer à `--resume`
- **Prévention d'injection de flags** — Séparateur `--` avant tous les prompts
- **Isolation des secrets** — Token du bot et secrets supprimés de l'environnement du sous-processus
- **Autorisation des utilisateurs** — `allowed_user_ids` restreint qui peut invoquer Claude

## Skills

Exécutez des [skills Claude Code](https://docs.anthropic.com/en/docs/claude-code) directement depuis Discord via la commande slash `/skill`.

```
/skill name:goodmorning                      → exécute /goodmorning
/skill name:todoist args:filter "today"      → exécute /todoist filter "today"
/skills                                      → liste toutes les skills disponibles
```

**Fonctionnalités :**
- **Autocomplétion** — Tapez pour filtrer ; noms et descriptions sont consultables
- **Arguments** — Passez des arguments supplémentaires via le paramètre `args`
- **Reprise dans le fil** — Utilisez `/skill` dans un fil Claude existant pour exécuter la skill dans la session actuelle au lieu de créer un nouveau fil
- **Rechargement à chaud** — Les nouvelles skills ajoutées à `~/.claude/skills/` sont détectées automatiquement (intervalle de rafraîchissement de 60s, pas de redémarrage nécessaire)

## Démarrage rapide

### Prérequis

- Python 3.10+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installé et authentifié
- Un token de bot Discord avec l'intent Message Content activé
- [uv](https://docs.astral.sh/uv/) (recommandé) ou pip

### Exécuter en mode autonome

```bash
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge

cp .env.example .env
# Éditez .env avec votre token de bot et l'ID du canal

uv run python -m claude_discord.main
```

### Installer comme un paquet

Si vous avez déjà un bot discord.py en cours d'exécution (Discord n'autorise qu'une seule connexion Gateway par token) :

```bash
uv add git+https://github.com/ebibibi/claude-code-discord-bridge.git
```

```python
from claude_discord import ClaudeRunner, setup_bridge

runner = ClaudeRunner(command="claude", model="sonnet")

# Un seul appel enregistre tous les Cogs — les nouvelles fonctionnalités sont incluses automatiquement
await setup_bridge(
    bot,
    runner,
    session_db_path="data/sessions.db",
    claude_channel_id=YOUR_CHANNEL_ID,
    allowed_user_ids={YOUR_USER_ID},
)
```

`setup_bridge()` connecte automatiquement `ClaudeChatCog`, `SkillCommandCog`, `SessionManageCog` et `SchedulerCog`. Quand de nouveaux Cogs sont ajoutés à ccdb, ils apparaissent automatiquement — sans modifications de code côté consommateur.

<details>
<summary>Connexion manuelle (avancé)</summary>

```python
from claude_discord import ClaudeChatCog, ClaudeRunner, SessionRepository
from claude_discord.database.models import init_db

await init_db("data/sessions.db")
repo = SessionRepository("data/sessions.db")
runner = ClaudeRunner(command="claude", model="sonnet")

await bot.add_cog(ClaudeChatCog(bot, repo, runner))
```
</details>

Mettre à jour vers la dernière version :

```bash
uv lock --upgrade-package claude-code-discord-bridge && uv sync
```

## Configuration

| Variable | Description | Défaut |
|----------|-------------|--------|
| `DISCORD_BOT_TOKEN` | Votre token de bot Discord | (requis) |
| `DISCORD_CHANNEL_ID` | ID du canal pour le chat Claude | (requis) |
| `CLAUDE_COMMAND` | Chemin vers le Claude Code CLI | `claude` |
| `CLAUDE_MODEL` | Modèle à utiliser | `sonnet` |
| `CLAUDE_PERMISSION_MODE` | Mode de permission pour CLI | `acceptEdits` |
| `CLAUDE_WORKING_DIR` | Répertoire de travail pour Claude | répertoire courant |
| `MAX_CONCURRENT_SESSIONS` | Sessions parallèles maximum | `3` |
| `SESSION_TIMEOUT_SECONDS` | Délai d'inactivité de session | `300` |
| `DISCORD_OWNER_ID` | ID d'utilisateur Discord pour @mention quand Claude a besoin d'une entrée | (optionnel) |
| `COORDINATION_CHANNEL_ID` | ID de canal pour les diffusions de coordination multi-session | (optionnel) |

## Configuration du bot Discord

1. Créez une nouvelle application sur le [Portail développeur Discord](https://discord.com/developers/applications)
2. Créez un bot et copiez le token
3. Activez **Message Content Intent** sous Privileged Gateway Intents
4. Invitez le bot sur votre serveur avec ces permissions :
   - Send Messages
   - Create Public Threads
   - Send Messages in Threads
   - Add Reactions
   - Manage Messages (pour le nettoyage des réactions)
   - Read Message History

## Automatisation GitHub + Claude Code

Le système de déclencheurs webhooks vous permet de construire des workflows CI/CD entièrement autonomes où Claude Code agit comme un agent intelligent — pas seulement en exécutant des scripts, mais en comprenant les changements de code et en prenant des décisions.

### Exemple : Synchronisation automatique de documentation

À chaque push sur main, Claude Code :
1. Récupère les derniers changements et analyse le diff
2. Met à jour la documentation en anglais si le code source a changé
3. Traduit en japonais (ou n'importe quelle langue cible)
4. Crée une PR avec un résumé bilingue
5. Active la fusion automatique — la PR fusionne automatiquement quand CI passe

**Workflow GitHub Actions :**

```yaml
# .github/workflows/docs-sync.yml
name: Documentation Sync
on:
  push:
    branches: [main]
jobs:
  trigger:
    # Ignore les commits de docs-sync lui-même (prévention de boucle infinie)
    if: "!contains(github.event.head_commit.message, '[docs-sync]')"
    runs-on: ubuntu-latest
    steps:
      - run: |
          curl -X POST "${{ secrets.DISCORD_WEBHOOK_URL }}" \
            -H "Content-Type: application/json" \
            -d '{"content": "🔄 docs-sync"}'
```

**Configuration du bot :**

```python
from claude_discord import WebhookTriggerCog, WebhookTrigger, ClaudeRunner

runner = ClaudeRunner(command="claude", model="sonnet")

triggers = {
    "🔄 docs-sync": WebhookTrigger(
        prompt="Analysez les changements, mettez à jour les docs, créez une PR avec résumé bilingue, activez l'auto-merge.",
        working_dir="/home/user/my-project",
        timeout=600,
    ),
    "🚀 deploy": WebhookTrigger(
        prompt="Déployez en environnement de staging.",
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

**Sécurité :** Seuls les messages webhook sont traités. `allowed_webhook_ids` optionnel pour un contrôle plus strict. Les prompts sont définis côté serveur — les webhooks sélectionnent uniquement quel déclencheur activer.

### Exemple : Auto-approbation des PR du propriétaire

Approuvez et fusionnez automatiquement vos propres PR après que CI passe :

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

## Tâches planifiées

`SchedulerCog` exécute des tâches Claude Code périodiques stockées dans SQLite. Les tâches sont enregistrées au moment de l'exécution via l'API REST — sans modifications de code ni redémarrages du bot.

### Enregistrer une tâche (via l'API REST)

```bash
curl -X POST http://localhost:8080/api/tasks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secret-token" \
  -d '{
    "name": "daily-standup",
    "prompt": "Vérifiez les issues GitHub ouvertes et publiez un bref résumé sur Discord.",
    "interval_seconds": 86400,
    "channel_id": 123456789
  }'
```

### Enregistrer une tâche (Claude s'auto-enregistre pendant une session)

Claude Code peut enregistrer ses propres tâches récurrentes en utilisant l'outil Bash — sans câblage manuel :

```
# Dans une session Claude Code, Claude exécute :
curl -X POST $CCDB_API_URL/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"name": "health-check", "prompt": "Exécutez la suite de tests et rapportez les résultats.", "interval_seconds": 3600}'
```

`CCDB_API_URL` est automatiquement injecté dans l'environnement du sous-processus de Claude quand `api_port` est configuré sur le `ClaudeRunner`.

## Mise à jour automatique

Mettez automatiquement à jour le bot quand un paquet upstream est publié.

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

**Pipeline :** Push upstream → CI webhook → `🔄 bot-upgrade` → `uv lock --upgrade-package` → `uv sync` → redémarrage du service.

### Vidange gracieuse (DrainAware)

Avant de redémarrer, AutoUpgradeCog attend que toutes les sessions actives se terminent. Tout Cog qui implémente une propriété `active_count` (satisfaisant le protocole `DrainAware`) est automatiquement découvert — pas de lambda `drain_check` manuel nécessaire.

Cogs DrainAware intégrés : `ClaudeChatCog`, `WebhookTriggerCog`.

Pour rendre votre propre Cog compatible avec la vidange, ajoutez simplement une propriété `active_count` :

```python
class MyCog(commands.Cog):
    @property
    def active_count(self) -> int:
        return len(self._running_tasks)
```

Vous pouvez toujours passer un callable `drain_check` explicite pour remplacer l'autodécouverte.

### Approbation de redémarrage

Pour les scénarios de mise à jour automatique (ex. mettre à jour le bot depuis sa propre session Discord), activez `restart_approval` pour éviter les redémarrages automatiques :

```python
config = UpgradeConfig(
    package_name="claude-code-discord-bridge",
    trigger_prefix="🔄 bot-upgrade",
    working_dir="/home/user/my-bot",
    restart_command=["sudo", "systemctl", "restart", "my-bot.service"],
    restart_approval=True,
)
```

Avec `restart_approval=True`, après la mise à jour du paquet le bot publie un message demandant l'approbation. Réagissez avec ✅ pour déclencher le redémarrage. Le bot envoie des rappels périodiques jusqu'à approbation.

## API REST

API REST optionnelle pour envoyer des notifications à Discord depuis des outils externes. Nécessite aiohttp :

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
    api_secret="your-secret-token",  # Auth Bearer optionnel
)
await api.start()
```

### Endpoints

**Notifications**

| Méthode | Chemin | Description |
|---------|--------|-------------|
| GET | `/api/health` | Vérification de santé |
| POST | `/api/notify` | Envoyer une notification immédiate |
| POST | `/api/schedule` | Planifier une notification pour plus tard |
| GET | `/api/scheduled` | Lister les notifications en attente |
| DELETE | `/api/scheduled/{id}` | Annuler une notification planifiée |

**Tâches planifiées** (nécessite `SchedulerCog`)

| Méthode | Chemin | Description |
|---------|--------|-------------|
| POST | `/api/tasks` | Enregistrer une nouvelle tâche Claude Code périodique |
| GET | `/api/tasks` | Lister toutes les tâches enregistrées |
| DELETE | `/api/tasks/{id}` | Supprimer une tâche planifiée |
| PATCH | `/api/tasks/{id}` | Mettre à jour une tâche (activer/désactiver, prompt, intervalle) |

### Exemples

```bash
# Vérification de santé
curl http://localhost:8080/api/health

# Envoyer une notification
curl -X POST http://localhost:8080/api/notify \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secret-token" \
  -d '{"message": "Build réussi !", "title": "CI/CD"}'

# Planifier une notification
curl -X POST http://localhost:8080/api/schedule \
  -H "Content-Type: application/json" \
  -d '{"message": "Il est temps de réviser les PR", "scheduled_at": "2026-01-01T09:00:00"}'
```

## Architecture

```
claude_discord/
  main.py                  # Point d'entrée autonome
  bot.py                   # Classe Discord Bot
  setup.py                 # setup_bridge() — fabrique à appel unique pour tous les Cogs
  cogs/
    claude_chat.py         # Chat interactif (création de fils, traitement des messages)
    skill_command.py       # Commande slash /skill avec autocomplétion
    webhook_trigger.py     # Webhook → exécution de tâche Claude Code (CI/CD)
    auto_upgrade.py        # Webhook → mise à jour du paquet + redémarrage
    scheduler.py           # Tâches Claude Code périodiques (basé sur SQLite, boucle maîtresse de 30s)
    _run_helper.py         # Logique d'exécution Claude CLI partagée
  claude/
    runner.py              # Gestionnaire de sous-processus Claude CLI
    parser.py              # Parseur d'événements stream-json
    types.py               # Définitions de types pour les messages SDK
  database/
    models.py              # Schéma SQLite
    repository.py          # Opérations CRUD de sessions
    ask_repo.py            # CRUD des AskUserQuestion en attente (récupération après redémarrage)
    notification_repo.py   # CRUD des notifications planifiées
    task_repo.py           # CRUD des tâches planifiées (SchedulerCog)
  coordination/
    service.py             # CoordinationService — publie les événements du cycle de vie de session sur un canal partagé
  discord_ui/
    status.py              # Gestionnaire de statut par réactions emoji (avec debounce)
    chunker.py             # Division de messages avec conscience des blocs de code et des tableaux
    embeds.py              # Constructeurs d'embeds Discord
    ask_view.py            # Boutons Discord/Select Menus pour AskUserQuestion
    ask_bus.py             # Routage de bus pour les boutons AskView persistants (survit aux redémarrages)
    thread_dashboard.py    # Embed épinglé en direct montrant les états de session par fil
  ext/
    api_server.py          # Serveur API REST (optionnel, nécessite aiohttp)
                           # Inclut les endpoints /api/tasks pour SchedulerCog
  utils/
    logger.py              # Configuration du logging
```

### Philosophie de conception

- **Spawn CLI, pas API** — Nous invoquons `claude -p --output-format stream-json`, obtenant gratuitement toutes les fonctionnalités de Claude Code (CLAUDE.md, skills, outils, mémoire)
- **Discord comme colle** — Discord fournit l'interface, le threading, les notifications et l'infrastructure webhook
- **Framework, pas application** — Installez comme un paquet, ajoutez des Cogs à votre bot existant, configurez via du code
- **Sécurité par la simplicité** — ~2500 lignes de Python auditable, pas d'exécution shell, pas de chemins de code arbitraires

## Tests

```bash
uv run pytest tests/ -v --cov=claude_discord
```

473 tests couvrant le parseur, le chunker, le dépôt, le runner, le streaming, les déclencheurs webhook, la mise à jour automatique, l'API REST, l'interface AskUserQuestion, le tableau de bord d'état des fils, SchedulerCog et le dépôt de tâches.

## Comment ce projet a été construit

**Tout ce code base a été écrit par [Claude Code](https://docs.anthropic.com/en/docs/claude-code)**, l'agent de codification IA d'Anthropic. L'auteur humain ([@ebibibi](https://github.com/ebibibi)) a fourni des exigences et une direction en langage naturel, mais n'a pas lu ni édité manuellement le code source.

Cela signifie :

- **Tout le code a été généré par IA** — architecture, implémentation, tests, documentation
- **L'auteur humain ne peut pas garantir la correction au niveau du code** — révisez le code source si vous avez besoin de certitude
- **Les rapports de bugs et les PR sont les bienvenus** — Claude Code sera probablement utilisé pour les traiter aussi
- **C'est un exemple concret de logiciel open source de création IA** — utilisez-le comme référence de ce que Claude Code peut construire

Le projet a démarré le 2026-02-18 et continue d'évoluer grâce à des conversations itératives avec Claude Code.

## Exemple concret

**[EbiBot](https://github.com/ebibibi/discord-bot)** — Un bot Discord personnel qui utilise claude-code-discord-bridge comme dépendance de paquet. Comprend la synchronisation automatique de documentation (anglais + japonais), les notifications push, le watchdog Todoist et l'intégration CI/CD avec GitHub Actions. Utilisez-le comme référence pour construire votre propre bot sur ce framework.

## Inspiré par

- [OpenClaw](https://github.com/openclaw/openclaw) — Réactions de statut emoji, debouncing des messages, chunking avec conscience des blocs de code
- [claude-code-discord-bot](https://github.com/timoconnellaus/claude-code-discord-bot) — Approche CLI spawn + stream-json
- [claude-code-discord](https://github.com/zebbern/claude-code-discord) — Patterns de contrôle des permissions
- [claude-sandbox-bot](https://github.com/RhysSullivan/claude-sandbox-bot) — Modèle de fil par conversation

## Licence

MIT
