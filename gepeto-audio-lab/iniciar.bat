@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Gepeto Audio Lab
rem Se o app já estiver rodando, só abre o navegador.
curl -s -m 2 http://127.0.0.1:8000/api/info >nul 2>nul
if %errorlevel%==0 (
  start "" http://127.0.0.1:8000
  exit /b 0
)
if not exist ".venv\Scripts\python.exe" (
  echo Primeira execucao: rodando o instalador.
  call instalar.bat
  if not exist ".venv\Scripts\python.exe" exit /b 1
)
".venv\Scripts\python.exe" app.py --abrir %*
pause
