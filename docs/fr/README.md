> **Note:** This is an auto-translated version of the original English documentation.
> If there are any discrepancies, the [English version](../../README.md) takes precedence.
> **Remarque :** Ceci est une version traduite automatiquement de la documentation originale en anglais.
> En cas de divergence, la [version anglaise](../../README.md) fait foi.

# claude-code-discord-bridge

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Exécutez plusieurs sessions Claude Code en parallèle — en toute sécurité — via Discord.**

Chaque fil Discord devient une session Claude Code isolée. Ouvrez-en autant que nécessaire : travaillez sur une fonctionnalité dans un fil, révisez une PR dans un autre, exécutez une tâche planifiée dans un troisième. Le bridge gère automatiquement la coordination pour que les sessions simultanées ne se marchent pas dessus.

**[English](../../README.md)** | **[日本語](../ja/README.md)** | **[简体中文](../zh-CN/README.md)** | **[한국어](../ko/README.md)** | **[Español](../es/README.md)** | **[Português](../pt-BR/README.md)**

> **Avertissement :** Ce projet n'est pas affilié, approuvé ou officiellement connecté à Anthropic. « Claude » et « Claude Code » sont des marques déposées d'Anthropic, PBC. Ceci est un outil open source indépendant qui s'interface avec Claude Code CLI.

> **Entièrement construit par Claude Code.** Architecture, implémentation, tests, documentation — cette base de code a été entièrement écrite par Claude Code lui-même. L'auteur humain a fourni les exigences et la direction en langage naturel. Voir [Comment ce projet a été construit](#comment-ce-projet-a-été-construit) pour les détails.

---

## L'idée principale : des sessions parallèles sans crainte

Quand vous envoyez des tâches à Claude Code dans des fils Discord séparés, le bridge fait automatiquement quatre choses :

1. **Injection automatique des instructions de concurrence** — Le prompt système de chaque session inclut des instructions obligatoires : créer un git worktree, travailler uniquement à l'intérieur, ne jamais toucher directement le répertoire de travail principal.

2. **Registre de sessions actives** — Chaque session en cours connaît les autres. Si deux sessions s'apprêtent à toucher le même dépôt, elles peuvent se coordonner plutôt que conflictuer.

3. **Canal de coordination** — Un canal Discord partagé où les sessions diffusent leurs événements de démarrage/fin. Claude et les humains peuvent voir d'un coup d'œil ce qui se passe dans tous les fils actifs.

4. **AI Lounge** — Une « salle de pause » session-à-session injectée dans chaque prompt. Avant de commencer, chaque session lit les messages récents du lounge pour voir ce que font les autres. Avant des opérations destructives (force push, redémarrage du bot, suppression de DB), les sessions vérifient d'abord le lounge pour ne pas piétiner le travail des autres.

```
Fil A (fonctionnalité) ──→  Claude Code (worktree-A)  ─┐
Fil B (revue PR)       ──→  Claude Code (worktree-B)   ├─→  #ai-lounge
Fil C (docs)           ──→  Claude Code (worktree-C)  ─┘    "A: refacto auth en cours"
           ↓ événements lifecycle                            "B: revue PR #42 terminée"
   #canal de coordination                                    "C: mise à jour README"
   "A: début refacto auth"
   "B: revue PR #42"
   "C: mise à jour README"
```

Pas de conditions de course. Pas de travail perdu. Pas de surprises de fusion.

---

## Ce que vous pouvez faire

### Chat interactif (Mobile / Bureau)

Utilisez Claude Code de partout où Discord fonctionne — téléphone, tablette ou bureau. Chaque message crée ou continue un fil, mappé 1:1 à une session Claude Code persistante.

### Développement parallèle

Ouvrez plusieurs fils simultanément. Chacun est une session Claude Code indépendante avec son propre contexte, répertoire de travail et git worktree. Schémas utiles :

- **Fonctionnalité + revue en parallèle** : Démarrez une fonctionnalité dans un fil pendant que Claude révise une PR dans un autre.
- **Plusieurs contributeurs** : Différents membres de l'équipe ont chacun leur fil ; les sessions restent au courant les unes des autres via le canal de coordination.
- **Expérimenter en sécurité** : Essayez une approche dans le fil A tout en gardant le fil B sur du code stable.

