"""Dead Island 2 backend of the mod launcher (UI from the Mod Launcher Kit, see ui/).

How the mod works (nothing in the game's own files changes):
  * UE4SS (patched for DI2's engine, see payload/) + the DI2ZombieModels mod are copied next to the
    game's exe. The mod loads di2swap.dll (tools/di2swap), which does the model swap from inside the
    game, reading swaps.txt; the Lua part repairs the rare zombies that still spawn as mannequins.
Apply writes the choices (one model drawn per enemy when several are assigned) into the mod folder;
Apply and launch also starts the game. Restore removes UE4SS and the mod from the game folder.
This launcher never touches the running game.
"""
import glob
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import threading
import traceback

import webview

from catalog import ACTS, TABS, Catalog
from gamepaths import STEAM_APP_ID, game_dir, store_of

VERSION = "0.9.0"
TITLE = f"Dead Island 2 / Model Swap  v{VERSION}"
# SHA-256 of the game exes this version was tested with (the mod may still work on others)
TESTED_GAME_EXES = {
    "ED672DCD9CA379B3E8E2DDB03326968134A07D5BD2DD55FBA9E49087C8020CE2": "Epic, update of 2026-09-30",
}
LAUNCH_URL = {
    "epic": ("com.epicgames.launcher://apps/236c74b4cd2e4e3099cbe2ebdc9686fd%3A75a5bee8052f4e2498094b2faaea8c11"
             "%3ACrow?action=launch&silent=true"),
    "steam": f"steam://rungameid/{STEAM_APP_ID}",
}
GAME_EXE = "DeadIsland-Win64-Shipping.exe"
# installed build: everything next to the exe in <game>\ModLauncher; development: %LOCALAPPDATA%
if getattr(sys, "frozen", False):
    APPDIR = os.path.dirname(sys.executable)
else:
    APPDIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "DI2ModLauncher")
CONFIG_FILE = os.path.join(APPDIR, "config.json")
OPTIONS_FILE = os.path.join(APPDIR, "options.json")
# on/off switches shown in the launcher's bottom bar: key -> (label, default)
OPTIONS = {"hide_veins": ("Hide pulsing veins", True)}
MOD_DIR = os.path.join("Mods", "DI2ZombieModels")
OLD_MOD_DIRS = (os.path.join("Mods", "DI2Corridrici"),)   # names used by earlier builds
# files and folders the mod adds next to the game's exe (Restore removes exactly these)
PAYLOAD_FILES = ("dwmapi.dll", "UE4SS.dll", "UE4SS-settings.ini", "VTableLayout.ini", "di2swap.dll")
PAYLOAD_DIRS = ("Mods",)
UE4SS_LEFTOVERS = ("UE4SS.log", "UE4SS.prev.log", "crash_*.dmp", "*.cache", "swaps.txt", "di2swap.log")
# models used when the launcher is opened for the first time with the mod already installed
LEGACY_DEFAULT = {"walker": "SK_RunnerFemSwim05", "shambler": "SK_RunnerFemSport02",
                  "runner": "SK_RunnerFemSewerCas03", "insect": "SK_RunnerFemCas09"}
NO_WINDOW = 0x08000000


def res_dir(*parts):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def game_running():
    out = subprocess.run(["tasklist"], capture_output=True, text=True, creationflags=NO_WINDOW).stdout
    return GAME_EXE.lower() in out.lower()


def lua_list(names):
    return "{ " + ", ".join(json.dumps(n) for n in names) + " }"


def object_path(pkg):
    """/Game/X/SK_A -> /Game/X/SK_A.SK_A (the name the game's soft pointers use)"""
    return f"{pkg}.{pkg.rsplit('/', 1)[1]}"


