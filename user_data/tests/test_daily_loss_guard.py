"""
Tests for the daily loss circuit breaker (:class:`DailyLossGuard`).

These tests prove that the guard trips, latches, resets and fails closed.
They do not prove that the strategy is profitable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

NOW = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)


def _guard(strategy_module, **kwargs):
    defaults = {
        "loss_limit_pct": 0.03,
        "starting_balance": 50.0,
        "currency": "USDT",
        "tz_offset_hours": 0,
        "cache_seconds": 0,
    }
    defaults.update(kwargs)
    return strategy_module.DailyLossGuard(**defaults)


def test_loss_limit_amount(strategy_module):
    guard = _guard(strategy_module, loss_limit_pct=0.03, starting_balance=50.0)
    assert guard.loss_limit_amount() == pytest.approx(1.5)


def test_no_halt_without_loss(strategy_module, trade_factory):
    guard = _guard(strategy_module)
    trade_factory(profit_abs=-0.10, close_date=NOW.replace(tzinfo=None))
    assert guard.realized_profit_today(NOW) == pytest.approx(-0.10)
    assert guard.is_halted(NOW) is False


def test_halt_when_daily_loss_exceeded(strategy_module, trade_factory):
    guard = _guard(strategy_module)
    # -2.00 USDT realized loss with a 1.50 USDT limit -> must halt.
    trade_factory(profit_abs=-2.00, close_date=NOW.replace(tzinfo=None))
    assert guard.is_halted(NOW) is True


def test_halt_is_latching(strategy_module, trade_factory):
    guard = _guard(strategy_module)
    trade_factory(profit_abs=-2.00, close_date=NOW.replace(tzinfo=None))
    assert guard.is_halted(NOW) is True
    # Even if a later trade made the day profitable again, the guard stays
    # latched for the rest of the day.
    trade_factory(profit_abs=+5.00, close_date=(NOW + timedelta(hours=1)).replace(tzinfo=None))
    assert guard.is_halted(NOW + timedelta(hours=2)) is True


def test_guard_resets_on_new_day(strategy_module, trade_factory):
    guard = _guard(strategy_module)
    trade_factory(profit_abs=-2.00, close_date=NOW.replace(tzinfo=None))
    assert guard.is_halted(NOW) is True

    next_day = NOW + timedelta(days=1)
    # No trades closed on the new day yet -> trading may resume.
    assert guard.realized_profit_today(next_day) == pytest.approx(0.0)
    assert guard.is_halted(next_day) is False


def test_trades_from_other_days_are_ignored(strategy_module, trade_factory):
    guard = _guard(strategy_module)
    yesterday = (NOW - timedelta(days=1)).replace(tzinfo=None)
    trade_factory(profit_abs=-5.00, close_date=yesterday)
    assert guard.realized_profit_today(NOW) == pytest.approx(0.0)
    assert guard.is_halted(NOW) is False


def test_open_trades_are_ignored(strategy_module, trade_factory):
    guard = _guard(strategy_module)
    trade_factory(profit_abs=-9.00, is_open=True)
    assert guard.realized_profit_today(NOW) == pytest.approx(0.0)
    assert guard.is_halted(NOW) is False


def test_guard_fails_closed_on_db_error(strategy_module, monkeypatch):
    guard = _guard(strategy_module)

    def boom(*args, **kwargs):
        raise RuntimeError("database is gone")

    monkeypatch.setattr(strategy_module.Trade, "get_trades_proxy", boom)

    assert guard.is_halted(NOW) is True
    assert guard.error_count == 1


def test_zero_limit_disables_guard(strategy_module, trade_factory):
    guard = _guard(strategy_module, loss_limit_pct=0)
    trade_factory(profit_abs=-100.0, close_date=NOW.replace(tzinfo=None))
    assert guard.is_halted(NOW) is False


def test_cache_prevents_repeated_queries(strategy_module, trade_factory, monkeypatch):
    guard = _guard(strategy_module, cache_seconds=600)
    trade_factory(profit_abs=-0.10, close_date=NOW.replace(tzinfo=None))

    calls = []
    original = strategy_module.Trade.get_trades_proxy

    def counting(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(strategy_module.Trade, "get_trades_proxy", counting)

    guard.realized_profit_today(NOW)
    guard.realized_profit_today(NOW + timedelta(seconds=30))
    assert len(calls) == 1

    # Once the cache window passed, the history is read again.
    guard.realized_profit_today(NOW + timedelta(seconds=1200))
    assert len(calls) == 2
