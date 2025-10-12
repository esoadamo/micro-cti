#!/bin/bash
set -eEuo pipefail
cd "$(dirname "$(realpath "$0")")"

COMMANDS=("uv run jobber.py" "uv run fastapi run web.py --port 80 --workers 4 --proxy-headers")

for CMD in "${COMMANDS[@]}"; do
    echo "Starting command: $CMD"
    eval "$CMD" &
done
wait -n
echo "One of the commands has exited. Exiting script."
exit 1
