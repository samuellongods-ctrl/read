#!/usr/bin/env bash
# Instalação no Linux/macOS
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
"$PY" -c 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)' \
  || { echo "Precisa do Python 3.10 a 3.13 (defina PYTHON=/caminho/python)."; exit 1; }
[ -x .venv/bin/python ] || "$PY" -m venv .venv
VPY=.venv/bin/python
"$VPY" -m pip install --upgrade pip
EXTRA=cpu
if command -v nvidia-smi >/dev/null 2>&1; then
  echo "Placa NVIDIA detectada: instalando PyTorch com CUDA."
  "$VPY" -m pip install torch
  EXTRA=gpu
elif [ "$(uname)" = "Darwin" ]; then
  "$VPY" -m pip install torch
else
  "$VPY" -m pip install torch --index-url https://download.pytorch.org/whl/cpu
fi
"$VPY" -m pip install -r requirements.txt "audio-separator[$EXTRA]"
"$VPY" -c "import app; print('ffmpeg:', app.FFMPEG or 'NAO ENCONTRADO')"
echo "Instalação concluída. Rode ./iniciar.sh"
