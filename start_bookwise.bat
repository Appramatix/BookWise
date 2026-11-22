@echo off
cd /d "%~dp0"
start "BookWise server" cmd /k "venv\Scripts\python.exe -m waitress --listen=127.0.0.1:8000 config.wsgi:application"
timeout /t 3 >nul
start "BookWise tunnel" cmd /k "cloudflared tunnel --url http://localhost:8000"