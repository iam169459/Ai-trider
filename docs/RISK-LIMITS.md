# Risk limits and measured results

> **No profitability is claimed.**  The numbers below are the result of one
> historical backtest of one simple strategy.  Past performance says nothing
> about future results, and a 10-50 USDT account is small enough that fees,
> slippage and rounding can dominate the outcome.

---

## 1. The risk budget

| Parameter | Value | Where | Meaning |
| --- | --- | --- | --- |
| Account (simulated) | 50 USDT | `dry_run_wallet`, `available_capital` | Upper end of the agreed budget |
| Stake per trade | 20 USDT | `stake_amount` | 40 % of the account |
| Open trades | 1 | `max_open_trades` | Never more than one position |
| Stop-loss | -4 % | `stoploss` | -0.80 USDT per trade = **1.6 % of the account** |
| Take profit | +4 % / +6 % / +8 % / +10 % | `minimal_roi` | After 0 h / 48 h / 96 h / 168 h |
| Daily loss limit | 3 % = 1.50 USDT | `daily_loss_limit` | No new entries + open positions are closed |
| Max drawdown | 10 % over 7 days | `MaxDrawdown` protection | Trading stops for 24 h |
| Stoploss guard | 2 stop losses / 24 h | `StoplossGuard` protection | Trading stops for 6 h |
| Cooldown | 3 candles (3 h) | `CooldownPeriod` protection | No re-entry on the same pair |
| Fee assumption | 0.10 % per side | `fee` | Binance spot taker fee (worst case) |

**Worst realistic case:** the account can lose ~1.6 % per trade (stop-loss)
plus the 0.2 % round-trip fee.  Two consecutive stop losses in one day trip
the daily loss circuit breaker.

## 2. How the safeguards are implemented

### Daily loss circuit breaker (`DailyLossGuard`)

* Implemented in `user_data/strategies/ConservativeTrendStrategy.py`.
* Sums the **realized** profit (fees included) of every trade closed during
  the current UTC day.
* **Latching:** once the limit is hit, trading stays blocked until the day
  changes - a later profitable trade cannot re-enable trading on a day that
  already breached the limit.
* **Fail closed:** if the trade history cannot be read, the guard reports
  "halted" and no new position is opened.
* Blocks new entries (`confirm_trade_entry`) *and* closes open positions
  (`custom_exit` -> exit reason `daily_loss_limit`).

### Freqtrade protections

Defined in the `protections` property of the strategy (Freqtrade deprecated
the `protections` section in the configuration file).

### What the protections do **not** cover

The `MaxDrawdown` protection looks at a **7 day window** and needs at least
three closed trades in it.  A *slow* drawdown that spreads over months is
therefore **not** caught by it - and this is exactly what happened in the
backtest: the measured maximum drawdown was **14.5 %**, well above the 10 %
limit of the protection, because the account bled slowly over ~500 days.

Adding a second `MaxDrawdown` with a 30 or 90 day window was tested and
changed neither the profit nor the maximum drawdown (the account was already
too slow to bleed for a window-based trigger to matter).  The daily loss
circuit breaker and the fixed stop-loss are what limit the damage in that
scenario.

## 3. Measured backtest results

Data: Binance spot 1h candles, 2021-01-20 -> 2026-10-21 (33 000 candles per
pair).  Protections enabled.  Fee 0.1 % per side.  Stake 20 USDT, one open
trade, 50 USDT starting balance.

| Period | Trades | Win rate | Result | Max drawdown |
| --- | --- | --- | --- | --- |
| 2021-01-20 -> 2023-12-31 | 101 | 44.6 % | **+7.18 USDT** (+14.4 %) | 14.5 % |
| 2024-01-01 -> 2026-10-21 | 81 | 49.4 % | **+6.72 USDT** (+13.4 %) | 14.7 % |
| full period | 182 | 47.3 % | **+14.71 USDT** (+29.4 %) | 14.5 % |

Exit reasons over the full period:

| Exit reason | Count | Average | Sum |
| --- | --- | --- | --- |
| `stop_loss` | 96 | -4.19 % | -402 % |
| `rsi_overbought` | 69 | +4.55 % | +314 % |
| `roi` | 17 | +9.65 % | +164 % |

Per pair: BTC/USDT +20.23 USDT (55.8 % win rate), ETH/USDT -5.52 USDT
(35.9 % win rate).

### How to read these numbers

* **+29 % over 5.8 years is roughly +4.4 % per year** on a 50 USDT
  account - about 2 USDT per year.  Any fee increase, slippage or a slightly
  different entry timing erases that.
* The edge comes from **fewer but larger wins** (69 overbought exits averaging
  +4.55 %) against **many small losses** (96 stop losses at -4.19 %).
  A win rate below 50 % is normal for trend following - but it also means the
  strategy is completely dependent on the winners being allowed to run.
* ETH/USDT lost money with this parameter set.  The strategy was **not**
  re-tuned for ETH - doing that on the same data would be overfitting.
* The parameters were chosen on 2021-2023 and checked on the unseen
  2024-2026 window; several neighbouring parameter sets (RSI threshold 38 to
  50, different EMA pairs) were **negative** in the same test, so the result
  is fragile.

**Conclusion: this is an unproven strategy.**  It is a reasonable skeleton
for dry-run testing and for learning how the bot behaves, not a money maker.
The daily loss circuit breaker, the maximum drawdown protection and the fixed
stop-loss are what make a 10-50 USDT account survivable while the strategy
is unproven.

## 4. Verification that was actually performed

| Check | Command | Result |
| --- | --- | --- |
| Risk safeguards | `python3 -m pytest user_data/tests -v` | 38 tests passed |
| Look-ahead bias | `freqtrade lookahead-analysis ... --minimum-trade-amount 20` | `has_bias = No`, 0 biased signals |
| Configuration | `python3 scripts/verify_setup.py` | 29 checks passed |
| Dry-run start | `freqtrade trade --config config/config.json` | starts, protections loaded |
| API binding | `lsof -nP -iTCP:8080 -sTCP:LISTEN` | `127.0.0.1:8080` only |
| API authentication | `curl /api/v1/status` without credentials | `401 Unauthorized` |

## 5. Change log of the tuning

| Change | Reason (measured) |
| --- | --- |
| Removed the "close below the fast EMA" exit | Closed 91 of 123 trades within hours, average -0.74 % |
| Removed the "close below the slow EMA" exit | Closed winners too early; -1.74 % average over 44 trades |
| Trailing stop switched off | Turned +13.9 USDT into -9 to -17 USDT over 2021-2026 |
| RSI entry threshold 45 -> 44 | 42/44/46 were tested; 44 was positive in every sub period, the others were not |
