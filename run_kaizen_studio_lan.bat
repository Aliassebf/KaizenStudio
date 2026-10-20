@echo off
setlocal
cd /d "%~dp0"

echo Recherche de l'adresse IPv4 du reseau local...
set "KAIZEN_STUDIO_HOST="
for /f "delims=" %%I in ('powershell -NoProfile -Command "$config = Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.IPv4Address }; $config | ForEach-Object { $_.IPv4Address } | Where-Object { $_.IPAddress -notlike '169.254.*' } | Select-Object -First 1 -ExpandProperty IPAddress"') do set "KAIZEN_STUDIO_HOST=%%I"

if not defined KAIZEN_STUDIO_HOST (
    echo ERREUR : aucune adresse IPv4 active avec une passerelle n'a ete trouvee.
    echo Connectez le PC au reseau de l'entreprise puis relancez ce fichier.
    pause
    exit /b 1
)

echo Adresse IPv4 detectee : %KAIZEN_STUDIO_HOST%
echo.
echo ATTENTION : le mode HTTP ne chiffre rien. Les mots de passe, videos et donnees
echo peuvent etre interceptes par toute personne capable d'observer le trafic reseau.
echo Utilisez-le uniquement sur un reseau prive approuve et filtre par l'equipe IT.
set "CONFIRM_HTTP="
set /p "CONFIRM_HTTP=Tapez OUI pour continuer en HTTP non chiffre : "
if /i not "%CONFIRM_HTTP%"=="OUI" (
    echo Demarrage annule.
    pause
    exit /b 1
)

set "KAIZEN_STUDIO_SSL_CERTFILE="
set "KAIZEN_STUDIO_SSL_KEYFILE="
set "KAIZEN_STUDIO_COOKIE_SECURE=0"
set "KAIZEN_STUDIO_ALLOW_INSECURE_LAN=1"

echo.
echo Kaizen Studio sera accessible en HTTP a cette adresse :
echo http://%KAIZEN_STUDIO_HOST%:8000/
echo Cette adresse n'est pas une garantie de confinement : demandez a l'IT de limiter le port 8000
echo aux postes ou au sous-reseau approuves et de confirmer l'absence d'exposition a Internet.
echo.
call "%~dp0run_kaizen_studio.bat"

endlocal
