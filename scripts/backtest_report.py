#!/usr/bin/env python3
"""
Run a backtest and print a compact report (including the exit reason
breakdown).  Purely a helper for the user - it never touches the network.

Usage:
    python3 scripts/backtest_report.py [timerange] [--strategy NAME]

Example:
    python3 scripts/backtest_report.py 20241021-20261021
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_backtest(freqtrade: str, config: Path, strategy: str, timerange: str) -> dict:
    out_dir = ROOT / "user_data" / "backtest_results"
    before = {p.name for p in out_dir.glob("*.zip")} if out_dir.exists() else set()

    cmd = [
        freqtrade,
        "backtesting",
        "--config",
        str(config),
        "--strategy",
        strategy,
        "--timeframe",
        "1h",
        "--timerange",
        timerange,
        "--enable-protections",
        # Without this Freqtrade reuses a cached result if the config and the
        # strategy file are unchanged - even if the timerange differs.
        "--cache",
        "none",
        "--export",
        "trades",
    ]
    print("$ " + " ".join(cmd) + "\n")
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout[-4000:])
        print(proc.stderr[-4000:], file=sys.stderr)
        raise SystemExit(f"backtest failed with exit code {proc.returncode}")
    if "Reusing result of previous backtest" in proc.stdout:
        print("WARNING: a cached backtest result was reused - the numbers below may be "
              "from an older run.\n")

    after = {p.name for p in out_dir.glob("*.zip")}
    new_files = sorted(after - before)
    if not new_files:
        raise SystemExit("no backtest result file was created")
    zip_name = new_files[-1]
    json_name = zip_name[: -len(".zip")] + ".json"
    with zipfile.ZipFile(out_dir / zip_name) as archive:
        return json.loads(archive.read(json_name))


def report(result: dict, strategy: str, wallet: float = 50.0) -> None:
    data = result["strategy"][strategy]
    trades = data["trades"]
    meta = result.get("strategy_comparison", [{}])

    print("=" * 78)
    print(f"Backtest report - {strategy}")
    print("=" * 78)
    if trades:
        profit_abs = sum(t["profit_abs"] for t in trades)
        wins = [t for t in trades if t["profit_ratio"] > 0]
        losses = [t for t in trades if t["profit_ratio"] <= 0]
        print(f"trades            : {len(trades)}")
        print(f"wins / losses     : {len(wins)} / {len(losses)}")
        print(
            f"total profit      : {profit_abs:+.2f} USDT "
            f"({profit_abs / wallet * 100:+.2f} % of a {wallet:.0f} USDT account)"
        )
        avg = statistics.mean(t["profit_ratio"] for t in trades) * 100
        print(f"avg profit/trade  : {avg:+.2f} %")
        best = max(t["profit_ratio"] for t in trades) * 100
        worst = min(t["profit_ratio"] for t in trades) * 100
        print(f"best / worst      : {best:+.2f} % / {worst:+.2f} %")
        print(
            f"avg duration      : "
            f"{statistics.mean(t['trade_duration'] for t in trades) / 60:.1f} h"
        )
        print(f"max drawdown      : {data.get('max_drawdown_account', 'n/a')}")

        print("\nExit reasons:")
        by_reason = collections.defaultdict(list)
        for t in trades:
            by_reason[t["exit_reason"]].append(t)
        for reason, group in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
            total = sum(t["profit_ratio"] for t in group)
            print(
                f"  {reason:20s} n={len(group):3d} "
                f"avg={statistics.mean(t['profit_ratio'] for t in group) * 100:6.2f} % "
                f"sum={total * 100:7.2f} % "
                f"wins={sum(1 for t in group if t['profit_ratio'] > 0)}"
            )

        print("\nPer pair:")
        by_pair = collections.defaultdict(list)
        for t in trades:
            by_pair[t["pair"]].append(t)
        for pair, group in sorted(by_pair.items()):
            total = sum(t["profit_abs"] for t in group)
            print(
                f"  {pair:12s} n={len(group):3d} "
                f"profit={total:+7.2f} USDT "
                f"win%={sum(1 for t in group if t['profit_ratio'] > 0) / len(group) * 100:5.1f}"
            )

        print("\nMonthly profit (USDT):")
        by_month = collections.defaultdict(float)
        for t in trades:
            by_month[t["close_date"][:7]] += t["profit_abs"]
        for month in sorted(by_month):
            print(f"  {month} {by_month[month]:+8.2f}")
    else:
        print("no trades were generated in this period")

    if meta:
        print("\n" + "-" * 78)
        for entry in meta:
            print(
                f"{entry.get('strategy')!s:35s} "
                f"trades={entry.get('total_trades') or 0:4d} "
                f"profit={entry.get('profit_total') or 0:+8.2f} USDT "
                f"drawdown={entry.get('max_drawdown_account') or 0:6.2f} %"
            )
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("timerange", nargs="?", default="20241021-20261021")
    parser.add_argument("--strategy", default="ConservativeTrendStrategy")
    parser.add_argument("--config", default="config/config.json")
    parser.add_argument("--freqtrade", default=".venv/bin/freqtrade")
    args = parser.parse_args()

    freqtrade = args.freqtrade
    if not Path(freqtrade).is_absolute() and not Path(freqtrade).exists():
        found = subprocess.run(
            ["which", "freqtrade"], check=False, capture_output=True, text=True
        ).stdout.strip()
        if not found:
            raise SystemExit("freqtrade executable not found - activate the virtualenv first")
        freqtrade = found

    result = run_backtest(freqtrade, ROOT / args.config, args.strategy, args.timerange)
    try:
        with (ROOT / args.config).open(encoding="utf-8") as fh:
            wallet = float(json.load(fh).get("dry_run_wallet", 50) or 50)
    except Exception:  # noqa: BLE001
        wallet = 50.0
    report(result, args.strategy, wallet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
