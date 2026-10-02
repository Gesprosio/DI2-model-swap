"""Finds Dead Island 2 on this PC: Epic Games Store (install manifests) or Steam (app 934700,
on any Steam library drive). The game folder is the one that contains DeadIsland\\Binaries."""
import glob
import json
import os
import re
import sys

GAME_MARKER = os.path.join("DeadIsland", "Binaries", "Win64", "DeadIsland-Win64-Shipping.exe")
STEAM_APP_ID = "934700"
EPIC_MANIFESTS = r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests\*.item"
INSTALL_SUBDIR = "ModLauncher"


def is_game(folder):
    return bool(folder) and os.path.exists(os.path.join(folder, GAME_MARKER))


def store_of(folder):
    return "steam" if "steamapps" in folder.lower() else "epic"


def _epic():
    for item in glob.glob(EPIC_MANIFESTS):
        try:
            m = json.load(open(item, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if m.get("DisplayName", "").startswith("Dead Island 2") or m.get("MainGameAppName") == "Crow":
            if is_game(m.get("InstallLocation")):
                yield os.path.normpath(m["InstallLocation"])


def _steam_roots():
    roots = []
    try:
        import winreg
        for hive, key, value in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                                 (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                                 (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath")):
            try:
                with winreg.OpenKey(hive, key) as k:
                    roots.append(os.path.normpath(winreg.QueryValueEx(k, value)[0]))
            except OSError:
                pass
    except ImportError:
        pass
    roots.append(r"C:\Program Files (x86)\Steam")
    return list(dict.fromkeys(roots))


def _steam():
    for root in _steam_roots():
        libs = [root]
        try:
            text = open(os.path.join(root, "steamapps", "libraryfolders.vdf"), encoding="utf-8", errors="replace").read()
            libs += [p.replace("\\\\", "\\") for p in re.findall(r'"path"\s+"([^"]+)"', text)]
        except OSError:
            pass
        for lib in dict.fromkeys(os.path.normpath(p) for p in libs):
            installdir = "Dead Island 2"
            try:
                acf = open(os.path.join(lib, "steamapps", f"appmanifest_{STEAM_APP_ID}.acf"),
                           encoding="utf-8", errors="replace").read()
                m = re.search(r'"installdir"\s+"([^"]+)"', acf)
                if m:
                    installdir = m.group(1)
            except OSError:
                pass
            game = os.path.join(lib, "steamapps", "common", installdir)
            if is_game(game):
                yield game


def _common_places():
    """Last resort: the usual install folders on every drive."""
    for d in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        for sub in (r"Program Files\Epic Games\DeadIsland2", r"Epic Games\DeadIsland2", r"Games\DeadIsland2",
                    r"Program Files (x86)\Steam\steamapps\common\Dead Island 2",
                    r"SteamLibrary\steamapps\common\Dead Island 2", r"Steam\steamapps\common\Dead Island 2"):
            game = f"{d}:\\{sub}"
            if is_game(game):
                yield game


def find_game():
    """Folder of the Dead Island 2 install on this PC, or None."""
    for source in (_epic, _steam, _common_places):
        for game in source():
            try:  # Steam stores paths lowercased: get the real letter case
                from pathlib import Path
                return str(Path(game).resolve())
            except OSError:
                return game
    return None


def game_root_from(folder):
    """The game folder for a folder picked by hand: the game folder itself, any folder inside it
    (DeadIsland, Binaries, Win64...) or the folder that contains it. None if it is not Dead Island 2."""
    if not folder:
        return None
    folder = os.path.normpath(folder)
    if os.path.isfile(folder):
        folder = os.path.dirname(folder)
    probe = folder
    for _ in range(5):   # the folder or one of its parents (picked DeadIsland\Binaries\Win64 ...)
        if is_game(probe):
            return probe
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    for sub in ("DeadIsland2", "Dead Island 2"):   # the folder that contains the game (Epic Games, common)
        if is_game(os.path.join(folder, sub)):
            return os.path.join(folder, sub)
    return None


def installed_game():
    """When this exe runs from <game>\\ModLauncher: that game folder, else None."""
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        parent = os.path.dirname(exe_dir)
        if os.path.basename(exe_dir).lower() == INSTALL_SUBDIR.lower() and is_game(parent):
            return parent
    return None


def game_dir():
    """The game folder this program works on: the one containing it, else the install found."""
    return installed_game() or find_game()
