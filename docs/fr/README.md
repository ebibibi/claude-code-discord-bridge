> **Note:** This is an auto-translated version of the original English documentation.
> If there are any discrepancies, the [English version](../../README.md) takes precedence.
> **Remarque :** Ceci est une version traduite automatiquement de la documentation originale en anglais.
> En cas de divergence, la [version anglaise](../../README.md) fait foi.

# claude-code-discord-bridge

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Exécutez plusieurs sessions Claude Code en parallèle — en toute sécurité — via Discord.**

Chaque fil Discord devient une session Claude Code isolée. Lancez-en autant que nécessaire : travaillez sur une fonctionnalité dans un fil, révisez un PR dans un autre, exécutez une tâche planifiée dans un troisième. Le bridge gère automatiquement la coordination pour que les sessions simultanées ne se perturbent pas mutuellement.

**[English](../../README.md)** | **[日本語](../ja/README.md)** | **[简体中文](../zh-CN/README.md)** | **[한국어](../ko/README.md)** | **[Español](../es/README.md)** | **[Português](../pt-BR/README.md)**

> **Avertissement :** Ce projet n'est pas affilié, approuvé ou officiellement connecté à Anthropic. « Claude » et « Claude Code » sont des marques déposées d'Anthropic, PBC. Ceci est un outil open source indépendant qui s'interface avec Claude Code CLI.

> **Entièrement construit par Claude Code.** L'intégralité de ce code base — architecture, implémentation, tests, documentation — a été écrite par Claude Code lui-même. L'auteur humain a fourni les exigences et la direction en langage naturel, mais n'a pas lu ni édité manuellement le code source. Voir [Comment ce projet a été construit](#comment-ce-projet-a-été-construit).

---

## La Grande Idée : Des Sessions Parallèles Sans Crainte

Quand vous envoyez des tâches à Claude Code dans des fils Discord séparés, le bridge fait automatiquement trois choses :

1. **Injection d'avis de concurrence** — Le prompt système de chaque session inclut des instructions obligatoires : créez un git worktree, travaillez uniquement à l'intérieur, ne touchez jamais directement au répertoire de travail principal.

2. **Registre des sessions actives** — Chaque session en cours d'exécution connaît les autres. Si deux sessions sont sur le point de toucher au même dépôt, elles peuvent se coordonner plutôt que d'entrer en conflit.

3. **Canal de coordination** — Un canal Discord partagé où les sessions diffusent les événements de démarrage/fin. Claude et les humains peuvent voir d'un coup d'œil ce qui se passe dans tous les fils actifs.

```
Fil A (fonctionnalité) ──→  Claude Code (worktree-A)
Fil B (révision PR)    ──→  Claude Code (worktree-B)
Fil C (docs)           ──→  Claude Code (worktree-C)
           ↓ événements de cycle de vie
   #canal-coordination
   "A : démarrage du refactor d'authentification"
   "B : révision du PR #42"
   "C : mise à jour du README"
```

Sans race conditions. Sans travail perdu. Sans surprises au merge.

---

## Ce Que Vous Pouvez Faire

### Chat Interactif (Mobile / Bureau)

Utilisez Claude Code depuis n'importe où où Discord fonctionne — téléphone, tablette ou bureau. Chaque message crée ou continue un fil, mappé 1:1 à une session Claude Code persistante.

### Développement Parallèle

Ouvrez plusieurs fils simultanément. Chacun est une session Claude Code indépendante avec son propre contexte, répertoire de travail et git worktree. Schémas utiles :

- **Fonctionnalité + révision en parallèle** : Démarrez une fonctionnalité dans un fil pendant que Claude révise un PR dans un autre.
- **Plusieurs contributeurs** : Différents membres de l'équipe ont chacun leur fil ; les sessions restent informées les unes des autres via le canal de coordination.
- **Expérimentez en toute sécurité** : Essayez une approche dans le fil A tout en maintenant le fil B sur du code stable.

### Tâches Planifiées (SchedulerCog)