class Api:
    def __init__(self):
        os.makedirs(APPDIR, exist_ok=True)
        self._cat = Catalog(res_dir("data"))
        game = game_dir()
        if not game:
            raise SystemExit("Dead Island 2 not found")
        self._bin = os.path.join(game, "DeadIsland", "Binaries", "Win64")
        self._launch_url = LAUNCH_URL[store_of(game)]
        self._models = self._cat.model_list()
        self._model_keys = {k for k, *_ in self._models}
        self._assign = self._load_config()
        self._options = self._load_options()
        self._window = None
        self._busy = False

    # ---------- state ----------
    def _installed(self):
        return (os.path.exists(os.path.join(self._bin, "UE4SS.dll"))
                and any(os.path.isdir(os.path.join(self._bin, d)) for d in (MOD_DIR,) + OLD_MOD_DIRS))

    def _game_tested(self):
        """True if the game exe is one this version was tested with (hash computed once)."""
        if not hasattr(self, "_tested"):
            try:
                h = hashlib.sha256()
                with open(os.path.join(self._bin, GAME_EXE), "rb") as f:
                    for block in iter(lambda: f.read(1 << 20), b""):
                        h.update(block)
                self._tested = h.hexdigest().upper() in TESTED_GAME_EXES
            except OSError:
                self._tested = True   # unreadable: do not warn
        return self._tested

    def _load_config(self):
        keys = list(self._cat.enemies)
        try:
            data = json.load(open(CONFIG_FILE, encoding="utf-8"))
            out = {}
            for e in keys:
                # older configs had one entry per theme ("walker:Filmset"): merge them into the archetype
                ms = data.get(e) or [m for k, v in data.items() if k.startswith(e + ":") for m in v]
                out[e] = list(dict.fromkeys(m for m in ms if m in self._model_keys))
            return out
        except (OSError, ValueError):
            pass
        if not self._installed():  # original game: every enemy shows its original model
            return {e: [] for e in keys}
        return {e: [LEGACY_DEFAULT[self._cat.enemies[e]["arch"]]] for e in keys}

    def _save_config(self):
        json.dump(self._assign, open(CONFIG_FILE, "w", encoding="utf-8"), indent=1)

    def _load_options(self):
        try:
            data = json.load(open(OPTIONS_FILE, encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        return {k: bool(data.get(k, default)) for k, (_label, default) in OPTIONS.items()}

    # ---------- called from the UI ----------
    def get_state(self):
        installed = self._installed()
        return {
            "title": "Model Swap",   # big heading (the window title bar shows TITLE)
            "installed": installed,
            "can_uninstall": bool(getattr(sys, "frozen", False)),
            "categories": [[t, keys] for t, keys in self._cat.categories()],
            "acts": [list(a) for a in ACTS],
            "no_campaign": "Other",
            "enemies": {e: {"name": self._cat.enemy_name(e), "acts": self._cat.enemy_acts(e)} for e in self._cat.enemies},
            "tabs": list(TABS),
            "models": [{"key": k, "name": n, "tab": t, "group": g} for k, n, t, g in self._models],
            "modelNames": {k: self._cat.chip_name(k) for k, *_ in self._models},
            "assign": self._assign,
            "options": [{"key": k, "label": label, "value": self._options[k]} for k, (label, _d) in OPTIONS.items()],
            "message": (("" if self._game_tested() else
                         "Warning: this game version was not tested with the mod (the game was probably "
                         "updated). If the game crashes, use \"Restore original game\".  ") +
                        ("Mod installed. Changes apply the next time the game starts." if installed else
                         "Mod not installed: the first Apply copies UE4SS and the mod next to the game.")),
        }

    def set_option(self, key, value):
        if key in OPTIONS:
            self._options[key] = bool(value)
            json.dump(self._options, open(OPTIONS_FILE, "w", encoding="utf-8"), indent=1)
            self._js("ui.status", "Option saved: it applies with the next Apply.")

    def save_assign(self, assign):
        self._assign = {e: [m for m in assign.get(e, []) if m in self._model_keys] for e in self._cat.enemies}
        self._save_config()

    def apply(self, assign, launch):
        self.save_assign(assign)
        chosen = {e: list(ms) for e, ms in self._assign.items()}  # several models = mixed in the game
        # no model and no option in use = the original game, without installing anything
        nothing = not any(chosen.values()) and not self._options["hide_veins"]

        def work(log, prog):
            if nothing:
                if self._installed():
                    log("No model chosen: removing the mod...")
                    self._remove_payload(prog)
                return
            if not self._installed():
                log("Installing UE4SS and the mod next to the game...")
                self._copy_payload(prog)
            else:
                self._update_mod_files()
            self._write_mod_config(chosen)
            self._write_swaps(chosen)
            prog(1)

        def done():
            msg = "Original game, no mod." if nothing else "Ready."
            if launch:
                os.startfile(self._launch_url)
                msg = "Launching Dead Island 2..."
            self._js("ui.status", msg)

        self._run(work, done)

    def restore(self):
        def done():
            self._assign = {e: [] for e in self._cat.enemies}
            self._save_config()
            self._js("ui.status", "Original game restored.")
        self._run(lambda log, prog: self._remove_payload(prog), done)

    def uninstall(self):
        def work(log, prog):
            if self._installed():
                log("Restoring the original game...")
                self._remove_payload(prog)

        def done():
            self._uninstall_launcher_files()
            self._window.destroy()
        self._run(work, done)

    # ---------- game folder ----------
    def _copy_payload(self, prog):
        src = res_dir("payload")
        items = list(PAYLOAD_FILES) + list(PAYLOAD_DIRS)
        for i, name in enumerate(items):
            s, d = os.path.join(src, name), os.path.join(self._bin, name)
            if os.path.isdir(s):
                shutil.copytree(s, d, dirs_exist_ok=True)
            else:
                shutil.copy2(s, d)
            prog((i + 1) / (len(items) + 1))

    def _update_mod_files(self):
        """Bring UE4SS and the mod in line with the ones bundled in this launcher. The Mods folder is
        entirely ours: it is replaced, which also removes leftovers of earlier builds."""
        src = res_dir("payload")
        for name in PAYLOAD_FILES:
            shutil.copy2(os.path.join(src, name), os.path.join(self._bin, name))
        mods = os.path.join(self._bin, "Mods")
        shutil.rmtree(mods, ignore_errors=True)
        shutil.copytree(os.path.join(src, "Mods"), mods)

    def _remove_payload(self, prog):
        targets = [os.path.join(self._bin, n) for n in PAYLOAD_FILES + PAYLOAD_DIRS]
        for pat in UE4SS_LEFTOVERS:
            targets += glob.glob(os.path.join(self._bin, pat))
        for i, t in enumerate(targets):
            if os.path.isdir(t):
                shutil.rmtree(t, ignore_errors=True)
            elif os.path.exists(t):
                os.remove(t)
            prog((i + 1) / len(targets))

    def _write_swaps(self, chosen):
        """swaps.txt for di2swap.dll: every variant to change, its mesh and the mesh to use."""
        s = self._cat.swaps(chosen, shuffle=random.shuffle)
        lines = [f"base {s['base_count']}", f"veins {'hide' if self._options['hide_veins'] else 'show'}"]
        lines += [f"{x}|{object_path(m)}|{object_path(t)}" for x, m, t in s["swaps"]]
        path = os.path.join(self._bin, "swaps.txt")   # next to di2swap.dll
        open(path, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")

    def _write_mod_config(self, chosen):
        classes, archs = self._cat.mod_classes(chosen)
        lines = ["-- Written by the mod launcher: models chosen for each zombie type.",
                 "-- Used by the Lua part only to repair mannequins; the swap itself is done by di2swap.dll.",
                 "return {"]
        for arch in ("walker", "shambler", "runner", "insect"):
            lines.append(f"    {arch} = {lua_list(archs.get(arch, []))},")
        lines.append("    classes = {")
        for cls, ms in sorted(classes.items()):
            lines.append(f"        [{json.dumps(cls)}] = {lua_list(ms)},")
        lines += ["    },", "    interval_ms = 500,", "    summary_s = 60,", "}", ""]
        path = os.path.join(self._bin, MOD_DIR, "Scripts", "config.lua")
        open(path, "w", encoding="utf-8", newline="\n").write("\n".join(lines))

    # ---------- launcher files ----------
    def _uninstall_launcher_files(self):
        import main
        main.uninstall_launcher_files()

    # ---------- helpers ----------
    def _js(self, fn, *args):
        if self._window:
            try:
                self._window.evaluate_js(f"{fn}({', '.join(json.dumps(a) for a in args)})")
            except Exception:   # window already closed (Apply and launch)
                pass

    def _run(self, work, done):
        if self._busy:
            return
        if game_running():
            self._js("ui.error", "Dead Island 2 is running. Close it before changing the mod.")
            return
        self._busy = True
        self._js("ui.busy", True)
        last = [0.0]

        def prog(frac):
            if frac - last[0] >= 0.01 or frac >= 1:
                last[0] = frac
                self._js("ui.progress", frac)

        def worker():
            err = None
            try:
                work(lambda msg: self._js("ui.status", msg), prog)
            except PermissionError as ex:
                traceback.print_exc()
                err = (f"Could not write {os.path.basename(str(ex.filename or ''))} in the game folder: it is "
                       "probably still in use. Close Dead Island 2 completely (also check the Task Manager for "
                       "a game process left behind after a crash), then try again.\n\nIf it keeps failing, "
                       "the game folder may be protected: run the launcher as administrator.")
            except Exception as ex:
                traceback.print_exc()
                err = str(ex)
            self._busy = False
            self._js("ui.busy", False)
            if err:
                self._js("ui.error", err)
            else:
                done()
            self._js("ui.refresh")

        threading.Thread(target=worker, daemon=True).start()


WEBVIEW2_CLIENT = r"Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
WEBVIEW2_PAGE = "https://developer.microsoft.com/microsoft-edge/webview2/"


def webview2_installed():
    """Microsoft Edge WebView2 Runtime (draws the launcher's window): its version in the registry,
    where Microsoft documents to look for it."""
    import winreg
    for hive, key in ((winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\WOW6432Node\\" + WEBVIEW2_CLIENT),
                      (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\" + WEBVIEW2_CLIENT),
                      (winreg.HKEY_CURRENT_USER, "Software\\" + WEBVIEW2_CLIENT)):
        try:
            with winreg.OpenKey(hive, key) as k:
                version = winreg.QueryValueEx(k, "pv")[0]
                if version and version != "0.0.0.0":
                    return True
        except OSError:
            continue
    return False


def ask_for_webview2():
    import tkinter as tk
    import webbrowser
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    if messagebox.askyesno(TITLE, "The launcher's window needs the Microsoft Edge WebView2 Runtime, which is "
                                  "missing on this PC.\n\nIt is free, made by Microsoft, and already present on "
                                  "most Windows 10/11 PCs. Install the \"Evergreen\" runtime, then open the "
                                  "launcher again.\n\nOpen the download page?"):
        webbrowser.open(WEBVIEW2_PAGE)


def run():
    if not webview2_installed():
        ask_for_webview2()
        return
    api = Api()
    api._window = webview.create_window(TITLE, res_dir("ui", "index.html"), js_api=api,
                                        width=1220, height=820, min_size=(960, 600), background_color="#16181d")
    try:
        # only WebView2: the old Internet Explorer fallback cannot draw this interface
        webview.start(gui="edgechromium")
    except Exception:
        traceback.print_exc()
        ask_for_webview2()
