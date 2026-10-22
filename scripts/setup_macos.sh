#!/usr/bin/env bash
#
# Bootstrap the conservative Binance Spot bot on macOS.
#
# The script is idempotent: it can be re-run safely.  It never enables live
# trading and never touches your Binance account.
#
#   bash scripts/setup_macos.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY_VERSION="${PY_VERSION:-3.12}"
VENV="${VENV:-$ROOT/.venv}"

info()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
fail()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- toolchain
info "Checking the toolchain"
if ! command -v brew >/dev/null 2>&1; then
    fail "Homebrew is required: https://brew.sh"
fi
if ! command -v "python${PY_VERSION}" >/dev/null 2>&1; then
    info "Installing python@${PY_VERSION} and build dependencies"
    brew install "python@${PY_VERSION}" gettext libomp
fi
command -v "python${PY_VERSION}" >/dev/null 2>&1 || fail "python${PY_VERSION} not found"

ARCH="$(uname -m)"
if [ "$ARCH" = "arm64" ]; then
    warn "Apple Silicon detected.  Freqtrade does not support ARM64 natively -"
    warn "use the Docker guide in docs/SETUP.md (section 'Apple Silicon')."
    warn "Continuing with the native install anyway; it usually works but is not"
    warn "officially supported."
fi

# --------------------------------------------------------------- virtualenv
if [ ! -d "$VENV" ]; then
    info "Creating the virtualenv in $VENV"
    "python${PY_VERSION}" -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

info "Installing Freqtrade and the project requirements"
pip install --upgrade pip >/dev/null
if pip install -r requirements.txt; then
    :
else
    warn "pip install -r requirements.txt failed - installing freqtrade directly"
    pip install freqtrade
fi

# --------------------------------------------------------------- user dirs
info "Preparing the Freqtrade user directory"
freqtrade create-userdir --userdir user_data >/dev/null 2>&1 || true
mkdir -p user_data/logs user_data/data user_data/backtest_results

# ---------------------------------------------------------------- secrets
if [ -f config/secrets.json ]; then
    info "config/secrets.json already exists - keeping it"
else
    info "Generating the FreqUI credentials"
    python3 scripts/generate_secrets.py
fi

# ------------------------------------------------------------- sanity check
info "Verifying the installation"
python3 scripts/verify_setup.py

cat <<'EOF'

Setup complete.

Next steps:
  1. Get the dashboard credentials:
         python3 scripts/generate_secrets.py --print
  2. Download two years of 1h candles:
         freqtrade download-data --config config/config.json --exchange binance \
             --pairs "BTC/USDT" "ETH/USDT" --timeframes 1h --days 730
  3. Backtest:
         python3 scripts/backtest_report.py 20241021-20261021
  4. Run the offline test suite:
         python3 -m pytest user_data/tests -v
  5. Start the bot in DRY-RUN mode:
         bash scripts/run_dryrun.sh
     and open http://127.0.0.1:8080

Live trading is NOT enabled.  See docs/RUNBOOK.md before changing anything.
EOF
