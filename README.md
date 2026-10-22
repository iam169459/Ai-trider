# Ai-trider

Conservative **Binance Spot** trading bot built on [Freqtrade](https://www.freqtrade.io)
with the browser based **FreqUI** dashboard.

> **This is a paper-trading (dry-run) setup.** Real money trading is disabled and
> requires explicit approval. No profitability is claimed or implied - see
> [`docs/RISK-LIMITS.md`](docs/RISK-LIMITS.md) for the measured backtest numbers.

## What is in here

| Path | Purpose |
| --- | --- |
| `config/config.json` | Main configuration (dry-run, no secrets) |
| `config/config.docker.json` | Docker variant (only differs in db/log paths) |
| `config/secrets.example.json` | Template for the FreqUI credentials |
| `config/secrets.json` | **Generated** credentials - git ignored, mode `0600` |
| `user_data/strategies/ConservativeTrendStrategy.py` | The trading strategy |
| `user_data/tests/` | Offline test suite (risk safeguards) |
| `scripts/` | Setup, secret generation, backtest and verification helpers |
| `docs/` | Setup guide, runbook (incl. recovery) and risk limits |

## Quick start (macOS)

```bash
# 1. install Freqtrade in a virtualenv (Apple Silicon: use the Docker guide)
brew install python@3.12 gettext libomp
git clone https://github.com/freqtrade/freqtrade.git
cd freqtrade && git checkout stable && bash setup.sh -i
cd ..

# 2. create the local secrets for the FreqUI login
python3 scripts/generate_secrets.py --print

# 3. download two years of 1h candles and backtest
source .venv/bin/activate
freqtrade download-data --config config/config.json --exchange binance \
    --pairs "BTC/USDT" "ETH/USDT" --timeframes 1h --days 730
python3 scripts/backtest_report.py 20241021-20261021

# 4. run the tests (offline, no exchange connection)
python3 -m pytest user_data/tests -v

# 5. start the bot in dry-run mode with the dashboard
freqtrade trade --config config/config.json --strategy ConservativeTrendStrategy
```

Then open <http://127.0.0.1:8080> and log in with the credentials from step 2.

Full instructions: [`docs/SETUP.md`](docs/SETUP.md).

## Safety properties

* `dry_run: true` - the bot never places a real order.
* The API server binds to `127.0.0.1` only, with a random username/password,
  a random JWT key and a random websocket token.
* No API key or secret is stored in the repository; Binance credentials stay
  in `config/secrets.json` (or environment variables).
* At most **one** open trade, fixed stake, hard stop-loss.
* A **daily loss circuit breaker** and Freqtrade's **MaxDrawdown /
  StoplossGuard / CooldownPeriod** protections stop trading when the risk
  budget is exceeded.  See [`docs/RISK-LIMITS.md`](docs/RISK-LIMITS.md) for the
  measured behaviour.

## Documentation

* [`docs/SETUP.md`](docs/SETUP.md) - installation, configuration, VS Code usage.
* [`docs/RUNBOOK.md`](docs/RUNBOOK.md) - daily operation, logs, recovery.
* [`docs/RISK-LIMITS.md`](docs/RISK-LIMITS.md) - risk parameters and backtest results.

## Development

```bash
python3 -m pytest user_data/tests -v   # offline test suite (38 tests)
ruff check .                            # linting (configured in pyproject.toml)
python3 scripts/verify_setup.py         # 29 safety checks on the local setup
```
