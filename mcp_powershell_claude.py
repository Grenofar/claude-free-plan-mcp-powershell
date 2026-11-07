#!/usr/bin/env python3
"""
MCP PowerShell pour Claude - serveur + interface de configuration tout-en-un.

Fonctionne en script Python (`python mcp_powershell_claude.py`) ou compilé en .exe (PyInstaller) :

Double-clic (ou lancement sans argument)  -> ouvre l'interface graphique.
`--mcp-server`                            -> lancé automatiquement par Claude (serveur MCP, stdio).
`--tray`                                  -> démarre caché dans la barre des tâches (utilisé au démarrage de Windows).
"""

import json
import os
import re
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_NAME = "ClaudePowerShellMCP"
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
IS_FROZEN = getattr(sys, "frozen", False)
SCRIPT_PATH = sys.executable if IS_FROZEN else os.path.abspath(__file__)
STARTUP_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_VALUE_NAME = "ClaudePowerShellMCP"


def launch_command(*extra_args):
    """Commande à utiliser pour relancer ce programme (exe autonome ou script .py)."""
    if IS_FROZEN:
        return [sys.executable, *extra_args]
    return [sys.executable, SCRIPT_PATH, *extra_args]

DEFAULT_BLOCKED_PATTERNS = [
    r"Remove-Item.*-Recurse.*-Force",
    r"\brm\s+-rf\b",
    r"Format-Volume",
    r"\bformat\s+[a-zA-Z]:",
    r"\bdiskpart\b",
    r"Stop-Computer",
    r"Restart-Computer",
    r"\bshutdown\b",
    r"del\s+/s\s+/q",
    r"(HKLM|HKEY_LOCAL_MACHINE)",
    r"\breg\s+(add|delete)\b",
    r"\bnet\s+user\b",
    r"\bInvoke-Expression\b",
    r"\bIEX\b",
    r"-EncodedCommand",
    r"vssadmin",
    r"bcdedit",
    r"Set-ExecutionPolicy",
]

DEFAULT_CONFIG = {
    "enabled": True,
    "allowed_folders": [],
    "command_mode": "blacklist",  # "blacklist" ou "whitelist"
    "blocked_patterns": DEFAULT_BLOCKED_PATTERNS,
    "allowed_patterns": [],
    "timeout_seconds": 30,
    "start_with_windows": False,
}


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
        cfg.update(saved)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return cfg


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------
# Dépendances optionnelles (installées à la volée, pas besoin de setup manuel)
# --------------------------------------------------------------------------

def ensure_package(import_name, pip_name=None):
    pip_name = pip_name or import_name
    try:
        return __import__(import_name)
    except ImportError:
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--user", "--quiet", pip_name],
                check=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            return __import__(import_name)
        except Exception:
            return None


# --------------------------------------------------------------------------
# Validation des commandes / dossiers (utilisé par le serveur MCP)
# --------------------------------------------------------------------------

def _is_inside(path, folder):
    path = os.path.normcase(os.path.abspath(path))
    folder = os.path.normcase(os.path.abspath(folder))
    return path == folder or path.startswith(folder + os.sep)


def validate_request(cfg, command, working_directory):
    folders = cfg.get("allowed_folders") or []
    if not folders:
        return False, "Aucun dossier autorisé n'est configuré. Ouvrez l'application de configuration pour en ajouter.", None

    wd = os.path.abspath(working_directory) if working_directory else os.path.abspath(folders[0])

    if not any(_is_inside(wd, f) for f in folders):
        return False, f"Le dossier '{wd}' n'est pas dans la liste des dossiers autorisés.", None
    if not os.path.isdir(wd):
        return False, f"Le dossier '{wd}' n'existe pas.", None

    mode = cfg.get("command_mode", "blacklist")
    if mode == "blacklist":
        for pattern in cfg.get("blocked_patterns") or []:
            try:
                if pattern and re.search(pattern, command, re.IGNORECASE):
                    return False, f"Commande bloquée par la règle de sécurité : {pattern}", None
            except re.error:
                continue
    else:
        patterns = [p for p in (cfg.get("allowed_patterns") or []) if p]
        if not patterns or not any(re.search(p, command, re.IGNORECASE) for p in patterns):
            return False, "Cette commande n'est pas dans la liste blanche autorisée.", None

    return True, "ok", wd


