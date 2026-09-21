#!/bin/bash
# Corre una revisión desde tu Mac. Útil si GitHub Actions termina bloqueado por el
# anti-bot de alguna farmacia: tu IP de casa no levanta sospechas.
#
# Uso manual:   ./local/correr.sh
# Automático:   ver local/README.md (launchd)
set -euo pipefail

cd "$(dirname "$0")/.."

# Credenciales del correo: cópialas a local/.env (ese archivo NO se sube a git)
if [ -f local/.env ]; then
  set -a
  source local/.env
  set +a
fi

export TZ="America/Mexico_City"
mkdir -p local/logs
LOG="local/logs/$(date +%Y-%m-%d).log"

{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S') ====="
  .venv/bin/python -m tracker
} >> "$LOG" 2>&1

# Guardar el historial en git (opcional, para que el dashboard en línea se actualice)
if [ "${SUBIR_A_GIT:-0}" = "1" ] && git diff --quiet --exit-code -- data docs/data; then
  :
elif [ "${SUBIR_A_GIT:-0}" = "1" ]; then
  git add data docs/data
  git commit -qm "Revisión local $(date '+%Y-%m-%d %H:%M')"
  git push -q
fi
