> **Note:** This is an auto-translated version of the original English documentation.
> If there are any discrepancies, the [English version](../../README.md) takes precedence.
> **Remarque :** Ceci est une version traduite automatiquement de la documentation originale en anglais.
> En cas de divergence, la [version anglaise](../../README.md) fait foi.

# Claude & Codex Discord Bridge

*Nom du package : `claude-code-discord-bridge` (kebab-case)*

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![CodeQL](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/codeql.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/codeql.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Utilisez Claude Code _ou_ OpenAI Codex depuis votre téléphone. Plusieurs fils. Tout en même temps. Développement réel inclus.**

Ouvrez Claude Code ou OpenAI Codex depuis l'application Discord de votre smartphone, lancez plusieurs fils et exécutez des sessions de développement en parallèle — sans toucher un clavier. Chaque fil Discord devient une session IA complètement isolée. Travaillez sur une fonctionnalité dans un fil, révisez un PR dans un autre et exécutez une tâche en arrière-plan dans un troisième — simultanément, en mélangeant même les backends par fil. Le bridge gère toute la coordination pour que les sessions ne se chevauchent jamais.

**Utilisez vos abonnements existants. Sans configuration de clé API.** ccdb fonctionne sur les CLIs officielles — Claude Code (inclus dans votre [abonnement Claude Pro/Max](https://claude.ai/pricing)) et OpenAI Codex (inclus dans [ChatGPT Plus/Pro/Business](https://chatgpt.com)). Changez de backend avec `/backend` ou configurez par fil — votre équipe accède aux deux IA via Discord à un coût prévisible.

**[English](../../README.md)** | **[日本語](../ja/README.md)** | **[简体中文](../zh-CN/README.md)** | **[한국어](../ko/README.md)** | **[Español](../es/README.md)** | **[Português](../pt-BR/README.md)**

> **Avertissement :** Ce projet n'est pas affilié, approuvé ni officiellement connecté à Anthropic ou OpenAI. « Claude » et « Claude Code » sont des marques commerciales d'Anthropic, PBC ; « OpenAI », « Codex » et « ChatGPT » sont des marques commerciales d'OpenAI. Il s'agit d'un outil open source indépendant qui s'interface avec Claude Code CLI et OpenAI Codex CLI.

> **Entièrement construit par Claude Code.** L'ensemble de ce codebase — architecture, implémentation, tests, documentation — a été écrit par Claude Code lui-même. L'auteur humain a fourni les exigences et la direction. Voir [Comment ce projet a été construit](#comment-ce-projet-a-été-construit).

---

## La Grande Idée : Sessions Parallèles Sans Crainte

Lorsque vous envoyez des tâches à Claude Code dans des fils Discord séparés, le bridge fait automatiquement quatre choses :

1. **Injection d'avis de concurrence** — Le system prompt de chaque session inclut des instructions obligatoires : créer un git worktree, travailler uniquement à l'intérieur, ne jamais toucher le répertoire de travail principal directement.

2. **Registre de sessions actives** — Chaque session en cours d'exécution connaît les autres. Si deux sessions vont toucher le même dépôt, elles peuvent se coordonner plutôt que d'entrer en conflit.

3. **AI Lounge** — Un « salon de repos » injecté dans chaque prompt. Avant de commencer, chaque session lit les messages récents du lounge pour voir ce que font les autres. Avant les opérations destructives (force push, redémarrage du bot, suppression DB), les sessions vérifient d'abord le lounge.

```
Fil A (fonctionnalité)  ──→  Claude Code (worktree-A)  ─┐
Fil B (révision PR)     ──→  Claude Code (worktree-B)   ├─→  #ai-lounge
Fil C (docs)            ──→  Claude Code (worktree-C)  ─┘    "A: refactor auth en cours"
                                                              "B: révision PR #42 terminée"
                                                              "C: mise à jour README"
```

Pas de conditions de course. Pas de travail perdu. Pas de surprises lors des merges.

---

## Ce Que Vous Pouvez Faire

### Chat Interactif (Mobile / Bureau)

Utilisez Claude Code depuis n'importe où où Discord fonctionne — téléphone, tablette ou bureau. Chaque message crée ou continue un fil, mappé 1:1 à une session Claude Code persistante.

### Développement Parallèle

Ouvrez plusieurs fils simultanément. Chacun est une session Claude Code indépendante avec son propre contexte, répertoire de travail et git worktree. Modèles utiles :

- **Fonctionnalité + révision en parallèle** : Démarrez une fonctionnalité dans un fil pendant que Claude révise un PR dans un autre.
- **Plusieurs contributeurs** : Différents membres de l'équipe ont leurs propres fils ; les sessions restent informées les unes des autres via l'AI Lounge.
- **Expérimentez en sécurité** : Essayez une approche dans le fil A tout en maintenant le fil B sur du code stable.

### Tâches Planifiées (SchedulerCog)

Enregistrez des tâches Claude Code périodiques depuis une conversation Discord ou via l'API REST — sans changements de code, sans redéploiements.

```
/skill name:goodmorning         → s'exécute immédiatement
Claude appelle POST /api/tasks  → enregistre une tâche périodique
SchedulerCog (boucle 30s)       → déclenche automatiquement les tâches dues
```

### Automatisation CI/CD

Déclenchez des tâches Claude Code depuis GitHub Actions via des webhooks Discord. Claude s'exécute de manière autonome — lit le code, met à jour la documentation, crée des PRs, active l'auto-merge.

**Exemple réel :** À chaque push sur `main`, Claude analyse le diff, met à jour la documentation en anglais + japonais, crée un PR bilingue et active l'auto-merge. Zéro interaction humaine.

### Synchronisation de Sessions

Vous utilisez déjà Claude Code CLI directement ? Synchronisez vos sessions de terminal existantes dans des fils Discord avec `/sync-sessions`. Remplit les messages de conversation récents pour que vous puissiez continuer une session CLI depuis votre téléphone sans perdre le contexte.

---

## Fonctionnalités

### Chat Interactif

#### 🔗 Bases de Session
- **Mode chat uniquement** — `CHAT_ONLY_CHANNEL_IDS` n'affiche que les réponses textuelles de Claude ; les embeds d'outils, blocs de réflexion, embeds de session et listes de tâches sont masqués
- **Fil = Session** — Mappage 1:1 entre fil Discord et session Claude Code
- **Suivi d'objectif** — `/goal <condition>` définit une condition de fin ; Claude continue à travailler jusqu'à ce qu'elle soit remplie
- **Persistance de session** — Continue les conversations entre les messages via `--resume`
- **Sessions concurrentes** — Plusieurs sessions parallèles avec limite configurable
- **Arrêter sans effacer** — `/stop` arrête une session en la préservant pour une reprise
- **Interruption de session** — Envoyer un nouveau message à un fil actif envoie SIGINT et recommence avec la nouvelle instruction
- **Renommage automatique des fils** — Avec `THREAD_AUTO_RENAME=true`, chaque nouveau fil est automatiquement renommé

#### 📡 Retour en Temps Réel
- **Statut en temps réel** — Réactions emoji : 🧠 réflexion, 🛠️ lecture de fichiers, 💻 édition, 🌐 recherche web
- **Texte en streaming** — Le texte intermédiaire apparaît pendant que Claude travaille
- **Embeds de résultat d'outil** — Résultats d'appels d'outils en direct avec temps écoulé
- **Réflexion étendue** — Raisonnement affiché comme embeds avec balise spoiler (cliquer pour révéler)
- **Tableau de bord des fils** — Embed épinglé en direct montrant les fils actifs vs. en attente

#### 🤝 Human-in-the-Loop
- **Questions interactives** — `AskUserQuestion` rendu comme boutons ou menu de sélection Discord ; le demandeur est @mentionné quand une saisie est nécessaire
- **Mode Plan** — `ExitPlanMode` affiche un embed Discord avec boutons Approuver/Annuler ; le demandeur est @mentionné à la demande d'approbation ; timeout 5 minutes
- **Demandes de permission d'outil** — Boutons Autoriser/Refuser ; le demandeur est @mentionné ; refus automatique après 2 minutes
- **MCP Elicitation** — Les serveurs MCP peuvent demander des saisies utilisateur via Discord ; le demandeur est @mentionné ; timeout 5 minutes
- **Progression TodoWrite en direct** — Embed Discord unique édité sur place

#### 📊 Observabilité
- **Utilisation de tokens** — Taux de succès du cache et comptages de tokens dans l'embed de session terminée
- **Utilisation du contexte** — Pourcentage de fenêtre de contexte ; avertissement ⚠️ au-dessus de 83,5%
- **Détection de compaction** — Notifie dans le fil lorsque la compaction de contexte se produit
- **Notification de blocage prolongé** — Message dans le fil après inactivité (30s standard, 120s pour Opus)
- **Notifications de timeout** — Embed avec temps écoulé et guide de reprise
- **Affichage StatusLine** — Affiche le statut de Claude après chaque session
- **Boîte de réception des fils** — Avec `THREAD_INBOX_ENABLED=true`, section 📬 dans le tableau de bord

#### 🔌 Entrée et Compétences
- **Support des pièces jointes** — Fichiers texte ajoutés automatiquement (jusqu'à 5 fichiers, 200 Ko chacun) ; images comme URLs CDN (jusqu'à 4 × 5 Mo)
- **Livraison de fichiers à la demande** — Claude écrit le chemin dans `.ccdb-attachments` ; envoyé comme pièce jointe Discord à la fin de la session
- **Exécution de compétences** — Commande `/skill` avec autocomplétion ; compétences des plugins installés aussi découvertes
- **Hot reload** — Les nouvelles compétences dans `~/.claude/skills/` détectées automatiquement (actualisation 60s)

### Concurrence et Coordination
- **Instructions Worktree auto-injectées** — Chaque session incitée à utiliser `git worktree`
- **Nettoyage automatique des worktrees** — Worktrees de session supprimés automatiquement ; les worktrees sales ne sont jamais supprimés automatiquement
- **Registre de sessions actives** — Registre en mémoire ; chaque session voit ce que font les autres
- **AI Lounge** — Canal partagé ; contexte injecté via `--append-system-prompt` (n'accumule pas dans l'historique)
- **Canal de coordination** — `COORDINATION_CHANNEL_ID` comme fallback par défaut pour AI Lounge

### Tâches Planifiées
- **SchedulerCog** — Exécuteur de tâches périodiques avec support SQLite, boucle maître 30 secondes
- **Auto-enregistrement** — Claude enregistre des tâches via `POST /api/tasks`
- **Sans changements de code** — Ajoutez, supprimez ou modifiez des tâches à l'exécution
- **Activer/désactiver** — Mettez en pause les tâches sans les supprimer (`PATCH /api/tasks/{id}`)

### Automatisation CI/CD
- **Déclencheurs Webhook** — Déclenchez des tâches depuis GitHub Actions ou tout système CI/CD
- **Auto-mise à jour** — Met à jour le bot automatiquement lors de publications de packages en amont
- **Redémarrage DrainAware** — Attend que les sessions actives se terminent avant de redémarrer
- **Marquage automatique de reprise** — Les sessions actives sont automatiquement marquées lors de tout arrêt
- **Déclencheur manuel de mise à jour** — Commande `/upgrade` (opt-in via `slash_command_enabled=True`)

### Gestion de Session
- **Aide intégrée** — `/help` affiche toutes les commandes slash disponibles (éphémère)
- **Synchronisation de session** — Importez des sessions CLI comme fils Discord (`/sync-sessions`)
- **Liste de sessions** — `/sessions` avec filtrage par origine et fenêtre temporelle
- **Reprendre une session** — `/resume` affiche un menu de sélection et reprend dans un nouveau fil
- **Effacer une session** — `/clear` réinitialise la session Claude Code du fil actuel
- **Reprise au démarrage** — Les sessions interrompues reprennent automatiquement après tout redémarrage du bot
- **Spawn programmatique** — `POST /api/spawn` crée un nouveau fil + session depuis n'importe quel script
- **Gestion des Worktrees** — `/worktree-list` et `/worktree-cleanup`
- **Changement de modèle à l'exécution** — `/model-show` et `/model-set`, sans redémarrer
- **Rembobinage de conversation** — `/rewind` tronque la session au tour sélectionné
- **Bifurcation de conversation** — `/fork` crée une copie de session indépendante dans un nouveau fil

### Sécurité
- **Pas d'injection de shell** — Seulement `asyncio.create_subprocess_exec`, jamais `shell=True`
- **Validation de l'ID de session** — Regex stricte avant de passer à `--resume`
- **Prévention d'injection de flags** — Séparateur `--` avant tous les prompts
- **Isolation des secrets** — Token du bot supprimé de l'environnement du sous-processus
- **Autorisation des utilisateurs** — `allowed_user_ids` restreint qui peut invoquer Claude
- **Prévention d'injection dans les logs** — Valeurs API fournies par l'utilisateur assainies avant écriture dans les logs

---

## Démarrage Rapide — Claude dans Discord en 5 Minutes

**Prérequis :** Python 3.10+, [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installé et authentifié.

**Support des plateformes :** Principalement développé et testé sur **Linux**. macOS et Windows sont pris en charge et passent les CI, mais reçoivent moins de tests réels.

### Étape 1 — Créer un Bot Discord (une fois, ~2 minutes)

1. Allez sur [discord.com/developers/applications](https://discord.com/developers/applications) → **New Application**
2. Naviguez vers **Bot** → activez **Message Content Intent** sous Privileged Gateway Intents
3. Copiez le **Token** du bot
4. Allez dans **OAuth2 → URL Generator** : Portées `bot` + `applications.commands`, Permissions : Send Messages, Create Public Threads, Send Messages in Threads, Add Reactions, Manage Messages, Read Message History
5. Ouvrez l'URL générée → invitez le bot sur votre serveur

### Étape 2 — Exécuter l'Assistant de Configuration

Pas besoin de cloner ni d'éditer `.env` — l'assistant fait tout :

```bash
# Avec uvx (pas d'installation requise) :
uvx --from "git+https://github.com/ebibibi/claude-code-discord-bridge.git" ccdb setup

# Ou après avoir cloné :
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge
uv run ccdb setup
```

### Démarrer / Arrêter

```bash
ccdb start    # démarrer le bot (lit .env dans le répertoire courant)
ccdb start --env /path/to/.env   # emplacement .env personnalisé
```

Envoyez un message dans le canal configuré — Claude répondra dans un nouveau fil.

### Exécuter comme Service systemd (Production)

```bash
sudo cp discord-bot.service /etc/systemd/system/mybot.service
sudo nano /etc/systemd/system/mybot.service
sudo systemctl daemon-reload
sudo systemctl enable mybot.service
sudo systemctl start mybot.service
journalctl -u mybot.service -f
```

### Cogs Personnalisés (Étendez Sans Forker)

Ajoutez vos propres fonctionnalités en déposant des fichiers Python dans un répertoire — sans fork, sans sous-classe, sans package :

```bash
ccdb start --cogs-dir ./my-cogs/
# Ou : CUSTOM_COGS_DIR=./my-cogs ccdb start
```

Chaque fichier `.py` doit exposer `async def setup(bot, runner, components)`.

---

### Bot Minimal (Installer comme Package)

```bash
uv add git+https://github.com/ebibibi/claude-code-discord-bridge.git
```

Créez `bot.py` :

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

`setup_bridge()` connecte automatiquement tous les Cogs. Mise à jour vers la dernière version :

```bash
uv lock --upgrade-package claude-code-discord-bridge && uv sync
```

---

## Configuration

| Variable | Description | Défaut |
|----------|-------------|--------|
| `DISCORD_BOT_TOKEN` | Token du bot Discord | (requis) |
| `DISCORD_CHANNEL_ID` | ID de canal pour le chat Claude | (requis) |
| `CCDB_BACKEND` | Backend CLI à utiliser : `claude` ou `codex` | `claude` |
| `CCDB_COMMAND` | Chemin ou nom du binaire CLI (remplace `CLAUDE_COMMAND`) | _(auto)_ |
| `CCDB_MODEL` | Modèle à utiliser (remplace `CLAUDE_MODEL`) | `sonnet` |
| `CCDB_PERMISSION_MODE` | Mode de permission CLI (remplace `CLAUDE_PERMISSION_MODE`) | `acceptEdits` |
| `CCDB_DANGEROUSLY_SKIP_PERMISSIONS` | Ignorer toutes les vérifications de permission | `false` |
| `CCDB_WORKING_DIR` | Répertoire de travail CLI | répertoire courant |
| `CCDB_ALLOWED_TOOLS` | Liste d'outils autorisés séparés par des virgules | (optionnel) |
| `CCDB_CHANNEL_IDS` | IDs de canaux supplémentaires pour configuration multi-canal | (optionnel) |
| `CLAUDE_COMMAND` | Chemin CLI Claude (nom hérité — préférer `CCDB_COMMAND`) | `claude` |
| `CLAUDE_MODEL` | Modèle (nom hérité — préférer `CCDB_MODEL`) | `sonnet` |
| `CLAUDE_PERMISSION_MODE` | Mode de permission (nom hérité — préférer `CCDB_PERMISSION_MODE`) | `acceptEdits` |
| `CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS` | Ignorer les permissions (nom hérité) | `false` |
| `CLAUDE_WORKING_DIR` | Répertoire de travail (nom hérité) | répertoire courant |
| `MAX_CONCURRENT_SESSIONS` | Maximum de sessions CLI parallèles | `3` |
| `SESSION_TIMEOUT_SECONDS` | Timeout d'inactivité de session | `300` |
| `DISCORD_OWNER_ID` | ID utilisateur à @mentionner quand Claude a besoin d'entrée | (optionnel) |
| `COORDINATION_CHANNEL_ID` | ID de canal comme fallback par défaut pour AI Lounge | (optionnel) |
| `MENTION_ONLY_CHANNEL_IDS` | IDs de canaux où le bot répond seulement quand @mentionné (séparés par virgule) | (optionnel) |
| `INLINE_REPLY_CHANNEL_IDS` | IDs de canaux de réponse inline (séparés par virgule, sans créer de fil) | (optionnel) |
| `CHAT_ONLY_CHANNEL_IDS` | IDs de canaux en mode chat uniquement (séparés par virgule) | (optionnel) |
| `WORKTREE_BASE_DIR` | Répertoire de base pour scanner les worktrees de session | (optionnel) |
| `CLI_SESSIONS_PATH` | Chemin pour la découverte de sessions CLI (`~/.claude/projects`) | (optionnel) |
| `CUSTOM_COGS_DIR` | Répertoire contenant les fichiers Cog personnalisés | (optionnel) |
| `THREAD_INBOX_ENABLED` | Activer la boîte de réception de fils persistante | `false` |
| `THREAD_AUTO_RENAME` | Renommer automatiquement les nouveaux fils avec un titre généré par Claude | `false` |
| `CCDB_CLI_ENV_FILE` | Chemin vers le fichier `KEY=VALUE` fusionné dans l'environnement du sous-processus CLI | (optionnel) |
| `CCDB_LOG_FILE` | Chemin vers le fichier de log. Quand défini, un gestionnaire de fichier rotatif (10 Mo × 5 sauvegardes) est ajouté en plus du stdout. Utile pour la surveillance et les alertes | (optionnel) |
| `API_HOST` | Adresse de liaison de l'API REST | `127.0.0.1` |
| `API_PORT` | Port de l'API REST (active l'API REST quand configuré) | (optionnel) |

---

## API REST

API REST optionnelle pour les notifications et la gestion des tâches. Nécessite aiohttp :

```bash
uv add "claude-code-discord-bridge[api]"
```

### Endpoints

| Méthode | Chemin | Description |
|---------|--------|-------------|
| GET | `/api/health` | Vérification de santé |
| POST | `/api/notify` | Envoyer notification immédiate |
| POST | `/api/schedule` | Planifier notification |
| GET | `/api/scheduled` | Lister les notifications en attente |
| DELETE | `/api/scheduled/{id}` | Annuler notification |
| POST | `/api/tasks` | Enregistrer tâche Claude Code périodique |
| GET | `/api/tasks` | Lister les tâches enregistrées |
| DELETE | `/api/tasks/{id}` | Supprimer tâche |
| PATCH | `/api/tasks/{id}` | Mettre à jour tâche |
| POST | `/api/spawn` | Créer nouveau fil Discord et démarrer session Claude Code (non bloquant) |
| POST | `/api/mark-resume` | Marquer fil pour reprise automatique au prochain démarrage du bot |
| GET | `/api/lounge` | Lire les messages récents de l'AI Lounge |
| POST | `/api/lounge` | Publier message dans l'AI Lounge |

---

## Architecture

```
claude_code_core/          # Bibliothèque centrale partagée (indépendante du backend)
  backend.py               # Protocole SessionBackend + fabrique create_backend()
  codex_runner.py          # Backend OpenAI Codex CLI
  runner.py                # Gestionnaire de sous-processus Claude CLI
  parser.py                # Analyseur d'événements stream-json
  types.py                 # Définitions de types pour messages SDK
claude_discord/
  main.py                  # Point d'entrée autonome
  cli.py                   # Point d'entrée CLI (commandes ccdb setup/start)
  setup.py                 # setup_bridge()
  cogs/
    claude_chat.py         # Chat interactif
    skill_command.py       # Commande slash /skill
    session_manage.py      # Gestion de session
    scheduler.py           # Exécuteur de tâches périodiques
    webhook_trigger.py     # Webhook → exécution de tâche Claude Code
    auto_upgrade.py        # Auto-mise à jour + redémarrage avec vidange
  ext/
    api_server.py          # API REST (optionnel)
examples/
  ebibot/                  # Exemple réel
```

### Philosophie de Conception

- **Spawn de CLI, pas API** — Invoque `claude -p --output-format stream-json`, obtenant toutes les fonctionnalités de Claude Code sans les réimplémenter. Sans clé API, sans facturation par token.
- **Concurrence d'abord** — Plusieurs sessions simultanées sont le cas attendu, pas un cas limite
- **Discord comme colle** — Discord fournit UI, threading, réactions, webhooks et notifications persistantes
- **Framework, pas application** — Installez comme package, ajoutez des Cogs à votre bot existant
- **Extensibilité sans code** — Ajoutez des tâches planifiées et des déclencheurs webhook sans toucher au code source
- **Sécurité par simplicité** — ~8000 lignes de Python auditable ; seulement subprocess exec, pas d'expansion de shell

---

## Tests

```bash
uv run pytest tests/ -v --cov=claude_discord
```

Plus de 1365 tests couvrant l'analyseur, le chunker, le référentiel, le runner, le streaming, les déclencheurs webhook, l'auto-mise à jour, l'API REST, l'UI AskUserQuestion, le tableau de bord des fils, les tâches planifiées, la synchronisation de session, l'AI Lounge, la reprise au démarrage, le changement de modèle, la détection de compaction, les embeds de progression TodoWrite, le chargeur de Cogs personnalisés, le protocole SessionBackend, CodexRunner et la fabrique de backends.

---

## Comment ce Projet a été Construit

**Ce codebase est développé par [Claude Code](https://docs.anthropic.com/en/docs/claude-code)**, l'agent de codage AI d'Anthropic, sous la direction de [@ebibibi](https://github.com/ebibibi). L'auteur humain définit les exigences, révise les pull requests et approuve tous les changements — Claude Code fait l'implémentation.

Le projet a commencé le 2026-02-18 et continue d'évoluer grâce à des conversations itératives avec Claude Code.

---

## Exemple Réel

**[`examples/ebibot/`](examples/ebibot/)** — Un bot Discord personnel construit sur ce framework, inclus directement dans ce dépôt. Démontre le chargeur de Cog personnalisé avec :

- **ReminderCog** — Commande slash `/remind HH:MM "message"` + boucle d'envoi de 30 secondes
- **WatchdogCog** — Moniteur de tâches Todoist en retard
- **AutoUpgradeCog** — Auto-mise à jour via webhook GitHub + systemctl restart
- **DocsSyncCog** — Synchronisation automatique de documentation à chaque push
- **AlertResponderCog** — Cog de surveillance d'alertes générique

Exécutez avec : `ccdb start --cogs-dir examples/ebibot/cogs/`

---

## Inspiré Par

- [OpenClaw](https://github.com/openclaw/openclaw) — Réactions emoji de statut, debouncing de messages, chunking conscient des fences
- [claude-code-discord-bot](https://github.com/timoconnellaus/claude-code-discord-bot) — Approche CLI spawn + stream-json
- [claude-code-discord](https://github.com/zebbern/claude-code-discord) — Modèles de contrôle de permissions
- [claude-sandbox-bot](https://github.com/RhysSullivan/claude-sandbox-bot) — Modèle de conversation par fil

---

## Licence

MIT
