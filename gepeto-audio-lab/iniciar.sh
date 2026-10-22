#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || ./instalar.sh
exec .venv/bin/python app.py "$@"