# --------------------------------------------------------------------------
# Serveur MCP (lancé par Claude via le fichier de config JSON)
# --------------------------------------------------------------------------

def run_mcp_server():
    mcp_module = ensure_package("mcp")
    if mcp_module is None:
        print(
            "Erreur: le module Python 'mcp' est introuvable et n'a pas pu être installé automatiquement.\n"
            "Lancez manuellement: pip install mcp",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        from mcp.server.fastmcp import FastMCP  # mcp 1.x
    except ModuleNotFoundError:
        from mcp.server.mcpserver import MCPServer as FastMCP  # mcp 2.x (FastMCP renamed)

    app = FastMCP("PowerShell Local")

    @app.tool()
    def run_powershell(command: str, working_directory: str = "") -> str:
        """Exécute une commande PowerShell sur l'ordinateur de l'utilisateur, uniquement dans les dossiers
        et selon les règles de commandes autorisés par l'utilisateur dans l'application de configuration."""
        cfg = load_config()
        if not cfg.get("enabled", True):
            return "Erreur: l'exécution PowerShell est désactivée dans l'application de configuration (ClaudePowerShellMCP)."

        ok, message, cwd = validate_request(cfg, command, working_directory)
        if not ok:
            return f"Erreur: {message}"

        try:
            proc = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=cfg.get("timeout_seconds", 30),
            )
        except subprocess.TimeoutExpired:
            return "Erreur: délai d'exécution dépassé."
        except Exception as exc:
            return f"Erreur d'exécution: {exc}"

        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        parts = []
        if out:
            parts.append(out)
        if err:
            parts.append("[stderr]\n" + err)
        parts.append(f"[code de sortie: {proc.returncode}]")
        return "\n".join(parts)

    @app.tool()
    def list_allowed_folders() -> str:
        """Liste les dossiers que cet outil est autorisé à parcourir ou modifier."""
        cfg = load_config()
        folders = cfg.get("allowed_folders") or []
        if not folders:
            return "Aucun dossier autorisé n'est configuré. Ouvrez l'application ClaudePowerShellMCP pour en ajouter."
        return "\n".join(folders)

    app.run()


# --------------------------------------------------------------------------
# Intégration Claude Desktop (écrit dans claude_desktop_config.json)
# --------------------------------------------------------------------------

def find_claude_config_path(ask_if_missing=True):
    appdata = os.environ.get("APPDATA", "")
    candidate = os.path.join(appdata, "Claude", "claude_desktop_config.json")
    if os.path.isdir(os.path.dirname(candidate)):
        return candidate
    if os.path.exists(candidate):
        return candidate
    if ask_if_missing:
        messagebox.showinfo(
            "Claude Desktop introuvable",
            "Le dossier de configuration de Claude Desktop n'a pas été trouvé automatiquement.\n"
            "Sélectionnez où se trouve (ou doit être créé) le fichier claude_desktop_config.json.",
        )
        path = filedialog.asksaveasfilename(
            title="Emplacement de claude_desktop_config.json",
            initialfile="claude_desktop_config.json",
            defaultextension=".json",
        )
        return path or None
    return None


def install_to_claude(server_name="powershell-local"):
    path = find_claude_config_path()
    if not path:
        return None

    data = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            data = {}

    cmd = launch_command("--mcp-server")
    data.setdefault("mcpServers", {})
    data["mcpServers"][server_name] = {
        "command": cmd[0],
        "args": cmd[1:],
    }

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def uninstall_from_claude(server_name="powershell-local"):
    path = find_claude_config_path(ask_if_missing=False)
    if not path or not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False

    removed = False
    if "mcpServers" in data and server_name in data["mcpServers"]:
        del data["mcpServers"][server_name]
        removed = True

    if removed:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    return removed