### Tâches planifiées (SchedulerCog)

Enregistrez des tâches Claude Code périodiques depuis une conversation Discord ou via REST API — sans changement de code, sans redéploiement. Les tâches sont stockées dans SQLite et s'exécutent selon un planning configurable.

```
/skill name:goodmorning         → s'exécute immédiatement
Claude appelle POST /api/tasks  → enregistre une tâche périodique
SchedulerCog (boucle maître 30s) → déclenche automatiquement les tâches dues
```

### Automatisation CI/CD

Déclenchez des tâches Claude Code depuis GitHub Actions via des webhooks Discord. Claude s'exécute de manière autonome — lit le code, met à jour la documentation, crée des PRs, active l'auto-merge.

```
GitHub Actions → Discord Webhook → Bridge → Claude Code CLI
                                                  ↓
GitHub PR ←── git push ←── Claude Code ──────────┘
```

**Exemple concret :** À chaque push sur `main`, Claude analyse le diff, met à jour la documentation anglaise + japonaise, crée une PR avec un résumé bilingue, et active l'auto-merge. Aucune intervention humaine.

### Synchronisation de sessions

Vous utilisez déjà Claude Code CLI directement ? Synchronisez vos sessions terminal existantes dans des fils Discord avec `/sync-sessions`. Remplit les messages de conversation récents pour que vous puissiez continuer une session CLI depuis votre téléphone sans perdre le contexte.

### AI Lounge

Un canal « salle de pause » partagé où toutes les sessions simultanées s'annoncent, lisent les mises à jour des autres et se coordonnent avant des opérations destructives.

Chaque session Claude reçoit automatiquement le contexte du lounge dans son prompt système : les messages récents des autres sessions, plus la règle de vérification avant toute opération destructive.

```bash
# Les sessions publient leurs intentions avant de commencer :
curl -X POST "$CCDB_API_URL/api/lounge" \
  -H "Content-Type: application/json" \
  -d '{"message": "Début refacto auth sur feature/oauth — worktree-A", "label": "dev fonctionnalité"}'

# Lire les messages récents du lounge (aussi injectés automatiquement dans chaque session) :
curl "$CCDB_API_URL/api/lounge"
```

Le canal lounge fait aussi office de flux d'activité visible par les humains — ouvrez-le dans Discord pour voir d'un coup d'œil ce que fait chaque session Claude active.

### Création de sessions programmatique

Créez de nouvelles sessions Claude Code depuis des scripts, GitHub Actions ou d'autres sessions Claude — sans interaction de messages Discord.

```bash
# Depuis une autre session Claude ou un script CI :
curl -X POST "$CCDB_API_URL/api/spawn" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Exécuter un scan de sécurité sur le dépôt", "thread_name": "Scan sécurité"}'
# Retourne immédiatement avec l'ID du fil ; Claude s'exécute en arrière-plan
```

### Reprise au démarrage

Si le bot redémarre en cours de session, les sessions Claude interrompues reprennent automatiquement quand le bot revient en ligne. Les sessions sont marquées pour reprise de trois façons :

- **Automatique (redémarrage de mise à niveau)** — `AutoUpgradeCog` capture toutes les sessions actives juste avant un redémarrage de mise à niveau de paquet et les marque automatiquement.
- **Automatique (tout arrêt)** — `ClaudeChatCog.cog_unload()` marque toutes les sessions en cours chaque fois que le bot s'arrête via n'importe quel mécanisme (`systemctl stop`, `bot.close()`, SIGTERM, etc.).
- **Manuel** — N'importe quelle session peut appeler directement `POST /api/mark-resume`.

---

## Fonctionnalités

