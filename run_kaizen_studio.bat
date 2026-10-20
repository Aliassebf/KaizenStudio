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
    echo ERREUR : Python 3.11 est introuvable. Installez-le pour votre compte utilisateur ou ajoutez-le au PATH.
    pause
    exit /b 1
)

if exist "%~dp0wheelhouse\*.whl" (
    echo Installation hors ligne des dependances depuis le dossier wheelhouse...
    %PYTHON% -m pip install --user --no-index --find-links "%~dp0wheelhouse" -r "%~dp0requirements.txt"
) else (
    echo Installation ou verification des dependances pour l'utilisateur courant...
    %PYTHON% -m pip install --user -r "%~dp0requirements.txt"
)
if errorlevel 1 (
    echo ERREUR : installation des dependances impossible.
    echo Verifiez le dossier wheelhouse ou l'acces a l'index Python approuve par votre entreprise.
    echo Pour preparer les dependances hors ligne, lancez prepare_offline_dependencies.bat sur un PC connecte.
    pause
    exit /b 1
)

echo.
echo Demarrage de Kaizen Studio. Fermez cette fenetre ou faites Ctrl+C pour arreter.
%PYTHON% -m app.launcher
if errorlevel 1 (
    echo ERREUR : Kaizen Studio s'est arrete avec une erreur.
    pause
    exit /b 1
)

endlocal
