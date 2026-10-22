@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo ============================================================
echo   Gepeto Audio Lab - instalacao
echo ============================================================

set "PY="
for %%V in (3.12 3.11 3.10 3.13) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>nul && set "PY=py -%%V"
  )
)
if not defined PY (
  python -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo.
  echo Python 3.10 a 3.13 nao foi encontrado.
  echo Instale o Python 3.12 em https://www.python.org/downloads/
  echo e marque a opcao "Add python.exe to PATH". Ou rode:
  echo     winget install Python.Python.3.12
  echo Depois abra este arquivo de novo.
  pause
  exit /b 1
)
echo Usando: %PY%

if not exist ".venv\Scripts\python.exe" (
  echo Criando ambiente virtual .venv ...
  %PY% -m venv .venv
  if errorlevel 1 goto falha
)
set "VPY=.venv\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip
if errorlevel 1 goto falha

set "EXTRA=cpu"
where nvidia-smi >nul 2>nul
if %errorlevel%==0 (
  echo Placa NVIDIA detectada: instalando PyTorch com CUDA ^(GPU^).
  set "EXTRA=gpu"
  "%VPY%" -m pip install torch --index-url https://download.pytorch.org/whl/cu126
) else (
  echo Instalando PyTorch para CPU.
  "%VPY%" -m pip install torch --index-url https://download.pytorch.org/whl/cpu
)
if errorlevel 1 goto falha

echo Instalando o servidor, o yt-dlp e o audio-separator ...
"%VPY%" -m pip install -r requirements.txt "audio-separator[%EXTRA%]"
if errorlevel 1 goto falha

"%VPY%" -c "import app; print('ffmpeg:', app.FFMPEG or 'NAO ENCONTRADO')"

echo.
echo ============================================================
echo   Instalacao concluida. Para abrir, rode iniciar.bat
echo ============================================================
pause
exit /b 0

:falha
echo.
echo A instalacao falhou. Veja a mensagem acima e tente de novo.
pause
exit /b 1
