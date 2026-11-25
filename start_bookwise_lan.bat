@echo off
cd /d "%~dp0"
echo.
echo === Open one of these addresses on your phone (with http://) ===
ipconfig | findstr /i "IPv4"
echo ===============================================================
echo.
venv\Scripts\python.exe -m waitress --listen=0.0.0.0:8000 config.wsgi:application