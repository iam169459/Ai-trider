#!/usr/bin/env python3
"""
Validate a hyperopt result out-of-sample and (optionally) apply it.

Workflow:
  1. Read the best epoch from the newest hyperopt result file.
  2. Write it to ``user_data/strategies/<Strategy>.json`` (the file Freqtrade
     loads automatically).
  3. Backtest the *validation* window (which the optimizer never saw) with
     the trained parameters **and** with the hand-tuned defaults.
  4. Report both.  ``--apply`` keeps the parameter file, otherwise it is
     removed again.

The point of this script is to make the overfitting check unavoidable: the
optimizer only ever sees the training window, the decision is made on the
validation window.

Usage:
    python3 scripts/validate_hyperopt.py --train 20210120-20241231 \\
                                         --valid 20250101-20261021
    python3 scripts/validate_hyperopt.py --apply     # keep the best params
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "user_data" / "backtest_results"
HYPEROPT_DIR = ROOT / "user_data" / "hyperopt_results"
FREQTRADE = str(ROOT / ".venv" / "bin" / "freqtrade")
STRATEGY_DIR = ROOT / "user_data" / "strategies"


def best_epoch(strategy: str) -> dict:
    """Return the best epoch of the newest hyperopt result file."""
    files = sorted(HYPEROPT_DIR.glob(f"strategy_{strategy}_*.fthypt"))
    if not files:
        raise SystemExit("no hyperopt result file found - run hyperopt first")
    rows = []
    for line in files[-1].read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not rows:
        raise SystemExit("the hyperopt result file is empty")
    return min(rows, key=lambda row: row["loss"])


def params_file(strategy: str) -> Path:
    return STRATEGY_DIR / f"{strategy}.json"


def write_params(strategy: str, epoch: dict) -> Path:
    """Write the trained parameters in the format Freqtrade expects."""
    payload = {
        "strategy_name": strategy,
        "params": {
            "roi": epoch.get("params_not_optimized", {}).get("roi", {}),
            "stoploss": epoch.get("params_not_optimized", {}).get("stoploss", {}),
            "trailing": epoch.get("params_not_optimized", {}).get("trailing", {}),
            "max_open_trades": epoch.get("params_not_optimized", {}).get("max_open_trades", {}),
            "enter": epoch.get("params_details", {}).get("enter", {}),
            "exit": epoch.get("params_details", {}).get("exit", {}),
        },
    }
    target = params_file(strategy)
    target.write_text(json.dumps(payload, indent=2) + "\n")
    return target


def backtest(strategy: str, timerange: str) -> dict:
    before = {p.name for p in RESULTS.glob("*.zip")}
    cmd = [
        FREQTRADE, "backtesting",
        "--config", str(ROOT / "config" / "config.json"),
        "--strategy", strategy,
        "--timeframe", "1h",
        "--timerange", timerange,
        "--enable-protections",
        "--cache", "none",
        "--export", "trades",
    ]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout[-2000:], proc.stderr[-1000:], file=sys.stderr)
        raise SystemExit("backtest failed")
    after = {p.name for p in RESULTS.glob("*.zip")}
    new = sorted(after - before)
    if not new:
        raise SystemExit("no backtest result produced")
    with zipfile.ZipFile(RESULTS / new[-1]) as archive:
        fname = [x for x in archive.namelist() if x.endswith(".json") and "config" not in x][0]
        data = json.loads(archive.read(fname))
    return data["strategy"][strategy]


def summarise(stats: dict) -> dict:
    trades = stats.get("trades", [])
    profits = [t["profit_ratio"] for t in trades]
    return {
        "trades": len(trades),
        "profit": round(sum(t["profit_abs"] for t in trades), 2),
        "winrate": round(
            sum(1 for p in profits if p > 0) / len(profits) * 100, 1
        ) if profits else 0.0,
        "avg_trade": round(statistics.mean(profits) * 100, 2) if profits else 0.0,
        "max_dd": round((stats.get("max_drawdown_account") or 0) * 100, 2),
    }


def show(label: str, data: dict) -> None:
    print(
        f"  {label:28s} trades={data['trades']:4d} profit={data['profit']:+8.2f} USDT "
        f"win%={data['winrate']:5.1f} avg/trade={data['avg_trade']:+6.2f}% "
        f"maxDD={data['max_dd']:5.2f}%"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", default="ConservativeTrendStrategy")
    parser.add_argument("--train", default="20210120-20241231")
    parser.add_argument("--valid", default="20250101-20261021")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="keep the trained parameter file if the validation does not degrade",
    )
    args = parser.parse_args()

    epoch = best_epoch(args.strategy)
    print("=" * 78)
    print(f"Best hyperopt epoch (loss {epoch['loss']:.4f})")
    print("=" * 78)
    print(json.dumps(epoch["params_dict"], indent=2))

    target = params_file(args.strategy)

    def with_params(enabled: bool, timerange: str) -> dict:
        """Backtest with the trained parameters, or with the defaults."""
        if enabled:
            write_params(args.strategy, epoch)
        else:
            # No parameter file -> the strategy uses its class defaults.
            target.unlink(missing_ok=True)
        return backtest(args.strategy, timerange)

    print()
    print(f"--- training window {args.train} (the optimizer saw this) ---")
    train_trained = summarise(with_params(True, args.train))
    show("trained parameters", train_trained)
    train_default = summarise(with_params(False, args.train))
    show("default parameters", train_default)

    print()
    print(f"--- validation window {args.valid} (never seen by the optimizer) ---")
    valid_trained = summarise(with_params(True, args.valid))
    show("trained parameters", valid_trained)
    valid_default = summarise(with_params(False, args.valid))
    show("default parameters", valid_default)

    print()
    better_profit = valid_trained["profit"] > valid_default["profit"]
    worse_dd = valid_trained["max_dd"] > valid_default["max_dd"]
    verdict = (
        "ACCEPT"
        if better_profit and not worse_dd
        else "REJECT"
    )
    print(f"verdict: {verdict}")
    print(
        "  (accept only if the trained parameters are more profitable out-of-sample"
        " AND do not have a worse drawdown)"
    )

    if args.apply and verdict == "ACCEPT":
        write_params(args.strategy, epoch)
        print(f"  -> applied to {target}")
    else:
        # Remove the parameter file completely: without it the strategy uses
        # the class defaults.  A rejected parameter file must never stay
        # behind - it would silently change the behaviour of the bot.
        target.unlink(missing_ok=True)
        print("  -> the default parameters are kept (no parameter file)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
