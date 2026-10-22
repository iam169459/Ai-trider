#!/usr/bin/env bash
#
# Start the bot in DRY-RUN mode with the FreqUI dashboard.
#
#   bash scripts/run_dryrun.sh
#
# The dashboard is reachable at http://127.0.0.1:8080 only.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

STRATEGY="${STRATEGY:-ConservativeTrendStrategy}"
CONFIG="${CONFIG:-config/config.json}"

if [ ! -f "$CONFIG" ]; then
    echo "[x] Config $CONFIG not found - run scripts/setup_macos.sh first." >&2
    exit 1
fi
if [ ! -f config/secrets.json ]; then
    echo "[x] config/secrets.json missing - run: python3 scripts/generate_secrets.py" >&2
    exit 1
fi

# Refuse to start if live trading was ever enabled in the config.
if ! python3 -c "
import json,sys
c = json.load(open('$CONFIG'))
sys.exit(0 if c.get('dry_run') is True else 1)
"; then
    echo "[x] '$CONFIG' does not have dry_run=true - refusing to start." >&2
    exit 1
fi

if [ -x .venv/bin/freqtrade ]; then
    FT=".venv/bin/freqtrade"
elif command -v freqtrade >/dev/null 2>&1; then
    FT="freqtrade"
else
    echo "[x] freqtrade not found - activate the virtualenv or run scripts/setup_macos.sh" >&2
    exit 1
fi

echo "==> Starting $STRATEGY in DRY-RUN mode (no real orders will be placed)."
echo "==> FreqUI: http://127.0.0.1:8080"
exec "$FT" trade --config "$CONFIG" --strategy "$STRATEGY" "$@"
