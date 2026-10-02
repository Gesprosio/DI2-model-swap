"""Entry point of the mod's exe: downloaded as "DI2 Model Swap Installer.exe", installed as
"Dead Island 2 Model Swap.exe" (same program, the role depends on where it runs from):

  run from anywhere else        -> setup: finds Dead Island 2 (Epic or Steam), copies itself into
                                   <game>\\ModLauncher, creates a desktop shortcut, opens the launcher
  run from <game>\\ModLauncher   -> the launcher window (webapp_di2.py)

Everything the mod needs lives in <game>\\ModLauncher, so uninstalling the game removes it too.
The model swap itself runs inside the game (di2swap.dll, loaded by the UE4SS mod).
"""
import os
import shutil
import subprocess
import sys

APP_NAME = "Dead Island 2 Model Swap"
EXE_NAME = APP_NAME + ".exe"      # the downloaded file is "DI2 Model Swap Installer.exe": same program
OLD_NAMES = ("Dead Island 2 Mod Launcher",)   # names of earlier builds (exe + desktop shortcut)
NO_WINDOW = 0x08000000
# where the first launcher build lived (before the installer): moved into the game folder
OLD_APPDIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "DI2ModLauncher")


def is_running_installed():
    if not getattr(sys, "frozen", False):
        return True  # development: python scripts are always "the launcher"
    from gamepaths import installed_game
    return installed_game() is not None


def desktop_shortcut_path(name=APP_NAME):
    desktop = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
    try:  # the real Desktop folder (may be redirected, e.g. to OneDrive)
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as k:
            desktop = winreg.QueryValueEx(k, "Desktop")[0]
    except OSError:
        pass
    return os.path.join(desktop, name + ".lnk")


def remove_old_names(target_dir):
    """Earlier builds were called "Dead Island 2 Mod Launcher": remove their exe and shortcut."""
    for name in OLD_NAMES:
        for path in (os.path.join(target_dir, name + ".exe"), desktop_shortcut_path(name)):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass


def create_shortcut(target):
    lnk = desktop_shortcut_path()
    ps = (f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}'); "
          f"$s.TargetPath = '{target}'; $s.WorkingDirectory = '{os.path.dirname(target)}'; "
          f"$s.IconLocation = '{target},0'; $s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                   creationflags=NO_WINDOW, check=False)
    return os.path.exists(lnk)


def migrate_old_install(target_dir):
    """Keep the choices and caches of the first build (in %LOCALAPPDATA%), then remove it."""
    if not os.path.isdir(OLD_APPDIR):
        return
    for name in ("config.json",):
        src, dst = os.path.join(OLD_APPDIR, name), os.path.join(target_dir, name)
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)
    shutil.rmtree(OLD_APPDIR, ignore_errors=True)


def pick_game_folder(messagebox, filedialog):
    """Let the user point at the game folder by hand; None if cancelled."""
    from gamepaths import game_root_from
    while True:
        folder = filedialog.askdirectory(title="Select the Dead Island 2 folder (the one that contains \"DeadIsland\")")
        if not folder:
            return None
        game = game_root_from(folder)
        if game:
            return game
        if not messagebox.askretrycancel(APP_NAME, f"Dead Island 2 was not found in:\n{folder}\n\n"
                                                  "Select the game's installation folder, for example\n"
                                                  r"C:\Program Files\Epic Games\DeadIsland2"):
            return None


def setup():
    import tkinter as tk
    from tkinter import filedialog, messagebox
    from gamepaths import INSTALL_SUBDIR, find_game, store_of

    root = tk.Tk()
    root.withdraw()
    game = find_game()
    if not game:
        if not messagebox.askyesno(APP_NAME, "Dead Island 2 was not found automatically.\n\n"
                                             "Do you want to select its installation folder yourself?"):
            return
        game = pick_game_folder(messagebox, filedialog)
        if not game:
            return
    while True:
        store = "Steam" if store_of(game) == "steam" else "Epic Games Store"
        target_dir = os.path.join(game, INSTALL_SUBDIR)
        target = os.path.join(target_dir, EXE_NAME)
        installed = [os.path.join(target_dir, n + ".exe") for n in (APP_NAME,) + OLD_NAMES]
        action = "Update" if any(os.path.exists(p) for p in installed) else "Install"
        answer = messagebox.askyesnocancel(APP_NAME, f"Dead Island 2 ({store}) found in:\n{game}\n\n"
                                                     f"{action} the mod launcher in:\n{target_dir}\n\n"
                                                     "Everything stays inside the game folder: uninstalling "
                                                     "the game removes the mod too.\n\n"
                                                     "Yes = continue    No = choose another folder")
        if answer is None:
            return
        if answer:
            break
        other = pick_game_folder(messagebox, filedialog)
        if other:
            game = other
    try:
        os.makedirs(target_dir, exist_ok=True)
        shutil.copy2(sys.executable, target)
    except PermissionError:
        messagebox.showerror(APP_NAME, "Could not write the launcher: close the mod launcher (and Dead Island 2) "
                                       "if they are open, then run this setup again.\n\nIf the game is in a "
                                       "protected folder, run this setup as administrator.")
        return
    migrate_old_install(target_dir)
    remove_old_names(target_dir)
    shortcut = create_shortcut(target)
    if messagebox.askyesno(APP_NAME, f"{action} complete." +
                           ("\nA shortcut was added to your desktop." if shortcut else "") +
                           "\n\nOpen the mod launcher now?"):
        subprocess.Popen([target], cwd=target_dir)


def uninstall_launcher_files():
    """Remove the desktop shortcut and, once this program has exited, its own folder."""
    for name in (APP_NAME,) + OLD_NAMES:
        lnk = desktop_shortcut_path(name)
        if os.path.exists(lnk):
            os.remove(lnk)
    if getattr(sys, "frozen", False) and is_running_installed():
        folder = os.path.dirname(sys.executable)
        # wait for this process to exit, then delete the ModLauncher folder
        subprocess.Popen(f'cmd /c "timeout /t 3 /nobreak >nul & rmdir /s /q "{folder}""',
                         creationflags=NO_WINDOW, shell=False)


def main():
    if is_running_installed():
        import webapp_di2
        webapp_di2.run()
    else:
        setup()


if __name__ == "__main__":
    main()
