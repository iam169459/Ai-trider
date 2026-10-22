"""
Tests for :class:`ConservativeTrendStrategy`.

Scope: the risk safeguards (entry blocking, forced exit) and the
signal logic.  These tests say nothing about profitability.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

NOW = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)


def _ohlcv(rows: int = 300) -> pd.DataFrame:
    """Synthetic but realistic looking 1h candles."""
    rng = np.random.default_rng(42)
    price = 100.0
    closes = []
    for _ in range(rows):
        price *= 1 + rng.normal(0.0005, 0.006)
        closes.append(price)
    close = np.array(closes)
    high = close * (1 + abs(rng.normal(0, 0.002, rows)))
    low = close * (1 - abs(rng.normal(0, 0.002, rows)))
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    volume = rng.uniform(50, 150, rows)
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=rows, freq="1h", tz="UTC"),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


# ---------------------------------------------------------------- indicators
def test_populate_indicators_adds_columns(strategy):
    df = _ohlcv()
    result = strategy.populate_indicators(df.copy(), {"pair": "BTC/USDT"})
    for column in ("ema_fast", "ema_slow", "rsi", "atr", "volume_mean"):
        assert column in result.columns
    # The slow EMA needs 200 candles, the last rows must not be NaN.
    tail = result.tail(10)
    assert not tail["ema_slow"].isna().any()
    assert tail["rsi"].between(0, 100).all()


# -------------------------------------------------------------- entry logic
def _entry_frame(rows: int = 60, **last_row) -> pd.DataFrame:
    """
    Frame with pre-computed indicators.

    The default describes a healthy uptrend where the last candle crosses the
    RSI entry threshold upwards -> an entry is expected.
    """
    ema_slow = np.linspace(90.0, 95.0, rows)
    ema_fast = ema_slow + 5.0
    close = ema_fast + 1.0
    rsi = np.full(rows, 50.0)
    rsi[-2] = 44.0  # previous candle below the entry threshold
    volume = np.full(rows, 120.0)
    volume_mean = np.full(rows, 100.0)

    frame = pd.DataFrame(
        {
            "close": close,
            "volume": volume,
            "volume_mean": volume_mean,
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "rsi": rsi,
        }
    )
    for column, value in last_row.items():
        if isinstance(value, (list, tuple)):
            frame[column] = value
        else:
            frame.loc[frame.index[-1], column] = value
    return frame


def test_entry_signal_fired_in_uptrend(strategy):
    df = _entry_frame()
    result = strategy.populate_entry_trend(df.copy(), {"pair": "BTC/USDT"})
    assert result["enter_long"].iloc[-1] == 1
    assert result["enter_tag"].iloc[-1] == "trend_pullback"


def test_no_entry_when_rsi_too_high(strategy):
    df = _entry_frame(rsi=80.0)
    result = strategy.populate_entry_trend(df.copy(), {"pair": "BTC/USDT"})
    assert result["enter_long"].iloc[-1] == 0


def test_no_entry_in_downtrend(strategy):
    df = _entry_frame()
    df["ema_fast"] = df["ema_slow"] - 1.0
    result = strategy.populate_entry_trend(df.copy(), {"pair": "BTC/USDT"})
    assert result["enter_long"].iloc[-1] == 0


def test_no_entry_when_slow_trend_is_falling(strategy):
    df = _entry_frame()
    df["ema_slow"] = np.linspace(95.0, 90.0, len(df))
    df["ema_fast"] = df["ema_slow"] + 5.0
    df["close"] = df["ema_fast"] + 1.0
    result = strategy.populate_entry_trend(df.copy(), {"pair": "BTC/USDT"})
    assert result["enter_long"].iloc[-1] == 0


def test_no_entry_without_rsi_recovery(strategy):
    # RSI already above the band on the previous candle -> no "cross up".
    df = _entry_frame()
    df.loc[df.index[-2], "rsi"] = 55.0
    result = strategy.populate_entry_trend(df.copy(), {"pair": "BTC/USDT"})
    assert result["enter_long"].iloc[-1] == 0


def test_no_entry_on_low_volume(strategy):
    df = _entry_frame(volume=10.0)
    result = strategy.populate_entry_trend(df.copy(), {"pair": "BTC/USDT"})
    assert result["enter_long"].iloc[-1] == 0


def test_entry_column_is_usable_when_no_signal(strategy):
    """
    Regression test: with pandas 3.x an uninitialised column assignment can
    produce a "void" dtype that breaks Freqtrade's ``== 1`` check.
    """
    df = _entry_frame(rsi=80.0)
    result = strategy.populate_entry_trend(df.copy(), {"pair": "BTC/USDT"})
    assert (result["enter_long"] == 1).any() in (True, False)
    assert result["enter_long"].dtype.kind in "iuf"


# -------------------------------------------------------------- exit logic
def test_no_exit_on_trend_break(strategy):
    """A close below the slow EMA is not an exit - the stop-loss handles risk."""
    df = pd.DataFrame(
        {
            "close": [90.0],
            "ema_fast": [100.0],
            "ema_slow": [95.0],
            "rsi": [55.0],
        }
    )
    result = strategy.populate_exit_trend(df.copy(), {"pair": "BTC/USDT"})
    assert result["exit_long"].iloc[-1] == 0


def test_exit_on_overbought(strategy):
    df = pd.DataFrame(
        {
            "close": [105.0],
            "ema_fast": [100.0],
            "ema_slow": [95.0],
            "rsi": [85.0],
        }
    )
    result = strategy.populate_exit_trend(df.copy(), {"pair": "BTC/USDT"})
    assert result["exit_long"].iloc[-1] == 1
    assert result["exit_tag"].iloc[-1] == "rsi_overbought"


def test_exit_column_is_usable_without_signal(strategy):
    """Regression test for the pandas 3.x "void" dtype problem."""
    df = pd.DataFrame(
        {
            "close": [105.0],
            "ema_fast": [100.0],
            "ema_slow": [95.0],
            "rsi": [55.0],
        }
    )
    result = strategy.populate_exit_trend(df.copy(), {"pair": "BTC/USDT"})
    assert result["exit_long"].dtype.kind in "iuf"
    assert (result["exit_long"] == 1).any() in (True, False)


# ------------------------------------------------------------ risk controls
def test_confirm_trade_entry_allows_normal_entry(strategy):
    assert (
        strategy.confirm_trade_entry(
            pair="BTC/USDT",
            order_type="limit",
            amount=0.0002,
            rate=100.0,
            time_in_force="GTC",
            current_time=NOW,
            entry_tag="trend_pullback",
            side="long",
        )
        is True
    )


def test_confirm_trade_entry_blocks_shorts(strategy):
    assert (
        strategy.confirm_trade_entry(
            pair="BTC/USDT",
            order_type="limit",
            amount=0.0002,
            rate=100.0,
            time_in_force="GTC",
            current_time=NOW,
            entry_tag="trend_pullback",
            side="short",
        )
        is False
    )


def test_confirm_trade_entry_blocked_after_daily_loss(strategy, trade_factory):
    trade_factory(profit_abs=-5.0, close_date=NOW.replace(tzinfo=None))
    assert (
        strategy.confirm_trade_entry(
            pair="BTC/USDT",
            order_type="limit",
            amount=0.0002,
            rate=100.0,
            time_in_force="GTC",
            current_time=NOW,
            entry_tag="trend_pullback",
            side="long",
        )
        is False
    )


def test_custom_exit_forced_after_daily_loss(strategy, trade_factory):
    trade_factory(profit_abs=-5.0, close_date=NOW.replace(tzinfo=None))
    result = strategy.custom_exit(
        pair="BTC/USDT",
        trade=None,
        current_time=NOW,
        current_rate=100.0,
        current_profit=-0.01,
    )
    assert result == "daily_loss_limit"


def test_custom_exit_none_when_healthy(strategy, trade_factory):
    trade_factory(profit_abs=-0.10, close_date=NOW.replace(tzinfo=None))
    result = strategy.custom_exit(
        pair="BTC/USDT",
        trade=None,
        current_time=NOW,
        current_rate=100.0,
        current_profit=0.01,
    )
    assert result is None


def test_starting_balance_uses_available_capital(strategy):
    assert strategy._starting_balance() == pytest.approx(50.0)


def test_daily_loss_guard_uses_configured_balance(strategy):
    guard = strategy._get_guard()
    assert guard.starting_balance == pytest.approx(50.0)
    assert guard.loss_limit_amount() == pytest.approx(1.5)


# ------------------------------------------------------------- protections
def test_protections_are_configured(strategy):
    methods = [p["method"] for p in strategy.protections]
    assert "MaxDrawdown" in methods
    assert "StoplossGuard" in methods
    assert "CooldownPeriod" in methods


def test_max_drawdown_protection_is_conservative(strategy):
    dd = next(p for p in strategy.protections if p["method"] == "MaxDrawdown")
    assert dd["max_allowed_drawdown"] <= 0.10
    assert dd["calculation_mode"] == "equity"
