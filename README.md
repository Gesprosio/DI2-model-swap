# DI2 - Model Swap

Source code of **DI2 - Model Swap**, a Dead Island 2 mod that lets you choose which models the
common zombies (Walkers, Shamblers, Runners, bee swarm walkers) wear, mixing as many as you like.
It also has an option to hide the pulsing veins.

Download and instructions for players: Nexus Mods page.

The game's files are never modified. Everything happens in memory while the game runs, and
Restore / Uninstall in the launcher removes every file the mod added.

## How it works

| Part | Folder | What it does |
|---|---|---|
| Installer / launcher | `launcher/` | Python + pywebview app, packaged with PyInstaller into one exe. Run from anywhere it is the installer: it finds the game (Epic manifests, Steam libraries, or a folder you pick) and copies itself to `<game>\ModLauncher`. Run from there it is the launcher: you pick models, it copies the payload next to `DeadIsland-Win64-Shipping.exe`, writes `swaps.txt` and starts the game. |
| In-game swap | `dll/di2swap.c` | Small C DLL loaded inside the game. Reads `swaps.txt`, resolves the names in the engine's FName pool, rewrites the CharacterMesh entries of the asset manager and the Model field of the ModelVariant assets as they load, and (optional) zeroes the vein pulse material parameters. It only reads/writes memory of its own process. |
| UE4SS mod | `launcher/payload/Mods/DI2ZombieModels` | Lua mod that loads `di2swap.dll`, fixes zombies that spawned before their mesh was ready, and binds F3 to remove nearby zombies if a "kill them all" objective gets stuck. |
| UE4SS | `ue4ss/patch_ue4ss.py` | [UE4SS](https://github.com/UE4SS-RE/RE-UE4SS) v3.0.1 (MIT), loaded through its `dwmapi.dll` proxy. Stock 3.0.1 crashes on Dead Island 2's engine build, so the script downloads the official release and patches 20 bytes (documented in the script). `UE4SS-settings.ini` and `VTableLayout.ini` are the configs for this game. |

`launcher/data/*.json` are lists of zombie variant and mesh asset paths, used by the launcher to
show the models. They contain names only, no game assets.

No network access, no telemetry. The launcher only talks to the local game folder (and opens the
Epic/Steam launch URL to start the game, or the WebView2 download page if that runtime is missing).

## Building

See [BUILD.md](BUILD.md).

## License

MIT, see [LICENSE](LICENSE). UE4SS is MIT licensed by its authors.
Dead Island 2 belongs to Deep Silver / Dambuster Studios. This is a fan mod, not affiliated with them.
