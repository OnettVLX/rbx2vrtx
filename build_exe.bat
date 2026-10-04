@echo off
cd /d "%~dp0"

REM Safety checks: make sure both files are the NEW versions
if not exist rbx2vrtx_gui.py (
  echo ERROR: rbx2vrtx_gui.py is missing. Put it in this folder.
  pause
  exit /b 1
)
findstr /c:"TEMPLATE_B64" rbx2vrtx.py >nul
if errorlevel 1 (
  echo ERROR: rbx2vrtx.py is an OLD version. Re-download it and replace it.
  pause
  exit /b 1
)
findstr /c:"build_bytes" rbx2vrtx.py >nul
if errorlevel 1 (
  echo ERROR: rbx2vrtx.py is an OLD version. Re-download it and replace it.
  pause
  exit /b 1
)

REM Remove old build leftovers
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist *.spec del *.spec

py -m pip install --upgrade pyinstaller zstandard
py -m PyInstaller --clean --onefile --windowed --name "Roblox to Vortex" rbx2vrtx_gui.py

echo.
echo Done. Your app is at: dist\Roblox to Vortex.exe
echo Double-click it, press Open, pick a .rbxlx, then press Download.
pause
