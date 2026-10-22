# Runbook - operating the bot

Everything below applies to the **dry-run** setup that ships with this
repository.

---

## 1. Daily operation

```bash
# start (dry-run + dashboard on http://127.0.0.1:8080)
bash scripts/run_dryrun.sh

# stop
Ctrl+C
```

Useful FreqUI pages:

| Page | What to look at |
| --- | --- |
| Dashboard | Bot state, balance, open trades, profit |
| Trades | Entry/exit reasons, fees, profit per trade |
| Chart | Entry and exit markers on the candles |
| Logs | The last log lines inside the browser |

## 2. Logs

| What | Where |
| --- | --- |
| Main log | `user_data/logs/freqtrade.log` |
| Rotated logs | `user_data/logs/freqtrade.log.*` |
| Trade database | `user_data/tradesv3.dryrun.sqlite` |
| Backtest results | `user_data/backtest_results/` |

```bash
tail -f user_data/logs/freqtrade.log
grep -i "error\|traceback" user_data/logs/freqtrade.log | tail -30
```

### Log messages you will see

| Message | Meaning |
| --- | --- |
| `DAILY LOSS LIMIT HIT: realized loss of ... today` | The daily circuit breaker tripped. No new entries until the next UTC day. |
| `Daily loss guard could not read the trade history` | The guard failed closed - trading is blocked until the state is known again. |
| `Exit <pair> forced: daily loss limit reached` | An open position was closed because of the daily loss limit. |
| `Using Protections: ...` | The list of active protections - check it on every start. |
| `Dry run is enabled. All trades are simulated.` | Confirmation that no real money is involved. |

## 3. Recovery procedures

### 3.1 The bot crashed

```bash
bash scripts/run_dryrun.sh
```

Freqtrade stores the state in `user_data/tradesv3.dryrun.sqlite`.  Open
trades survive a restart and are re-synced with the exchange (in dry-run
with the simulated exchange state).  Check the *Open trades* view after the
restart.

### 3.2 The dashboard does not come up

```bash
# 1. is anything listening?
lsof -nP -iTCP:8080 -sTCP:LISTEN

# 2. is the config still valid?
python3 scripts/verify_setup.py

# 3. does the log show an error?
tail -50 user_data/logs/freqtrade.log
```

Typical causes: a stale process still holding port 8080 (kill it with
`kill <pid>`), or a broken `config/secrets.json` (regenerate it with
`python3 scripts/generate_secrets.py --force`).

### 3.3 The bot does not open any trade

This is normal - the strategy is deliberately selective.  It needs
* an uptrend (EMA50 above EMA200, both rising),
* an RSI(14) cross above 44,
* price above both EMAs,
* above-average volume.

Check the *Chart* view: the entry markers show the historical signals.
In the measured backtest the strategy produced **~30 entries per year**
(182 entries over 5.8 years) - so a quiet week means nothing.

### 4. The bot opened a trade that was closed by the daily loss limit

Expected behaviour.  Check the exit reason in the FreqUI:

* `daily_loss_limit` -> the daily circuit breaker closed it.
* `stop_loss` -> the -4 % stop-loss was hit.
* `rsi_overbought` / `roi` -> a normal exit.

### 3.5 The database is corrupted

```bash
# stop the bot first, then
freqtrade convert-db --config config/config.json
```

If that fails, the dry-run database can be deleted safely - it only holds
simulated trades:

```bash
rm user_data/tradesv3.dryrun.sqlite
```

### 3.6 A backtest returns results that look wrong

Freqtrade caches backtest results.  If a number does not match your time
range, re-run with `--cache none` (the helper script always does):

```bash
python3 scripts/backtest_report.py 20241021-20261021
```

## 4. Routine maintenance

```bash
# weekly: make sure the setup is still consistent
python3 scripts/verify_setup.py
python3 -m pytest user_data/tests -q

# monthly: refresh the candle data
freqtrade download-data --config config/config.json --exchange binance \
    --pairs "BTC/USDT" "ETH/USDT" --timeframes 1h --days 730
```

## 5. Before you ever consider live trading

**Do not skip this list.**  Live trading is currently *not* configured and
*not* approved.

1. Run in dry-run for **at least 8 weeks** and check that the live behaviour
   matches the backtest (entry frequency, average profit, drawdown).
2. Re-check the Binance minimum order size
   (`freqtrade list-pairs --exchange binance`) - with a small account the
   5 USDT minimum notional matters.
3. Create a Binance API key **with spot trading only**:
   * *withdrawals*: **disabled**
   * *IP restriction*: enabled, and add only the IP of the machine that runs
     the bot
4. Put the key into `config/secrets.json` (never into git, never into the
   chat):
   ```json
   "exchange": { "key": "...", "secret": "..." }
   ```
   or use the environment variables
   `FREQTRADE__EXCHANGE__KEY` / `FREQTRADE__EXCHANGE__SECRET`.
5. Keep `"dry_run": true` until you have explicitly decided otherwise.
   Switching to live requires changing `dry_run` to `false` - **and it needs
   your explicit approval**, it is not done by this project.
6. Start with the **lowest** possible stake (e.g. 6 USDT) and let it run.

## 6. Security checklist

- [x] The API server binds to `127.0.0.1` only.
- [x] The API requires a username + password (`401` without them).
- [x] The password, JWT key and websocket token are random and stored in a
      git-ignored file with mode `0600`.
- [x] No exchange key/secret exists in the repository.
- [x] No withdrawal capability is ever created.
- [ ] (future) The Binance API key has withdrawals disabled and is
      IP-restricted.
