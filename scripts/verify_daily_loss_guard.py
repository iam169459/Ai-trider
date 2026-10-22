#!/usr/bin/env python3
"""
Verify that the daily loss circuit breaker really fires inside a backtest.

The unit tests prove the guard logic; this script proves the *wiring* - that
Freqtrade actually calls ``confirm_trade_entry`` / ``custom_exit`` during a
backtest and that the guard blocks entries and closes positions.

It runs two backtests with a deliberately tiny daily loss limit (0.5 % of the
account = 0.25 USDT) and compares them with the normal limit (3 %).

Usage:
    python3 scripts/verify_daily_loss_guard.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "user_data" / "backtest_results"
FREQTRADE = str(ROOT / ".venv" / "bin" / "freqtrade")
STRATEGY = ROOT / "user_data" / "strategies" / "ConservativeTrendStrategy.py"
BACKUP = Path("/tmp/ConservativeTrendStrategy.py.bak")

TIMERANGE = "20241021-20251021"


def run_backtest(limit: float) -> tuple[dict, str]:
    """Backtest with a patched daily loss limit, returns (stats, log)."""
    source = BACKUP.read_text()
    patched = source.replace(
        "daily_loss_limit = 0.03",
        f"daily_loss_limit = {limit}",
    )
    if patched == source and limit != 0.03:
        raise SystemExit("could not patch the daily loss limit")
    STRATEGY.write_text(patched)
    try:
        before = {p.name for p in RESULTS.glob("*.zip")}
        cmd = [
            FREQTRADE, "backtesting",
            "--config", str(ROOT / "config" / "config.json"),
            "--strategy", "ConservativeTrendStrategy",
            "--timeframe", "1h",
            "--timerange", TIMERANGE,
            "--enable-protections",
            "--cache", "none",
            "--export", "trades",
        ]
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        after = {p.name for p in RESULTS.glob("*.zip")}
        new = sorted(after - before)
        if not new:
            print(proc.stdout[-2000:])
            raise SystemExit("no backtest result produced")
        import zipfile

        with zipfile.ZipFile(RESULTS / new[-1]) as archive:
            fname = [x for x in archive.namelist() if x.endswith(".json") and "config" not in x][0]
            data = json.loads(archive.read(fname))
        return data["strategy"]["ConservativeTrendStrategy"], proc.stdout
    finally:
        STRATEGY.write_text(BACKUP.read_text())


def main() -> int:
    import shutil

    shutil.copy(STRATEGY, BACKUP)
    try:
        print(f"=== backtest {TIMERANGE}: normal limit (3 %) vs. tight limit (0.2 %) ===\n")
        normal, normal_log = run_backtest(0.03)
        tight, tight_log = run_backtest(0.002)

        def summarise(stats: dict) -> tuple[int, float, int]:
            trades = stats["trades"]
            forced = sum(1 for t in trades if t.get("exit_reason") == "daily_loss_limit")
            profit = sum(t["profit_abs"] for t in trades)
            return len(trades), profit, forced

        n1, p1, f1 = summarise(normal)
        n2, p2, f2 = summarise(tight)

        print(f"{'limit':>10s} {'trades':>8s} {'profit':>10s} {'forced exits':>14s}")
        print(f"{'3 %':>10s} {n1:>8d} {p1:>10.2f} {f1:>14d}")
        print(f"{'0.2 %':>10s} {n2:>8d} {p2:>10.2f} {f2:>14d}")

        guard_logged = "DAILY LOSS LIMIT HIT" in tight_log
        entry_blocked = "rejected: daily loss limit reached" in tight_log

        print()
        print(f"guard logged the daily loss limit : {guard_logged}")
        print(f"entries rejected by the guard      : {entry_blocked}")

        ok = True
        if n2 >= n1:
            print("FAIL: the tight limit did not reduce the number of trades")
            ok = False
        if f2 == 0:
            print("FAIL: no trade was closed by the daily loss limit")
            ok = False
        if not guard_logged:
            print("FAIL: the guard did not log the daily loss limit")
            ok = False
        if not entry_blocked:
            print("FAIL: no entry was rejected by the guard")
            ok = False

        print()
        print("PASS: the daily loss circuit breaker is wired into the backtest"
              if ok else "FAIL: the daily loss circuit breaker did not behave as expected")
        return 0 if ok else 1
    finally:
        shutil.copy(BACKUP, STRATEGY)


if __name__ == "__main__":
    sys.exit(main())
