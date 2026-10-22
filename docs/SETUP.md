# Setup guide - conservative Binance Spot bot (macOS + VS Code)

Everything in this guide runs in **dry-run** mode.  No real order is ever
placed by the configuration that ships with this repository.

---

## 1. Requirements

| Requirement | Notes |
| --- | --- |
| macOS 12+ | Intel or Apple Silicon |
| Python 3.12 | `brew install python@3.12` |
| Homebrew | <https://brew.sh> |
| VS Code | plus the *Python* and *Pylance* extensions |
| ~2 GB disk | for the virtualenv, TA-Lib and the candle data |

> **Apple Silicon:** Freqtrade does not support ARM64 natively.  The native
> installation usually works, but the officially supported route is Docker -
> see [section 8](#8-apple-silicon--docker).

## 2. Install Freqtrade

```bash
brew install python@3.12 gettext libomp

git clone https://github.com/freqtrade/freqtrade.git
cd freqtrade
git checkout stable          # or `git checkout develop` for the newest release
bash setup.sh -i             # -i installs the python dependencies
cd ..
```

`setup.sh -i` creates the virtualenv **inside the Freqtrade clone**
(`freqtrade/.venv`).  Two options:

* **Option A (recommended):** use that virtualenv.
  ```bash
  source freqtrade/.venv/bin/activate
  ```
* **Option B:** create your own virtualenv in this project.
  ```bash
  python3.12 -m venv .venv
  source .venv/bin/activate
  pip install freqtrade
  pip install -r requirements.txt
  ```

Option B keeps everything inside this repository, which is what the helper
scripts in `scripts/` expect (`scripts/run_dryrun.sh` looks for
`.venv/bin/freqtrade` first).

## 3. Bootstrap this project

```bash
bash scripts/setup_macos.sh
```

The script

1. checks the toolchain,
2. creates `.venv` (if missing) and installs the requirements,
3. creates the Freqtrade `user_data` structure,
4. generates `config/secrets.json` (mode `0600`) with a random username,
   password, JWT key and websocket token,
5. runs `scripts/verify_setup.py`.

### VS Code

```bash
code .
```

The workspace already contains `.vscode/settings.json`:

* the interpreter is `${workspaceFolder}/.venv/bin/python`,
* the pytest test discovery is limited to `user_data/tests`,
* Ruff is configured as the formatter.

Pick the interpreter with `Cmd+Shift+P` -> *Python: Select Interpreter* ->
`.venv/bin/python`.

## 4. The credentials

The FreqUI login data is **not** in `config/config.json`.  It lives in
`config/secrets.json` (git ignored, mode `0600`) and is merged in through
`"add_config_files": ["secrets.json"]`.

```bash
python3 scripts/generate_secrets.py --print
```

```
username: trader_XXXXXXXXXXXX
password: ****************
url:      http://127.0.0.1:8080
```

> **Why the secrets live in a second file:** Freqtrade gives the *parent*
> config priority over the files listed in `add_config_files`.  If the main
> config contained `"password": ""`, it would win and the generated password
> would be ignored.  `scripts/verify_setup.py` checks for exactly this
> mistake.

## 5. Download the data and backtest

```bash
freqtrade download-data --config config/config.json --exchange binance \
    --pairs "BTC/USDT" "ETH/USDT" --timeframes 1h --days 730

python3 scripts/backtest_report.py 20241021-20261021
```

> **Important:** always pass `--cache none` when you change the time range.
> Freqtrade caches backtest results by a hash of the configuration *and the
> strategy file* - the time range is **not** part of that hash, so a cached
> result of a different period can be reused silently.
> `scripts/backtest_report.py` always passes `--cache none`.

## 6. Run the offline test suite

```bash
python3 -m pytest user_data/tests -v
```

The tests never touch the network.  They cover the daily-loss circuit
breaker, the entry/exit logic and the Freqtrade protections.

## 7. Start the bot (dry-run) and the dashboard

```bash
bash scripts/run_dryrun.sh
```

* Dashboard: <http://127.0.0.1:8080>
* Log file: `user_data/logs/freqtrade.log`

The script refuses to start if `dry_run` is not `true` in the config.

Verify the binding and the authentication:

```bash
# must only listen on 127.0.0.1
lsof -nP -iTCP:8080 -sTCP:LISTEN

# must answer 401 without credentials
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/api/v1/status
```

## 8. Apple Silicon / Docker

```bash
docker compose -f docker-compose.yml up -d
```

The bundled `docker-compose.yml` mounts this directory into
`/user_data` and uses `config/config.docker.json` (which only changes the
database and log paths).  The dashboard is published on `127.0.0.1:8080`
only:

```yaml
ports:
  - "127.0.0.1:8080:8080"
```

## 9. Scaling to your real budget

The configuration assumes the upper end of the agreed range (50 USDT).
To simulate a smaller account, change **both** values in
`config/config.json`:

| Your budget | `dry_run_wallet` / `available_capital` | `stake_amount` |
| --- | --- | --- |
| 50 USDT | 50 | 20 |
| 25 USDT | 25 | 10 |
| 10 USDT | 10 | 6 |

`stake_amount` must stay **above ~6 USDT**: Binance requires a minimum
notional of 5 USDT per spot order, and Freqtrade adds a 5 % reserve plus the
4 % stop-loss on top of that.

## 10. What is *not* included

* No Binance API key - dry-run does not need one.
* No withdrawal permission - the key is never created, so it cannot be used
  to move funds.
* No live trading configuration - see `docs/RUNBOOK.md` for what would have
  to change, and what still needs your explicit approval.
