@echo off
rem Builds "DI2 Model Swap Installer.exe" into launcher\dist.
rem Run ue4ss\patch_ue4ss.py and dll\build.bat first: they fill launcher\payload.
cd /d "%~dp0"
for %%f in (UE4SS.dll dwmapi.dll di2swap.dll) do if not exist "payload\%%f" (echo payload\%%f is missing, see BUILD.md & exit /b 1)
python -m PyInstaller --noconfirm --clean --onefile --windowed --name "DI2 Model Swap Installer" ^
  --icon icon.ico --version-file version_info.txt --paths "." --hidden-import main --hidden-import gamepaths ^
  --exclude-module numpy --add-data "ui;ui" --add-data "data;data" --add-data "payload;payload" ^
  --collect-all webview --collect-all clr_loader --collect-all pythonnet ^
  --distpath dist --workpath build main.py
