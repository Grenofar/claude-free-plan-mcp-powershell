# Claude PowerShell MCP

Un serveur MCP (Model Context Protocol) qui permet à **Claude Desktop** d'exécuter des commandes
PowerShell sur votre ordinateur Windows — avec une interface graphique simple (sans ligne de
commande) pour configurer les dossiers autorisés, les commandes bloquées/autorisées, l'installation
dans Claude, et le démarrage automatique avec Windows.

Tout est contenu dans **un seul fichier** : [`mcp_powershell_claude.py`](mcp_powershell_claude.py).
Une **version .exe** prête à l'emploi (compilée avec PyInstaller, le moteur utilisé par
auto-py-to-exe) est aussi disponible : [`ClaudePowerShellMCP-exe.zip`](ClaudePowerShellMCP-exe.zip).

## Installation la plus simple : version .exe (sans Python)

1. Téléchargez [`ClaudePowerShellMCP-exe.zip`](ClaudePowerShellMCP-exe.zip) et extrayez-le
   entièrement dans un dossier (ne déplacez pas seulement le `.exe`, il a besoin des fichiers
   du dossier `_internal` à côté de lui).
2. Double-cliquez sur `ClaudePowerShellMCP.exe`. La fenêtre de configuration s'ouvre.
3. Continuez à partir de l'étape 4 ci-dessous ("Dossiers autorisés").

## Installation (version Python, pour non-développeurs)

1. **Installer Python** (si ce n'est pas déjà fait) : https://www.python.org/downloads/
   Pendant l'installation, cochez **"Add python.exe to PATH"**.
2. **Télécharger** `mcp_powershell_claude.py` depuis ce dépôt et le placer où vous voulez
   (par exemple dans `Documents`).
3. **Double-cliquer** sur le fichier `mcp_powershell_claude.py`.
   - Au premier lancement, les dépendances nécessaires (`mcp`, `pystray`, `pillow`) s'installent
     automatiquement — patientez quelques secondes.
   - Une fenêtre de configuration s'ouvre.
4. Dans l'onglet **"Dossiers autorisés"**, ajoutez le ou les dossiers que Claude aura le droit
   d'utiliser (ex : `Documents`, `Bureau`, un dossier de projet...). **Sans dossier autorisé,
   aucune commande ne peut être exécutée.**
5. Dans l'onglet **"Commandes"**, laissez les règles de sécurité par défaut (liste noire) ou
   personnalisez-les.
6. Dans l'onglet **"Installation & démarrage"**, cliquez sur **"Installer / mettre à jour dans
   Claude Desktop"**. Cela ajoute automatiquement le serveur dans le fichier
   `claude_desktop_config.json` de Claude.
7. **Redémarrez Claude Desktop.** Claude peut maintenant utiliser l'outil `run_powershell`.

## Fonctionnalités

- **Interface graphique (Tkinter)** : aucune ligne de commande requise pour configurer.
- **Dossiers autorisés** : Claude ne peut exécuter des commandes que dans les dossiers que vous
  avez explicitement ajoutés (et leurs sous-dossiers).
- **Restriction des commandes** :
  - Mode *liste noire* (par défaut) : tout est autorisé sauf les motifs dangereux (suppression
    récursive forcée, formatage de disque, modification du registre, `shutdown`, etc.).
  - Mode *liste blanche* : seules les commandes correspondant à vos motifs sont autorisées.
- **Activer / désactiver** en un clic sans avoir à désinstaller quoi que ce soit.
- **Installation automatique** dans `claude_desktop_config.json` (et désinstallation en un clic).
- **Démarrage avec Windows** : une case à cocher ajoute/retire une entrée dans le registre
  (`HKCU\...\Run`) pour lancer l'icône dans la barre des tâches au démarrage de Windows.
- **Icône dans la barre des tâches (system tray)** : fermer la fenêtre la minimise dans la barre
  des tâches (le programme reste actif). Le menu de l'icône permet de :
  - **Ouvrir l'interface** (réafficher la fenêtre de configuration),
  - **Activer / désactiver** rapidement,
  - **Fermer le MCP** (quitter complètement le programme).

## Comment ça marche

Le même fichier `.py` a deux rôles selon la façon dont il est lancé :

- Lancé normalement (double-clic, ou `python mcp_powershell_claude.py`) → ouvre l'**interface de
  configuration**.
- Lancé par Claude Desktop avec l'argument `--mcp-server` → démarre en **serveur MCP** silencieux
  (communication via stdio), sans fenêtre.
- Lancé avec `--tray` (utilisé au démarrage de Windows) → démarre caché, uniquement dans la barre
  des tâches.

La configuration (dossiers autorisés, règles de commandes, activé/désactivé) est enregistrée dans :

```
%APPDATA%\ClaudePowerShellMCP\config.json
```

Le serveur MCP relit ce fichier à chaque appel, donc les changements faits dans l'interface
graphique s'appliquent immédiatement, sans avoir besoin de redémarrer Claude.

## Avertissement de sécurité

Ce programme donne à Claude la capacité d'exécuter de vraies commandes PowerShell sur votre
ordinateur. Les restrictions (dossiers, liste noire/blanche de commandes) réduisent les risques
mais **ne constituent pas un bac à sable (sandbox) de sécurité absolu** : une commande autorisée
dans un dossier autorisé peut toujours, par exemple, lire des fichiers présents dans ce dossier.
N'autorisez que des dossiers dont vous êtes sûr, et passez en revue les actions demandées par
Claude avant de les laisser s'exécuter si vous n'êtes pas certain de leur effet.

## Licence

Libre d'utilisation, modification et redistribution.
