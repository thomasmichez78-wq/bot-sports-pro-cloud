@echo off
cd /d C:\bot-sports-pro
python app.py update-live-football-history
exit /b %errorlevel%
