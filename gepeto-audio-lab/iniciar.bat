@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Gepeto Audio Lab
if not exist ".venv\Scripts\python.exe" (
  echo Primeira execucao: rodando o instalador.
  call instalar.bat
  if not exist ".venv\Scripts\python.exe" exit /b 1
)
".venv\Scripts\python.exe" app.py --abrir %*
pause
