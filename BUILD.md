# Building

Everything is built on Windows 10/11 x64.

## Requirements

- Python 3.11 (64-bit), from python.org
- MinGW-w64 GCC, for example [w64devkit](https://github.com/skeeto/w64devkit) 2.x (the release was built with w64devkit 2.10.0)
- Python packages: `pip install -r launcher\requirements.txt`

## Steps

Run from the repository root.

**1. UE4SS** (downloads the official v3.0.1 zip, verifies it and applies the patch)

```
python ue4ss\patch_ue4ss.py
```

Writes `launcher\payload\UE4SS.dll` and `launcher\payload\dwmapi.dll`. The script checks the SHA-256
of the original and of the result, so you get the same bytes that are in the release.

**2. di2swap.dll**

```
dll\build.bat
```

Needs `gcc.exe` on PATH (or `set CC=C:\path\to\gcc.exe`). Writes `launcher\payload\di2swap.dll`.

**3. Installer exe**

```
launcher\build.bat
```

Writes `launcher\dist\DI2 Model Swap Installer.exe`.

## Bootloader note

The released exe uses a PyInstaller 6.21.0 bootloader compiled from source with MinGW-w64 instead
of the prebuilt one shipped in the wheel (the prebuilt bootloader is a common source of antivirus
false positives). This only changes the small stub that unpacks the app, not the app itself. To
do the same:

```
pip download pyinstaller==6.21.0 --no-binary :all: --no-deps
tar -xf pyinstaller-6.21.0.tar.gz
cd pyinstaller-6.21.0\bootloader
python ./waf distclean all --target-arch=64bit --gcc
cd ..
pip install .
```

(with the w64devkit `bin` folder on PATH). Building with the stock PyInstaller wheel also works,
the resulting exe behaves the same.

## Payload layout

After steps 1 and 2, `launcher\payload` contains exactly what the launcher copies next to
`DeadIsland-Win64-Shipping.exe` (in `DeadIsland\Binaries\Win64`):

```
dwmapi.dll                 UE4SS proxy loader (official, unchanged)
UE4SS.dll                  UE4SS 3.0.1, patched for Dead Island 2
UE4SS-settings.ini         Engine version 4.25, object array cache off, console on
VTableLayout.ini           UE4.25 layout with Dead Island 2's extra UObject virtual
di2swap.dll                the model swap (dll\di2swap.c)
Mods\mods.txt
Mods\DI2ZombieModels\Scripts\main.lua, config.lua
```

The launcher also writes `swaps.txt` there (the chosen models) and `di2swap.log` is created by the DLL.