Enregistrez des tâches Claude Code périodiques depuis une conversation Discord ou via l'API REST — sans changements de code, sans redéploiements. Les tâches sont stockées dans SQLite et s'exécutent selon un calendrier configurable. Claude peut auto-enregistrer des tâches pendant une session en utilisant `POST /api/tasks`.

```
/skill name:goodmorning         → s'exécute immédiatement
Claude appelle POST /api/tasks → enregistre une tâche périodique
SchedulerCog (boucle toutes 30s) → déclenche les tâches dues automatiquement
```

### Automatisation CI/CD

Déclenchez des tâches Claude Code depuis GitHub Actions via des webhooks Discord. Claude s'exécute de manière autonome — lit le code, met à jour la documentation, crée des PRs, active l'auto-merge.

```
GitHub Actions → Discord Webhook → Bridge → Claude Code CLI
                                                  ↓
GitHub PR ←── git push ←── Claude Code ──────────┘
```

**Exemple concret :** À chaque push sur `main`, Claude analyse le diff, met à jour la documentation en anglais + japonais, crée un PR avec un résumé bilingue et active l'auto-merge. Zéro interaction humaine.

### Synchronisation de Sessions

Vous utilisez déjà Claude Code CLI directement ? Synchronisez vos sessions terminal existantes en fils Discord avec `/sync-sessions`. Remplit les messages de conversation récents pour que vous puissiez continuer une session CLI depuis votre téléphone sans perdre le contexte.

### Création Programmatique de Sessions

Créez de nouvelles sessions Claude Code depuis des scripts, GitHub Actions ou d'autres sessions Claude — sans interaction avec des messages Discord.

```bash
# Depuis une autre session Claude ou un script CI :
curl -X POST "$CCDB_API_URL/api/spawn" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Exécuter un scan de sécurité sur le dépôt", "thread_name": "Scan de Sécurité"}'
# Retourne immédiatement avec l'ID du fil ; Claude s'exécute en arrière-plan
```

Les sous-processus Claude reçoivent `DISCORD_THREAD_ID` comme variable d'environnement, donc une session en cours peut créer des sessions enfants pour paralléliser le travail.

### Reprise au Démarrage

Si le bot redémarre en cours de session, les sessions Claude interrompues reprennent automatiquement quand le bot revient en ligne. Les sessions sont marquées pour reprise de trois façons :

