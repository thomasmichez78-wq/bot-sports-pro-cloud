@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo BOT SPORTS PRO - INSTALLATION
echo =============================
echo Dossier : %CD%
echo.

where python > nul 2>&1
if errorlevel 1 (
    echo ERREUR : Python est introuvable.
    pause
    exit /b 1
)

echo [1/2] Initialisation du socle...
python -u app.py init
if errorlevel 1 (
    echo ERREUR : l'initialisation a échoué.
    pause
    exit /b 1
)

echo.
echo [2/2] Exécution des tests...
python -u -m unittest discover -s tests -v
if errorlevel 1 (
    echo ERREUR : au moins un test a échoué.
    pause
    exit /b 1
)

if not exist ".env" copy ".env.example" ".env" > nul

echo.
echo Installation terminée.
echo Renseigne maintenant tes clés dans le fichier .env.
pause
