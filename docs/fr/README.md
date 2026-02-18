> **Note:** This is an auto-translated version of the original English documentation.
> If there are any discrepancies, the [English version](../../README.md) takes precedence.
> **Remarque :** Ceci est une version traduite automatiquement de la documentation originale en anglais.
> En cas de divergence, la [version anglaise](../../README.md) fait foi.

# claude-code-discord-bridge

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Connectez [Claude Code](https://docs.anthropic.com/en/docs/claude-code) à Discord et GitHub. Un framework qui fait le pont entre Claude Code CLI et Discord pour le **chat interactif, l'automatisation CI/CD et l'intégration des workflows GitHub**.

Claude Code est excellent dans le terminal — mais il peut faire bien plus. Ce pont vous permet d'**utiliser Claude Code dans votre workflow de développement GitHub** : synchroniser automatiquement la documentation, réviser et fusionner les PRs, et exécuter n'importe quelle tâche Claude Code déclenchée par GitHub Actions. Le tout avec Discord comme colle universelle.

**[English](../../README.md)** | **[日本語](../ja/README.md)** | **[简体中文](../zh-CN/README.md)** | **[한국어](../ko/README.md)** | **[Español](../es/README.md)** | **[Português](../pt-BR/README.md)**

> **Avertissement :** Ce projet n'est pas affilié, approuvé ou officiellement connecté à Anthropic. « Claude » et « Claude Code » sont des marques déposées d'Anthropic, PBC. Ceci est un outil open source indépendant qui s'interface avec Claude Code CLI.

> **Entièrement construit par Claude Code.** Ce projet a été conçu, implémenté, testé et documenté par Claude Code lui-même — l'agent de codage IA d'Anthropic. L'auteur humain n'a pas lu le code source. Voir [Comment ce projet a été construit](#comment-ce-projet-a-été-construit) pour les détails.

## Deux façons de l'utiliser

### 1. Chat interactif (Mobile / Bureau)

Utilisez Claude Code depuis votre téléphone ou n'importe quel appareil avec Discord. Chaque conversation devient un fil avec persistance complète de session.

```
Vous (Discord)  →  Bridge  →  Claude Code CLI
      ↑                               ↓
      ←──── sortie stream-json ───────←
```

### 2. Automatisation CI/CD (GitHub → Discord → Claude Code → GitHub)

Déclenchez des tâches Claude Code depuis GitHub Actions via des webhooks Discord. Claude Code fonctionne de manière autonome — lecture du code, mise à jour de la documentation, création de PRs et activation de l'auto-merge.

```
GitHub Actions  →  Discord Webhook  →  Bridge  →  Claude Code CLI
                                                         ↓
GitHub PR (auto-merge)  ←  git push  ←  Claude Code  ←──┘
```

**Exemple concret :** À chaque push sur main, Claude Code analyse automatiquement les changements, met à jour la documentation en anglais et japonais, crée une PR avec un résumé bilingue et active l'auto-merge. Aucune intervention humaine requise.

## Fonctionnalités

### Chat interactif
- **Thread = Session** — Chaque tâche a son propre fil Discord, mappé 1:1 à une session Claude Code
- **Statut en temps réel** — Les réactions emoji montrent ce que fait Claude (🧠 réflexion, 🛠️ lecture de fichiers, 💻 édition, 🌐 recherche web)
- **Texte en streaming** — Le texte intermédiaire apparaît pendant que Claude travaille
- **Affichage des résultats d'outils** — Les résultats sont affichés en embeds en temps réel
- **Pensée étendue** — Le raisonnement de Claude apparaît en embeds avec spoiler (clic pour révéler)
- **Persistance de session** — Continuez les conversations entre messages via `--resume`
- **Exécution de skills** — Exécutez les skills Claude Code (`/skill goodmorning`) via des commandes slash avec autocomplétion
- **Sessions concurrentes** — Exécutez plusieurs sessions en parallèle (limite configurable)

### Automatisation CI/CD
- **Déclencheurs webhook** — Déclenchez des tâches Claude Code depuis GitHub Actions ou tout système CI/CD
- **Mise à jour automatique** — Mettez à jour automatiquement le bot quand un paquet upstream est publié
- **REST API** — Notifications push vers Discord depuis des outils externes (optionnel, nécessite aiohttp)

### Sécurité
- **Pas d'injection shell** — Uniquement `asyncio.create_subprocess_exec`, jamais `shell=True`
- **Validation des ID de session** — Regex strict avant de passer à `--resume`
- **Prévention d'injection de flags** — Séparateur `--` avant tous les prompts
- **Isolation des secrets** — Token du bot et secrets supprimés de l'environnement du sous-processus
- **Autorisation utilisateur** — `allowed_user_ids` restreint qui peut invoquer Claude

## Démarrage rapide

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
from claude_discord import ClaudeChatCog, ClaudeRunner, SessionRepository
from claude_discord.database.models import init_db

# Initialiser
await init_db("data/sessions.db")
repo = SessionRepository("data/sessions.db")
runner = ClaudeRunner(command="claude", model="sonnet")

# Ajouter à votre bot existant
await bot.add_cog(ClaudeChatCog(bot, repo, runner))
```

Mettre à jour vers la dernière version :

```bash
uv lock --upgrade-package claude-code-discord-bridge && uv sync
```

## Tests

```bash
uv run pytest tests/ -v --cov=claude_discord
```

131 tests couvrant le parser, le chunker, le repository, le runner, le streaming, les déclencheurs webhook, l'auto-upgrade et l'API REST.

## Comment ce projet a été construit

**L'intégralité du code a été écrite par [Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — l'agent de codage IA d'Anthropic. L'auteur humain ([@ebibibi](https://github.com/ebibibi)) a fourni les exigences et la direction en langage naturel, mais n'a pas lu ou édité manuellement le code source.

Cela signifie :

- **Tout le code est généré par IA** — architecture, implémentation, tests, documentation
- **L'auteur humain ne peut pas garantir l'exactitude au niveau du code** — examinez le source si vous avez besoin d'assurance
- **Les rapports de bugs et les PRs sont les bienvenus** — Claude Code sera probablement utilisé pour les traiter
- **C'est un exemple concret de logiciel open source écrit par une IA** — utilisez-le comme référence de ce que Claude Code peut construire

Le projet a démarré le 2026-02-18 et continue d'évoluer à travers des conversations itératives avec Claude Code.

## Exemple concret

**[EbiBot](https://github.com/ebibibi/discord-bot)** — Un bot Discord personnel qui utilise claude-code-discord-bridge comme dépendance. Inclut la synchronisation automatique de documentation (anglais + japonais), les notifications push, le watchdog Todoist et l'intégration CI/CD avec GitHub Actions.

## Licence

MIT
