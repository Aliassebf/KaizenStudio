@echo off
setlocal
cd /d "%~dp0"
set "ROOT=%CD%"
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
    echo ERREUR : Python 3.11 64 bits est requis pour construire l'executable.
    pause
    exit /b 1
)

%PYTHON% -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo ERREUR : PyInstaller n'est pas installe dans cet environnement Python.
    echo Installez les dependances de construction avec :
    echo %PYTHON% -m pip install -r requirements-build.txt
    pause
    exit /b 1
)

echo Creation de l'icone KS...
%PYTHON% tools\create_kaizen_icon.py
if errorlevel 1 (
    echo ERREUR : creation de l'icone impossible.
    pause
    exit /b 1
)

echo Construction de KaizenStudio.exe...
%PYTHON% -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name KaizenStudio ^
    --icon "%ROOT%\assets\kaizen_studio.ico" ^
    --add-data "%ROOT%\assets\kaizen_studio.ico;assets" ^
    --add-data "%ROOT%\app\static;app\static" ^
    --collect-all mediapipe ^
    --collect-all cv2 ^
    --collect-submodules app ^
    --distpath "%ROOT%\dist" ^
    --workpath "%ROOT%\build\work" ^
    --specpath "%ROOT%\build" ^
    "%ROOT%\kaizen_studio_exe.py"
if errorlevel 1 (
    echo ERREUR : la construction a echoue. Consultez le message PyInstaller ci-dessus.
    pause
    exit /b 1
)

echo.
echo Executable autonome cree : "%~dp0dist\KaizenStudio.exe"
echo Python n'est pas requis sur le PC cible. Copiez uniquement cet executable approuve par l'IT.
pause

endlocal