### Chat interactif
- **Thread = Session** — Correspondance 1:1 entre fil Discord et session Claude Code
- **Statut en temps réel** — Réactions emoji : 🧠 réflexion, 🛠️ lecture de fichiers, 💻 édition, 🌐 recherche web
- **Texte en streaming** — Le texte intermédiaire de l'assistant apparaît pendant que Claude travaille
- **Embeds de résultats d'outils** — Résultats d'appels d'outils en direct avec temps écoulé montant toutes les 10s
- **Réflexion étendue** — Raisonnement affiché en embeds avec balises spoiler (cliquer pour révéler)
- **Persistance de session** — Reprise des conversations entre messages via `--resume`
- **Exécution de skills** — Commande `/skill` avec autocomplétion, arguments optionnels, reprise dans le fil
- **Rechargement à chaud** — Les nouveaux skills ajoutés dans `~/.claude/skills/` sont détectés automatiquement (rafraîchissement 60s, sans redémarrage)
- **Sessions simultanées** — Plusieurs sessions parallèles avec limite configurable
- **Arrêt sans effacement** — `/stop` interrompt une session tout en la préservant pour reprise
- **Support des pièces jointes** — Fichiers texte ajoutés automatiquement au prompt (jusqu'à 5 × 50 Ko)
- **Notifications de délai** — Embed avec temps écoulé et guide de reprise en cas de timeout
- **Questions interactives** — `AskUserQuestion` rendu en Boutons Discord ou Menu de sélection ; la session reprend avec votre réponse ; les boutons survivent aux redémarrages du bot
- **Tableau de bord des fils** — Embed épinglé en direct montrant quels fils sont actifs ou en attente ; @mention du propriétaire quand une saisie est nécessaire
- **Utilisation des tokens** — Taux de cache hit et comptages de tokens affichés dans l'embed de fin de session

### Concurrence et coordination
- **Instructions worktree auto-injectées** — Chaque session invitée à utiliser `git worktree` avant de toucher un fichier
- **Nettoyage automatique des worktrees** — Les worktrees de session (`wt-{thread_id}`) sont supprimés automatiquement à la fin de session et au démarrage du bot ; les worktrees sales ne sont jamais auto-supprimés (invariant de sécurité)
- **Registre de sessions actives** — Registre en mémoire ; chaque session voit ce que font les autres
- **AI Lounge** — Canal « salle de pause » partagé injecté dans chaque prompt de session ; les sessions publient leurs intentions, lisent le statut des autres, et vérifient avant des opérations destructives ; les humains le voient comme un flux d'activité en direct
- **Canal de coordination** — Canal partagé optionnel pour les diffusions de lifecycle inter-sessions
- **Scripts de coordination** — Claude peut appeler `coord_post.py` / `coord_read.py` depuis une session pour publier et lire des événements

### Tâches planifiées
- **SchedulerCog** — Exécuteur de tâches périodiques basé sur SQLite avec une boucle maître de 30 secondes
- **Auto-enregistrement** — Claude enregistre des tâches via `POST /api/tasks` pendant une session de chat
- **Aucun changement de code** — Ajoutez, supprimez ou modifiez des tâches à l'exécution
- **Activer/désactiver** — Mettez des tâches en pause sans les supprimer (`PATCH /api/tasks/{id}`)

### Automatisation CI/CD
- **Déclencheurs webhook** — Déclenchez des tâches Claude Code depuis GitHub Actions ou tout système CI/CD
- **Mise à niveau automatique** — Mettez à jour automatiquement le bot quand des paquets en amont sont publiés
- **Redémarrage DrainAware** — Attend que les sessions actives se terminent avant de redémarrer
- **Marquage auto-reprise** — Les sessions actives sont automatiquement marquées pour reprise à tout arrêt ; reprennent où elles en étaient après le retour en ligne du bot
- **Approbation de redémarrage** — Portail optionnel pour confirmer les mises à niveau avant application

### Gestion de sessions
- **Synchronisation de sessions** — Importez des sessions CLI comme fils Discord (`/sync-sessions`)
- **Liste de sessions** — `/sessions` avec filtrage par origine (Discord / CLI / tous) et fenêtre temporelle
- **Info de reprise** — `/resume-info` affiche la commande CLI pour continuer la session courante dans un terminal
- **Reprise au démarrage** — Les sessions interrompues redémarrent automatiquement après tout redémarrage du bot
- **Création programmatique** — `POST /api/spawn` crée un nouveau fil Discord + session Claude depuis n'importe quel script ou sous-processus Claude
- **Injection de l'ID de fil** — La variable d'env `DISCORD_THREAD_ID` est passée à chaque sous-processus Claude, permettant aux sessions de créer des sessions enfants via `$CCDB_API_URL/api/spawn`
- **Gestion des worktrees** — `/worktree-list` affiche tous les worktrees de session actifs avec statut clean/dirty ; `/worktree-cleanup` supprime les worktrees clean orphelins

### Sécurité
- **Pas d'injection shell** — `asyncio.create_subprocess_exec` uniquement, jamais `shell=True`
- **Validation d'ID de session** — Regex stricte avant passage à `--resume`
- **Prévention d'injection de flags** — Séparateur `--` avant tous les prompts
- **Isolation des secrets** — Token du bot supprimé de l'environnement du sous-processus
- **Autorisation utilisateur** — `allowed_user_ids` restreint qui peut invoquer Claude

---

## Démarrage rapide — Claude dans Discord en 5 minutes

### Étape 1 — Prérequis

- **Python 3.10+** et **[uv](https://docs.astral.sh/uv/)** installés
- **[Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code)** installé et authentifié (`claude --version` doit fonctionner)
- Un **serveur Discord** où vous avez les droits admin

### Étape 2 — Créer un bot Discord

1. Allez sur [discord.com/developers/applications](https://discord.com/developers/applications) et cliquez sur **New Application**
2. Naviguez vers **Bot** → cliquez sur **Add Bot**
3. Sous **Privileged Gateway Intents**, activez **Message Content Intent**
4. Copiez le **Token** du bot (vous en aurez besoin bientôt)
5. Allez dans **OAuth2 → URL Generator** :
   - Scopes : `bot`, `applications.commands`
   - Bot Permissions : `Send Messages`, `Create Public Threads`, `Send Messages in Threads`, `Add Reactions`, `Manage Messages`, `Read Message History`
6. Ouvrez l'URL générée dans votre navigateur et invitez le bot sur votre serveur

### Étape 3 — Obtenir vos IDs Discord

Activez le **Mode développeur** dans Discord (Paramètres → Avancé → Mode développeur), puis :

- **ID de canal** : Clic droit sur le canal où Claude doit écouter → **Copier l'ID du canal**
- **Votre ID utilisateur** : Clic droit sur votre nom d'utilisateur → **Copier l'ID de l'utilisateur**

### Étape 4 — Lancer

```bash
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge
cp .env.example .env
```

Éditez `.env` :

```env
DISCORD_BOT_TOKEN=your-bot-token-here
DISCORD_CHANNEL_ID=123456789012345678    # le canal copié ci-dessus
DISCORD_OWNER_ID=987654321098765432      # votre ID utilisateur (pour les @-mentions)
CLAUDE_WORKING_DIR=/path/to/your/project
```

Puis démarrez le bot :

```bash
uv run python -m claude_discord.main
```

Envoyez un message dans le canal configuré — Claude répondra dans un nouveau fil.

---

### Bot minimal (installer comme paquet)

Si vous avez déjà un bot discord.py, ajoutez ccdb comme paquet à la place :

```bash
uv add git+https://github.com/ebibibi/claude-code-discord-bridge.git
```

Créez un `bot.py` :

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
    print(f"Connecté en tant que {bot.user}")
    await setup_bridge(
        bot,
        runner,
        claude_channel_id=int(os.environ["DISCORD_CHANNEL_ID"]),
        allowed_user_ids={int(os.environ["DISCORD_OWNER_ID"])},
    )

asyncio.run(bot.start(os.environ["DISCORD_BOT_TOKEN"]))
```

`setup_bridge()` connecte automatiquement tous les Cogs. Mise à jour vers la dernière version :

```bash
uv lock --upgrade-package claude-code-discord-bridge && uv sync
```

---

## Configuration

| Variable | Description | Défaut |
|----------|-------------|--------|
| `DISCORD_BOT_TOKEN` | Votre token de bot Discord | (requis) |
| `DISCORD_CHANNEL_ID` | ID de canal pour le chat Claude | (requis) |
| `CLAUDE_COMMAND` | Chemin vers Claude Code CLI | `claude` |
| `CLAUDE_MODEL` | Modèle à utiliser | `sonnet` |
| `CLAUDE_PERMISSION_MODE` | Mode de permission pour le CLI | `acceptEdits` |
| `CLAUDE_WORKING_DIR` | Répertoire de travail pour Claude | répertoire courant |
| `MAX_CONCURRENT_SESSIONS` | Sessions parallèles maximum | `3` |
| `SESSION_TIMEOUT_SECONDS` | Délai d'inactivité de session | `300` |
| `DISCORD_OWNER_ID` | ID utilisateur à @-mentionner quand Claude a besoin d'une saisie | (optionnel) |
| `COORDINATION_CHANNEL_ID` | ID de canal pour les diffusions d'événements inter-sessions | (optionnel) |
| `CCDB_COORDINATION_CHANNEL_NAME` | Créer automatiquement un canal de coordination par nom | (optionnel) |
| `WORKTREE_BASE_DIR` | Répertoire de base pour scanner les worktrees de session (active le nettoyage automatique) | (optionnel) |

---

## REST API

API REST optionnelle pour les notifications et la gestion des tâches. Nécessite aiohttp :

```bash
uv add "claude-code-discord-bridge[api]"
```

### Points de terminaison

| Méthode | Chemin | Description |
|---------|--------|-------------|
| GET | `/api/health` | Vérification de santé |
| POST | `/api/notify` | Envoyer une notification immédiate |
| POST | `/api/schedule` | Planifier une notification |
| GET | `/api/scheduled` | Lister les notifications en attente |
| DELETE | `/api/scheduled/{id}` | Annuler une notification |
| POST | `/api/tasks` | Enregistrer une tâche Claude Code planifiée |
| GET | `/api/tasks` | Lister les tâches enregistrées |
| DELETE | `/api/tasks/{id}` | Supprimer une tâche |
| PATCH | `/api/tasks/{id}` | Mettre à jour une tâche (activer/désactiver, changer le planning) |
| POST | `/api/spawn` | Créer un nouveau fil Discord et démarrer une session Claude Code (non-bloquant) |
| POST | `/api/mark-resume` | Marquer un fil pour reprise automatique au prochain démarrage du bot |
| GET | `/api/lounge` | Lire les messages récents de l'AI Lounge |
| POST | `/api/lounge` | Publier un message dans l'AI Lounge (avec `label` optionnel) |

---

## Tests

```bash
uv run pytest tests/ -v --cov=claude_discord
```

610+ tests couvrant le parser, le chunker, le repository, le runner, le streaming, les déclencheurs webhook, la mise à niveau automatique, l'API REST, l'UI AskUserQuestion, le tableau de bord des fils, les tâches planifiées, la synchronisation de sessions, l'AI Lounge et la reprise au démarrage.

---

## Comment ce projet a été construit

**Cette base de code est développée par [Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — l'agent de codage IA d'Anthropic — sous la direction de [@ebibibi](https://github.com/ebibibi). L'auteur humain définit les exigences, révise les pull requests et approuve tous les changements — Claude Code fait l'implémentation.

Cela signifie :

- **L'implémentation est générée par IA** — architecture, code, tests, documentation
- **La revue humaine s'applique au niveau PR** — chaque changement passe par des pull requests GitHub et CI avant la fusion
- **Les rapports de bugs et PRs sont les bienvenus** — Claude Code sera utilisé pour les traiter
- **C'est un exemple concret de logiciel open source dirigé par l'humain et implémenté par l'IA**

Le projet a démarré le 2026-02-18 et continue d'évoluer à travers des conversations itératives avec Claude Code.

---

## Exemple concret

**[EbiBot](https://github.com/ebibibi/discord-bot)** — Un bot Discord personnel construit sur ce framework. Inclut la synchronisation automatique de documentation (anglais + japonais), les notifications push, le watchdog Todoist, les vérifications de santé planifiées et CI/CD GitHub Actions. Utilisez-le comme référence pour construire votre propre bot.

---

## Licence

MIT