def is_installed_in_claude(server_name="powershell-local"):
    path = find_claude_config_path(ask_if_missing=False)
    if not path or not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return server_name in data.get("mcpServers", {})
    except (json.JSONDecodeError, OSError):
        return False


# --------------------------------------------------------------------------
# Démarrage avec Windows (clé de registre HKCU\...\Run)
# --------------------------------------------------------------------------

def set_startup(enabled):
    if os.name != "nt":
        return
    import winreg

    if IS_FROZEN:
        cmd = [sys.executable, "--tray"]
    else:
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        cmd = [pythonw if os.path.exists(pythonw) else sys.executable, SCRIPT_PATH, "--tray"]
    command = " ".join(f'"{part}"' for part in cmd)

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, STARTUP_VALUE_NAME, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, STARTUP_VALUE_NAME)
            except FileNotFoundError:
                pass


def is_startup_enabled():
    if os.name != "nt":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, STARTUP_VALUE_NAME)
            return True
    except FileNotFoundError:
        return False


# --------------------------------------------------------------------------
# Icône de la barre des tâches (pystray, optionnel)
# --------------------------------------------------------------------------

def build_tray_icon(app):
    pystray = ensure_package("pystray")
    pil_image = ensure_package("PIL.Image", "Pillow")
    if pystray is None or pil_image is None:
        return None

    from PIL import Image, ImageDraw
    import pystray

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((2, 2, size - 2, size - 2), fill=(70, 110, 230, 255))
    draw.text((size // 2 - 8, size // 2 - 14), "PS", fill=(255, 255, 255, 255))

    def on_open(icon, item):
        app.root.after(0, app.show_window)

    def on_toggle(icon, item):
        app.root.after(0, app.toggle_enabled_from_tray)

    def on_quit(icon, item):
        app.root.after(0, app.quit_app)

    menu = pystray.Menu(
        pystray.MenuItem("Ouvrir l'interface", on_open, default=True),
        pystray.MenuItem("Activer / désactiver", on_toggle),
        pystray.MenuItem("Fermer le MCP (quitter)", on_quit),
    )
    icon = pystray.Icon(APP_NAME, img, "Claude PowerShell MCP", menu)
    return icon


# --------------------------------------------------------------------------
# Interface graphique
# --------------------------------------------------------------------------

class App:
    def __init__(self, start_hidden=False):
        self.cfg = load_config()
        self.tray_icon = None
        self.tray_thread = None

        self.root = tk.Tk()
        self.root.title("Claude PowerShell MCP")
        self.root.geometry("640x520")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._build_ui()
        self._load_into_ui()
        self._start_tray()

        if start_hidden:
            self.root.after(100, self.root.withdraw)

    # ---- UI construction ----

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")

        self.enabled_var = tk.BooleanVar()
        ttk.Checkbutton(
            top, text="Activer l'exécution PowerShell pour Claude", variable=self.enabled_var
        ).pack(side="left")

        self.status_label = ttk.Label(top, text="")
        self.status_label.pack(side="right")

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=10, pady=5)

        self.tab_folders = ttk.Frame(notebook, padding=10)
        self.tab_commands = ttk.Frame(notebook, padding=10)
        self.tab_install = ttk.Frame(notebook, padding=10)
        notebook.add(self.tab_folders, text="Dossiers autorisés")
        notebook.add(self.tab_commands, text="Commandes")
        notebook.add(self.tab_install, text="Installation && démarrage")

        self._build_tab_folders()
        self._build_tab_commands()
        self._build_tab_install()

        bottom = ttk.Frame(self.root, padding=10)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Enregistrer", command=self.save).pack(side="right")
        ttk.Label(bottom, text=f"Fichier de configuration : {CONFIG_PATH}", foreground="gray").pack(side="left")

    def _build_tab_folders(self):
        ttk.Label(
            self.tab_folders,
            text="Claude ne pourra exécuter des commandes PowerShell que dans ces dossiers (et leurs sous-dossiers).",
            wraplength=580,
        ).pack(anchor="w", pady=(0, 10))

        frame = ttk.Frame(self.tab_folders)
        frame.pack(fill="both", expand=True)
        self.folders_list = tk.Listbox(frame, height=12)
        self.folders_list.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(frame, command=self.folders_list.yview)
        scroll.pack(side="left", fill="y")
        self.folders_list.config(yscrollcommand=scroll.set)

        btns = ttk.Frame(self.tab_folders)
        btns.pack(fill="x", pady=8)
        ttk.Button(btns, text="Ajouter un dossier...", command=self.add_folder).pack(side="left")
        ttk.Button(btns, text="Supprimer la sélection", command=self.remove_folder).pack(side="left", padx=6)

    def _build_tab_commands(self):
        ttk.Label(
            self.tab_commands,
            text="Choisissez comment limiter les commandes PowerShell que Claude peut exécuter.",
            wraplength=580,
        ).pack(anchor="w", pady=(0, 10))

        self.command_mode_var = tk.StringVar(value="blacklist")
        mode_frame = ttk.Frame(self.tab_commands)
        mode_frame.pack(fill="x")
        ttk.Radiobutton(
            mode_frame, text="Tout autoriser sauf ces règles (liste noire)",
            variable=self.command_mode_var, value="blacklist", command=self._refresh_patterns_list,
        ).pack(anchor="w")
        ttk.Radiobutton(
            mode_frame, text="N'autoriser que ces règles (liste blanche)",
            variable=self.command_mode_var, value="whitelist", command=self._refresh_patterns_list,
        ).pack(anchor="w")

        frame = ttk.Frame(self.tab_commands)
        frame.pack(fill="both", expand=True, pady=8)
        self.patterns_list = tk.Listbox(frame, height=10)
        self.patterns_list.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(frame, command=self.patterns_list.yview)
        scroll.pack(side="left", fill="y")
        self.patterns_list.config(yscrollcommand=scroll.set)

        entry_frame = ttk.Frame(self.tab_commands)
        entry_frame.pack(fill="x")
        self.pattern_entry = ttk.Entry(entry_frame)
        self.pattern_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(entry_frame, text="Ajouter", command=self.add_pattern).pack(side="left", padx=6)
        ttk.Button(entry_frame, text="Supprimer la sélection", command=self.remove_pattern).pack(side="left")

        ttk.Button(
            self.tab_commands, text="Restaurer les règles de sécurité par défaut",
            command=self.restore_default_patterns,
        ).pack(anchor="w", pady=8)

    def _build_tab_install(self):
        ttk.Label(
            self.tab_install,
            text="Script utilisé par Claude :",
        ).pack(anchor="w")
        ttk.Label(self.tab_install, text=SCRIPT_PATH, foreground="gray", wraplength=580).pack(anchor="w", pady=(0, 15))

        ttk.Button(
            self.tab_install, text="Installer / mettre à jour dans Claude Desktop",
            command=self.do_install,
        ).pack(anchor="w")
        ttk.Button(
            self.tab_install, text="Retirer de Claude Desktop",
            command=self.do_uninstall,
        ).pack(anchor="w", pady=(6, 0))

        self.install_status_label = ttk.Label(self.tab_install, text="", foreground="gray")
        self.install_status_label.pack(anchor="w", pady=(6, 20))

        ttk.Separator(self.tab_install).pack(fill="x", pady=10)

        self.startup_var = tk.BooleanVar()
        ttk.Checkbutton(
            self.tab_install,
            text="Démarrer automatiquement avec Windows (icône dans la barre des tâches)",
            variable=self.startup_var,
            command=self.toggle_startup,
        ).pack(anchor="w")

        ttk.Label(
            self.tab_install,
            text="Redémarrez Claude Desktop après chaque installation ou modification pour que les changements soient pris en compte.",
            foreground="gray", wraplength=580,
        ).pack(anchor="w", pady=(15, 0))

    # ---- data <-> UI ----

    def _load_into_ui(self):
        self.enabled_var.set(self.cfg.get("enabled", True))
        self.folders_list.delete(0, "end")
        for f in self.cfg.get("allowed_folders", []):
            self.folders_list.insert("end", f)
        self.command_mode_var.set(self.cfg.get("command_mode", "blacklist"))
        self._refresh_patterns_list()
        self.startup_var.set(is_startup_enabled())
        self._refresh_install_status()

    def _refresh_patterns_list(self):
        self.patterns_list.delete(0, "end")
        key = "blocked_patterns" if self.command_mode_var.get() == "blacklist" else "allowed_patterns"
        for p in self.cfg.get(key, []):
            self.patterns_list.insert("end", p)

    def _refresh_install_status(self):
        installed = is_installed_in_claude()
        self.install_status_label.config(
            text="Statut : installé dans Claude Desktop ✔" if installed else "Statut : non installé dans Claude Desktop"
        )

    def _collect_from_ui(self):
        self.cfg["enabled"] = self.enabled_var.get()
        self.cfg["allowed_folders"] = list(self.folders_list.get(0, "end"))
        mode = self.command_mode_var.get()
        self.cfg["command_mode"] = mode
        patterns = list(self.patterns_list.get(0, "end"))
        if mode == "blacklist":
            self.cfg["blocked_patterns"] = patterns
        else:
            self.cfg["allowed_patterns"] = patterns

    # ---- actions ----

    def add_folder(self):
        path = filedialog.askdirectory(title="Choisir un dossier autorisé")
        if path:
            self.folders_list.insert("end", path)

    def remove_folder(self):
        for idx in reversed(self.folders_list.curselection()):
            self.folders_list.delete(idx)

    def add_pattern(self):
        text = self.pattern_entry.get().strip()
        if text:
            self.patterns_list.insert("end", text)
            self.pattern_entry.delete(0, "end")

    def remove_pattern(self):
        for idx in reversed(self.patterns_list.curselection()):
            self.patterns_list.delete(idx)

    def restore_default_patterns(self):
        if self.command_mode_var.get() != "blacklist":
            messagebox.showinfo("Info", "Les règles par défaut sont des règles de liste noire. Passez en mode liste noire pour les restaurer.")
            return
        self.patterns_list.delete(0, "end")
        for p in DEFAULT_BLOCKED_PATTERNS:
            self.patterns_list.insert("end", p)

    def save(self):
        self._collect_from_ui()
        save_config(self.cfg)
        self.status_label.config(text="Enregistré ✔")
        self.root.after(2000, lambda: self.status_label.config(text=""))

    def do_install(self):
        self.save()
        path = install_to_claude()
        if path:
            messagebox.showinfo("Installation", f"Serveur ajouté dans :\n{path}\n\nRedémarrez Claude Desktop.")
        self._refresh_install_status()

    def do_uninstall(self):
        removed = uninstall_from_claude()
        if removed:
            messagebox.showinfo("Installation", "Le serveur a été retiré de Claude Desktop.\nRedémarrez Claude Desktop.")
        else:
            messagebox.showinfo("Installation", "Aucune installation trouvée à retirer.")
        self._refresh_install_status()

    def toggle_startup(self):
        try:
            set_startup(self.startup_var.get())
        except Exception as exc:
            messagebox.showerror("Erreur", f"Impossible de modifier le démarrage automatique : {exc}")
            self.startup_var.set(is_startup_enabled())

    # ---- fenêtre / tray ----

    def _start_tray(self):
        icon = build_tray_icon(self)
        if icon is None:
            return
        self.tray_icon = icon
        self.tray_thread = threading.Thread(target=icon.run, daemon=True)
        self.tray_thread.start()

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def toggle_enabled_from_tray(self):
        self.enabled_var.set(not self.enabled_var.get())
        self.save()

    def on_close(self):
        if self.tray_icon is not None:
            self.root.withdraw()
        else:
            self.quit_app()

    def quit_app(self):
        self.save()
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.root.destroy()
        sys.exit(0)

    def run(self):
        self.root.mainloop()


# --------------------------------------------------------------------------
# Point d'entrée
# --------------------------------------------------------------------------

def main():
    if "--mcp-server" in sys.argv:
        run_mcp_server()
        return
    if "--tray" in sys.argv:
        App(start_hidden=True).run()
        return
    App(start_hidden=False).run()


if __name__ == "__main__":
    main()