- **Automatique (redémarrage par mise à jour)** — `AutoUpgradeCog` prend un snapshot de toutes les sessions actives juste avant un redémarrage par mise à jour de package et les marque automatiquement.
- **Automatique (n'importe quel arrêt)** — `ClaudeChatCog.cog_unload()` marque toutes les sessions en cours quand le bot s'arrête par n'importe quel mécanisme (`systemctl stop`, `bot.close()`, SIGTERM, etc.).
- **Manuel** — N'importe quelle session peut appeler `POST /api/mark-resume` directement.

---

## Fonctionnalités

### Chat Interactif

#### 🔗 Bases de Session
- **Thread = Session** — Mappage 1:1 entre fil Discord et session Claude Code
- **Persistance de session** — Reprend les conversations entre messages via `--resume`
- **Sessions simultanées** — Plusieurs sessions parallèles avec limite configurable
- **Arrêt sans effacement** — `/stop` arrête une session en la préservant pour reprise
- **Interruption de session** — Envoyer un nouveau message à un fil actif envoie SIGINT à la session en cours et recommence avec la nouvelle instruction ; pas de `/stop` manuel nécessaire

#### 📡 Retour en Temps Réel
- **Statut en temps réel** — Réactions emoji : 🧠 réflexion, 🛠️ lecture de fichiers, 💻 édition, 🌐 recherche web
- **Texte en streaming** — Le texte intermédiaire de l'assistant apparaît pendant que Claude travaille
- **Embeds de résultats d'outils** — Résultats en direct avec temps écoulé augmentant toutes les 10s ; résultats d'une seule ligne affichés directement, résultats multi-lignes réduits derrière un bouton d'expansion
- **Pensée étendue** — Raisonnement affiché sous forme d'embeds avec spoiler (cliquer pour révéler)
- **Tableau de bord des fils** — Embed épinglé en direct montrant quels fils sont actifs vs. en attente ; le propriétaire est @mentionné quand une saisie est nécessaire

#### 🤝 Collaboration Humain-IA
- **Questions interactives** — `AskUserQuestion` s'affiche en Boutons Discord ou Menu de Sélection ; la session reprend avec votre réponse ; les boutons survivent aux redémarrages du bot
- **Plan Mode** — Quand Claude appelle `ExitPlanMode`, un embed Discord affiche le plan complet avec des boutons Approuver/Annuler ; Claude continue seulement après approbation ; annulation automatique après 5 minutes
- **Demandes de permission d'outil** — Quand Claude a besoin d'une permission pour exécuter un outil, Discord affiche des boutons Autoriser/Refuser avec le nom et l'entrée de l'outil ; refus automatique après 2 minutes
- **MCP Elicitation** — Les serveurs MCP peuvent demander une saisie utilisateur via Discord (mode formulaire : jusqu'à 5 champs Modal du schéma JSON ; mode URL : bouton URL + confirmation) ; délai de 5 minutes
- **Progression en direct de TodoWrite** — Quand Claude appelle `TodoWrite`, un seul embed Discord est publié et édité en place à chaque mise à jour ; affiche ✅ terminé, 🔄 actif (avec étiquette `activeForm`), ⬜ en attente

#### 📊 Observabilité
- **Utilisation de tokens** — Taux de succès du cache et nombre de tokens affichés dans l'embed de session terminée
- **Utilisation du contexte** — Pourcentage de la fenêtre de contexte (tokens d'entrée + cache, hors sortie) et capacité restante jusqu'à l'auto-compactage affichés dans l'embed de session terminée ; ⚠️ avertissement au-dessus de 83,5%
- **Détection de compactage** — Notifie dans le fil quand la compaction du contexte se produit (type de déclencheur + nombre de tokens avant compactage)
- **Notification de blocage** — Message dans le fil après 30 s sans activité (réflexion étendue ou compression de contexte) ; réinitialise automatiquement quand Claude reprend
- **Notifications de timeout** — Embed avec temps écoulé et guide de reprise en cas de timeout

#### 🔌 Entrée et Skills
- **Support des pièces jointes** — Fichiers texte ajoutés automatiquement au prompt (jusqu'à 5 × 50 Ko) ; images téléchargées et transmises via `--image` (jusqu'à 4 × 5 Mo)
- **Exécution de skills** — Commande `/skill` avec autocomplétion, arguments optionnels, reprise dans le fil
- **Hot reload** — Les nouveaux skills ajoutés à `~/.claude/skills/` sont détectés automatiquement (actualisation toutes les 60s, sans redémarrage)

### Concurrence et Coordination
- **Instructions de worktree auto-injectées** — Chaque session est invitée à utiliser `git worktree` avant de toucher à un fichier
- **Nettoyage automatique de worktree** — Les worktrees de session (`wt-{thread_id}`) sont supprimés automatiquement à la fin de session et au démarrage du bot ; les worktrees avec des modifications ne sont jamais supprimés automatiquement (invariant de sécurité)
- **Registre des sessions actives** — Registre en mémoire ; chaque session voit ce que font les autres
- **AI Lounge** — Canal «salle de repos» partagée ; contexte injecté via `--append-system-prompt` (éphémère, ne s'accumule jamais dans l'historique) pour que les longues sessions n'atteignent jamais «Prompt is too long» ; les sessions publient leurs intentions, lisent le statut des autres et vérifient avant les opérations destructives ; les humains le voient comme un fil d'activité en temps réel
- **Canal de coordination** — Canal partagé optionnel pour les diffusions de cycle de vie entre sessions
- **Scripts de coordination** — Claude peut appeler `coord_post.py` / `coord_read.py` depuis une session pour publier et lire des événements

### Tâches Planifiées
- **SchedulerCog** — Exécuteur de tâches périodiques avec support SQLite et une boucle maître de 30 secondes
- **Auto-enregistrement** — Claude enregistre des tâches via `POST /api/tasks` pendant une session de chat
- **Sans changements de code** — Ajoute, supprime ou modifie des tâches à l'exécution
- **Activer/désactiver** — Pause des tâches sans les supprimer (`PATCH /api/tasks/{id}`)

### Automatisation CI/CD
- **Déclencheurs webhook** — Déclenche des tâches Claude Code depuis GitHub Actions ou tout système CI/CD
- **Mise à jour automatique** — Met à jour automatiquement le bot quand des packages upstream sont publiés
- **Redémarrage avec drainage** — Attend que les sessions actives se terminent avant de redémarrer
- **Marquage automatique de reprise** — Les sessions actives sont automatiquement marquées pour reprise lors de tout arrêt (redémarrage par mise à jour via `AutoUpgradeCog`, ou tout autre arrêt via `ClaudeChatCog.cog_unload()`) ; elles reprennent où elles s'étaient arrêtées après le redémarrage du bot
- **Approbation de redémarrage** — Portail optionnel pour confirmer les mises à jour avant de les appliquer

### Gestion des Sessions
- **Synchronisation de sessions** — Importe les sessions CLI comme fils Discord (`/sync-sessions`)
- **Liste des sessions** — `/sessions` avec filtrage par origine (Discord / CLI / toutes) et fenêtre temporelle
- **Informations de reprise** — `/resume-info` affiche la commande CLI pour continuer la session actuelle dans un terminal
- **Reprise au démarrage** — Les sessions interrompues redémarrent automatiquement après tout redémarrage du bot ; `AutoUpgradeCog` (redémarrages par mise à jour) et `ClaudeChatCog.cog_unload()` (tous les autres arrêts) les marquent automatiquement, ou utilisez `POST /api/mark-resume` manuellement
- **Création programmatique** — `POST /api/spawn` crée un nouveau fil Discord + session Claude depuis n'importe quel script ou sous-processus Claude ; retourne un 201 non bloquant immédiatement après la création du fil
- **Injection d'ID de fil** — La variable d'environnement `DISCORD_THREAD_ID` est passée à chaque sous-processus Claude, permettant aux sessions de créer des sessions enfants via `$CCDB_API_URL/api/spawn`
- **Gestion des worktrees** — `/worktree-list` affiche tous les worktrees de session actifs avec leur statut propre/sale ; `/worktree-cleanup` supprime les worktrees propres orphelins (supporte la prévisualisation avec `dry_run`)

### Sécurité
- **Pas d'injection shell** — Uniquement `asyncio.create_subprocess_exec`, jamais `shell=True`
- **Validation des ID de session** — Regex strict avant de passer à `--resume`
- **Prévention d'injection de flags** — Séparateur `--` avant tous les prompts
- **Isolation des secrets** — Le token du bot est supprimé de l'environnement du sous-processus
- **Autorisation utilisateur** — `allowed_user_ids` restreint qui peut invoquer Claude

---

## Démarrage Rapide

### Prérequis

- Python 3.10+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installé et authentifié
- Token de bot Discord avec Message Content intent activé
- [uv](https://docs.astral.sh/uv/) (recommandé) ou pip

### Exécution autonome

```bash
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge

cp .env.example .env
# Éditez .env avec votre token de bot et ID de canal

uv run python -m claude_discord.main
```

### Installer comme paquet

Si vous avez déjà un bot discord.py en fonctionnement (Discord n'autorise qu'une connexion Gateway par token) :

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

`setup_bridge()` connecte tous les Cogs automatiquement. Les nouveaux Cogs ajoutés à ccdb sont inclus sans modifications du code consommateur.

Mettre à jour vers la dernière version :

```bash
uv lock --upgrade-package claude-code-discord-bridge && uv sync
```

---

## Configuration

| Variable | Description | Défaut |
|----------|-------------|--------|
| `DISCORD_BOT_TOKEN` | Votre token de bot Discord | (obligatoire) |
| `DISCORD_CHANNEL_ID` | ID du canal pour le chat Claude | (obligatoire) |
| `CLAUDE_COMMAND` | Chemin vers le Claude Code CLI | `claude` |
| `CLAUDE_MODEL` | Modèle à utiliser | `sonnet` |
| `CLAUDE_PERMISSION_MODE` | Mode de permission du CLI | `acceptEdits` |
| `CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS` | Ignorer toutes les vérifications de permissions (à utiliser avec précaution) | `false` |
| `CLAUDE_WORKING_DIR` | Répertoire de travail pour Claude | répertoire courant |
| `MAX_CONCURRENT_SESSIONS` | Nombre maximum de sessions parallèles | `3` |
| `SESSION_TIMEOUT_SECONDS` | Timeout d'inactivité de session | `300` |
| `DISCORD_OWNER_ID` | ID utilisateur à @mentionner quand Claude a besoin d'une saisie | (optionnel) |
| `COORDINATION_CHANNEL_ID` | ID du canal pour les diffusions d'événements entre sessions | (optionnel) |
| `CCDB_COORDINATION_CHANNEL_NAME` | Créer automatiquement un canal de coordination par nom | (optionnel) |
| `WORKTREE_BASE_DIR` | Répertoire de base pour scanner les worktrees de session (active le nettoyage automatique) | (optionnel) |

### Modes d'autorisation — Ce qui fonctionne en mode `-p`

Le CLI Claude Code s'exécute en **mode `-p` (non interactif)** lorsqu'il est utilisé via ccdb. Dans ce mode, le CLI **ne peut pas demander d'autorisation** — les outils nécessitant une approbation sont immédiatement rejetés. Il s'agit d'une [contrainte de conception du CLI](https://code.claude.com/docs/en/headless), pas d'une limitation de ccdb.

| Mode | Comportement en mode `-p` | Recommandation |
|------|----------------------|----------------|
| `default` | ❌ **Tous les outils rejetés** — inutilisable | Ne pas utiliser |
| `acceptEdits` | ⚠️ Edit/Write approuvés automatiquement, Bash rejeté (Claude utilise Write pour les opérations sur fichiers) | Option minimale viable |
| `bypassPermissions` | ✅ Tous les outils approuvés | Fonctionne, mais préférer l'option ci-dessous |
| **`CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS=true`** | ✅ **Tous les outils approuvés** | **Recommandé** — ccdb restreint déjà l'accès via `allowed_user_ids` |

**Notre recommandation :** Définissez `CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS=true`. Puisque ccdb contrôle qui peut interagir avec Claude via `allowed_user_ids`, les vérifications d'autorisation au niveau du CLI ajoutent des frictions sans bénéfice sécuritaire réel. Le «dangerously» dans le nom reflète l'avertissement général du CLI ; dans le contexte de ccdb où l'accès est déjà contrôlé, c'est le choix pratique.

Si vous préférez un contrôle plus fin, le support de `CLAUDE_ALLOWED_TOOLS` est prévu ([#217](https://github.com/ebibibi/claude-code-discord-bridge/issues/217)).

> **Pourquoi les boutons d'autorisation n'apparaissent-ils pas dans Discord ?** Le mode `-p` du CLI n'émet jamais d'événements `permission_request`, donc il n'y a rien à afficher pour ccdb. Les boutons `AskUserQuestion` que vous voyez (invites de sélection de Claude) sont un mécanisme différent qui fonctionne correctement. Voir [#210](https://github.com/ebibibi/claude-code-discord-bridge/issues/210) pour l'investigation complète.

---

## Configuration du Bot Discord

1. Créez une nouvelle application sur le [Portail Développeur Discord](https://discord.com/developers/applications)
2. Créez un bot et copiez le token
3. Activez **Message Content Intent** dans Privileged Gateway Intents
4. Invitez le bot avec ces permissions :
   - Send Messages
   - Create Public Threads
   - Send Messages in Threads
   - Add Reactions
   - Manage Messages (pour le nettoyage des réactions)
   - Read Message History

---

## GitHub + Automatisation avec Claude Code

### Exemple : Synchronisation Automatique de Documentation

À chaque push sur `main`, Claude Code :
1. Récupère les derniers changements et analyse le diff
2. Met à jour la documentation en anglais
3. Traduit en japonais (ou toute langue cible)
4. Crée un PR avec un résumé bilingue
5. Active l'auto-merge — fusionne automatiquement quand le CI passe

**GitHub Actions :**

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

**Configuration du bot :**

```python
from claude_discord import WebhookTriggerCog, WebhookTrigger, ClaudeRunner

runner = ClaudeRunner(command="claude", model="sonnet")

triggers = {
    "🔄 docs-sync": WebhookTrigger(
        prompt="Analysez les changements, mettez à jour les docs, créez un PR avec résumé bilingue, activez l'auto-merge.",
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

**Sécurité :** Les prompts sont définis côté serveur. Les webhooks sélectionnent uniquement quel déclencheur activer — pas d'injection arbitraire de prompts.

### Exemple : Auto-approbation des PRs du Propriétaire

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

## Tâches Planifiées

Enregistrez des tâches Claude Code périodiques à l'exécution — sans changements de code, sans redéploiements.

Depuis une session Discord, Claude peut enregistrer une tâche :

```bash
# Claude appelle cela depuis une session :
curl -X POST "$CCDB_API_URL/api/tasks" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Vérifier les dépendances obsolètes et ouvrir une issue si trouvées", "interval_seconds": 604800}'
```

Ou enregistrez depuis vos propres scripts :

```bash
curl -X POST http://localhost:8080/api/tasks \
  -H "Authorization: Bearer your-secret" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Scan de sécurité hebdomadaire", "interval_seconds": 604800}'
```

La boucle maître de 30 secondes détecte les tâches dues et crée des sessions Claude Code automatiquement.

---

## Mise à Jour Automatique

Mettez automatiquement à jour le bot quand une nouvelle version est publiée :

```python
from claude_discord import AutoUpgradeCog, UpgradeConfig

config = UpgradeConfig(
    package_name="claude-code-discord-bridge",
    trigger_prefix="🔄 bot-upgrade",
    working_dir="/home/user/my-bot",
    restart_command=["sudo", "systemctl", "restart", "my-bot.service"],
    restart_approval=True,  # Réagissez avec ✅ pour confirmer le redémarrage
)

await bot.add_cog(AutoUpgradeCog(bot, config))
```

Avant de redémarrer, `AutoUpgradeCog` :

1. **Prend un snapshot des sessions actives** — Collecte tous les fils avec des sessions Claude en cours (duck typing : tout Cog avec un dict `_active_runners` est découvert automatiquement).
2. **Draine** — Attend que les sessions actives se terminent naturellement.
3. **Marque pour reprise** — Sauvegarde les IDs de fils actifs dans la table des reprises en attente. Au prochain démarrage, ces sessions reprennent automatiquement avec un prompt « bot redémarré, veuillez continuer ».
4. **Redémarre** — Exécute la commande de redémarrage configurée.

Tout Cog avec une propriété `active_count` est découvert automatiquement et drainé :

```python
class MyCog(commands.Cog):
    @property
    def active_count(self) -> int:
        return len(self._running_tasks)
```

> **Couverture :** `AutoUpgradeCog` couvre les redémarrages déclenchés par mise à jour. Pour *tous les autres* arrêts (`systemctl stop`, `bot.close()`, SIGTERM), `ClaudeChatCog.cog_unload()` fournit un deuxième filet de sécurité automatique.

---

## API REST

API REST optionnelle pour les notifications et la gestion des tâches. Nécessite aiohttp :

```bash
uv add "claude-code-discord-bridge[api]"
```

### Endpoints

| Méthode | Chemin | Description |
|---------|--------|-------------|
| GET | `/api/health` | Vérification de l'état |
| POST | `/api/notify` | Envoyer une notification immédiate |
| POST | `/api/schedule` | Planifier une notification |
| GET | `/api/scheduled` | Lister les notifications en attente |
| DELETE | `/api/scheduled/{id}` | Annuler une notification |
| POST | `/api/tasks` | Enregistrer une tâche Claude Code planifiée |
| GET | `/api/tasks` | Lister les tâches enregistrées |
| DELETE | `/api/tasks/{id}` | Supprimer une tâche |
| PATCH | `/api/tasks/{id}` | Mettre à jour une tâche (activer/désactiver, changer le calendrier) |
| POST | `/api/spawn` | Créer un nouveau fil Discord et démarrer une session Claude Code (non bloquant) |
| POST | `/api/mark-resume` | Marquer un fil pour reprise automatique au prochain démarrage du bot |

```bash
# Envoyer une notification
curl -X POST http://localhost:8080/api/notify \
  -H "Authorization: Bearer your-secret" \
  -H "Content-Type: application/json" \
  -d '{"message": "Build réussi !", "title": "CI/CD"}'

# Enregistrer une tâche récurrente
curl -X POST http://localhost:8080/api/tasks \
  -H "Authorization: Bearer your-secret" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Résumé quotidien de standup", "interval_seconds": 86400}'
```

---

## Architecture

```
claude_discord/
  main.py                  # Point d'entrée autonome
  setup.py                 # setup_bridge() — câblage des Cogs en un appel
  bot.py                   # Classe Discord Bot
  concurrency.py           # Instructions de worktree + registre des sessions actives
  cogs/
    claude_chat.py         # Chat interactif (création de fils, gestion des messages)
    skill_command.py       # Commande slash /skill avec autocomplétion
    session_manage.py      # /sessions, /sync-sessions, /resume-info
    scheduler.py           # Exécuteur de tâches Claude Code périodiques
    webhook_trigger.py     # Webhook → tâche Claude Code (CI/CD)
    auto_upgrade.py        # Webhook → mise à jour de package + redémarrage avec drainage
    event_processor.py     # EventProcessor — machine à états pour événements stream-json
    run_config.py          # RunConfig dataclass — regroupe tous les paramètres d'exécution CLI
    _run_helper.py         # Couche d'orchestration fine
  claude/
    runner.py              # Gestionnaire de sous-processus Claude CLI
    parser.py              # Parseur d'événements stream-json
    types.py               # Définitions de types pour les messages SDK
  coordination/
    service.py             # Publie les événements de cycle de vie de session dans le canal partagé
  database/
    models.py              # Schéma SQLite
    repository.py          # CRUD des sessions
    task_repo.py           # CRUD des tâches planifiées
    ask_repo.py            # CRUD des AskUserQuestion en attente
    notification_repo.py   # CRUD des notifications planifiées
    resume_repo.py         # CRUD de reprise au démarrage
    settings_repo.py       # Paramètres par serveur
  discord_ui/
    status.py              # Gestionnaire de réactions emoji (avec debounce)
    chunker.py             # Découpage de messages avec connaissance des blocs et tableaux
    embeds.py              # Constructeurs d'embeds Discord
    ask_view.py            # Boutons/Menus de Sélection pour AskUserQuestion
    ask_handler.py         # collect_ask_answers() — UI + cycle de vie DB d'AskUserQuestion
    streaming_manager.py   # StreamingMessageManager — éditions de messages en place avec debounce
    tool_timer.py          # LiveToolTimer — compteur de temps écoulé pour outils longs
    thread_dashboard.py    # Embed épinglé en direct affichant les états de session
    plan_view.py           # Boutons Approuver/Annuler pour Plan Mode (ExitPlanMode)
    permission_view.py     # Boutons Autoriser/Refuser pour les demandes de permission d'outil
    elicitation_view.py    # Interface Discord pour MCP Elicitation (formulaire Modal ou bouton URL)
  session_sync.py          # Découverte et importation de sessions CLI
  worktree.py              # WorktreeManager — cycle de vie sécurisé de git worktree
  ext/
    api_server.py          # API REST (optionnel, nécessite aiohttp)
  utils/
    logger.py              # Configuration du logging
```

### Philosophie de Conception

- **Invocation CLI, pas API** — Invoque `claude -p --output-format stream-json`, donnant les fonctionnalités complètes de Claude Code (CLAUDE.md, skills, outils, mémoire) sans les réimplémenter
- **Concurrence d'abord** — Plusieurs sessions simultanées sont le cas attendu, pas un cas limite ; chaque session reçoit des instructions de worktree, le registre et le canal de coordination gèrent le reste
- **Discord comme colle** — Discord fournit UI, fils, réactions, webhooks et notifications persistantes ; pas de frontend personnalisé nécessaire
- **Framework, pas application** — Installez comme paquet, ajoutez des Cogs à votre bot existant, configurez via le code
- **Extensibilité sans code** — Ajoutez des tâches planifiées et des déclencheurs webhook sans toucher au code source
- **Sécurité par la simplicité** — ~3000 lignes de Python auditables ; seulement subprocess exec, pas d'expansion shell

---

## Tests

```bash
uv run pytest tests/ -v --cov=claude_discord
```

700+ tests couvrant le parseur, le découpage, le référentiel, le runner, le streaming, les déclencheurs webhook, la mise à jour automatique (incluant la commande `/upgrade`, l'invocation depuis un fil et le bouton d'approbation), l'API REST, l'UI AskUserQuestion, le tableau de bord des fils, les tâches planifiées, la synchronisation de sessions, AI Lounge, la reprise au démarrage, le changement de modèle, la détection de compactage, les embeds de progression TodoWrite, et l'analyse d'événements permission/elicitation/plan-mode.

---

## Comment Ce Projet A Été Construit

**L'intégralité de ce code base a été écrite par [Claude Code](https://docs.anthropic.com/en/docs/claude-code)**, l'agent de codage IA d'Anthropic. L'auteur humain ([@ebibibi](https://github.com/ebibibi)) a fourni les exigences et la direction en langage naturel, mais n'a pas lu ni édité manuellement le code source.

Cela signifie :

- **Tout le code a été généré par IA** — architecture, implémentation, tests, documentation
- **L'auteur humain ne peut pas garantir l'exactitude au niveau du code** — examinez le source si vous avez besoin d'assurance
- **Les rapports de bugs et les PRs sont les bienvenus** — Claude Code sera utilisé pour les traiter
- **C'est un exemple concret de logiciel open source écrit par une IA**

Le projet a démarré le 2026-02-18 et continue d'évoluer à travers des conversations itératives avec Claude Code.

---

## Exemple Concret

**[EbiBot](https://github.com/ebibibi/discord-bot)** — Un bot Discord personnel construit sur ce framework. Inclut la synchronisation automatique de documentation (anglais + japonais), les notifications push, le watchdog Todoist, les vérifications de santé planifiées et le CI/CD avec GitHub Actions. Utilisez-le comme référence pour construire votre propre bot.

---

## Inspiré par

- [OpenClaw](https://github.com/openclaw/openclaw) — Réactions emoji de statut, debounce de messages, découpage avec connaissance des blocs
- [claude-code-discord-bot](https://github.com/timoconnellaus/claude-code-discord-bot) — Approche d'invocation CLI + stream-json
- [claude-code-discord](https://github.com/zebbern/claude-code-discord) — Schémas de contrôle des permissions
- [claude-sandbox-bot](https://github.com/RhysSullivan/claude-sandbox-bot) — Modèle de fil par conversation

---

## Licence

MIT
