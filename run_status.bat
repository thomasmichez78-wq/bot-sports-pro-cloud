@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo BOT SPORTS PRO - STATUT
echo =======================
python -u app.py status
echo.
pause
