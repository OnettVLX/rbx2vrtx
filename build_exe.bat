@echo off
cd /d "%~dp0"

REM Safety checks: make sure both files are the NEW versions
if not exist rbx2vrtx_gui.py (
  echo ERROR: rbx2vrtx_gui.py is missing. Put it in this folder.
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

REM Folder build (--onedir): antivirus programs flag this far less than a single-file exe
py -m PyInstaller --clean --onedir --windowed --name "RBLX2VRTX" rbx2vrtx_gui.py

REM Zip the folder so it is one easy download
powershell -NoProfile -Command "Compress-Archive -Path 'dist\RBLX2VRTX' -DestinationPath 'dist\RBLX2VRTX.zip' -Force"

echo.
echo Done.
echo To use it yourself: open dist\RBLX2VRTX and double-click RBLX2VRTX.exe
echo To share it: upload dist\RBLX2VRTX.zip to your GitHub release.
pause
