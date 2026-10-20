@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1

where py >nul 2>nul
if not errorlevel 1 (
    py -3.11 -c "import sys; print(sys.version)" >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON=py -3.11"
    )
)

if not defined PYTHON (
    python -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 11) else 1)" >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON=python"
    )
)

if not defined PYTHON (
    echo ERREUR : Python 3.11 est introuvable. Installez-le pour le compte utilisateur ou ajoutez-le au PATH.
    pause
    exit /b 1
)

if not exist "%~dp0wheelhouse" mkdir "%~dp0wheelhouse"
echo Telechargement des dependances Windows Python 3.11 dans le dossier wheelhouse...
%PYTHON% -m pip download --only-binary=:all: --dest "%~dp0wheelhouse" -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo ERREUR : telechargement impossible. Verifiez l'index de paquets approuve et les roues disponibles.
    pause
    exit /b 1
)

echo.
echo Dependances hors ligne preparees dans "%~dp0wheelhouse".
echo Copiez le dossier du projet complet vers le PC cible, puis lancez run_kaizen_studio.bat.
pause

endlocal
