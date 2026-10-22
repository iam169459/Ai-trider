"""
Integration tests for the Freqtrade protections used by the strategy.

These tests really load the protection classes through Freqtrade's
``ProtectionResolver`` and feed them synthetic trades, so they verify that
the safeguards actually trigger - not just that they are configured.

Run with:
    python -m pytest user_data/tests/test_protections.py -v
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

NOW = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)


@pytest.fixture
def protection_config(base_config):
    base_config["timeframe"] = "1h"
    return base_config


def _load(method: str, protection_config: dict, extra: dict):
    from freqtrade.resolvers import ProtectionResolver

    params = {"method": method, **extra}
    return ProtectionResolver.load_protection(
        method, config=protection_config, protection_config=params
    )


# ------------------------------------------------------------------ loading
def test_protection_classes_are_loadable(strategy, protection_config):
    """All protections used by the strategy can be resolved by Freqtrade."""
    for params in strategy.protections:
        protection = _load(params["method"], protection_config, params)
        assert protection.name == params["method"]
        assert protection.short_desc()


def test_protection_manager_builds(strategy, protection_config):
    from freqtrade.plugins.protectionmanager import ProtectionManager

    manager = ProtectionManager(protection_config, strategy.protections)
    assert set(manager.name_list) == {"CooldownPeriod", "StoplossGuard", "MaxDrawdown"}


# -------------------------------------------------------------- MaxDrawdown
def test_max_drawdown_triggers_on_large_loss(strategy, protection_config, trade_factory):
    """
    3 losing trades (-5 USDT each) on a 50 USDT account -> 30% drawdown,
    which is above the configured 10% limit -> trading must be stopped.
    """
    params = next(p for p in strategy.protections if p["method"] == "MaxDrawdown")
    protection = _load("MaxDrawdown", protection_config, params)

    for offset in range(3):
        trade_factory(
            profit_abs=-5.0,
            close_date=(NOW - timedelta(hours=offset + 1)).replace(tzinfo=None),
        )

    result = protection.global_stop(date_now=NOW, side="long", starting_balance=50.0)
    assert result is not None
    assert result.lock is True
    # The reason contains the observed drawdown (0.3) and the limit (0.1).
    assert "0.3" in result.reason
    assert "0.1" in result.reason
    # The lock lasts 24 candles (1h timeframe).
    assert result.until > NOW


def test_max_drawdown_does_not_trigger_on_small_loss(strategy, protection_config, trade_factory):
    params = next(p for p in strategy.protections if p["method"] == "MaxDrawdown")
    protection = _load("MaxDrawdown", protection_config, params)

    for offset in range(3):
        trade_factory(
            profit_abs=-0.20,
            close_date=(NOW - timedelta(hours=offset + 1)).replace(tzinfo=None),
        )

    result = protection.global_stop(date_now=NOW, side="long", starting_balance=50.0)
    assert result is None


def test_max_drawdown_needs_enough_trades(strategy, protection_config, trade_factory):
    """trade_limit=3 -> a single losing trade must not stop the bot."""
    params = next(p for p in strategy.protections if p["method"] == "MaxDrawdown")
    protection = _load("MaxDrawdown", protection_config, params)

    trade_factory(profit_abs=-25.0, close_date=(NOW - timedelta(hours=1)).replace(tzinfo=None))

    result = protection.global_stop(date_now=NOW, side="long", starting_balance=50.0)
    assert result is None


# ------------------------------------------------------------ StoplossGuard
def test_stoploss_guard_triggers_after_two_stoplosses(
    strategy, protection_config, trade_factory
):
    params = next(p for p in strategy.protections if p["method"] == "StoplossGuard")
    protection = _load("StoplossGuard", protection_config, params)

    for offset in range(2):
        trade_factory(
            profit_abs=-1.0,
            exit_reason="stop_loss",
            close_date=(NOW - timedelta(hours=offset + 1)).replace(tzinfo=None),
        )

    result = protection.global_stop(date_now=NOW, side="long", starting_balance=50.0)
    assert result is not None
    assert result.lock is True


def test_stoploss_guard_ignores_winning_trades(strategy, protection_config, trade_factory):
    params = next(p for p in strategy.protections if p["method"] == "StoplossGuard")
    protection = _load("StoplossGuard", protection_config, params)

    for offset in range(4):
        trade_factory(
            profit_abs=+1.0,
            exit_reason="roi",
            close_date=(NOW - timedelta(hours=offset + 1)).replace(tzinfo=None),
        )

    result = protection.global_stop(date_now=NOW, side="long", starting_balance=50.0)
    assert result is None


# ----------------------------------------------------------- CooldownPeriod
def test_cooldown_period_locks_pair_after_exit(strategy, protection_config, trade_factory):
    params = next(p for p in strategy.protections if p["method"] == "CooldownPeriod")
    protection = _load("CooldownPeriod", protection_config, params)

    trade_factory(
        pair="BTC/USDT",
        profit_abs=+1.0,
        close_date=(NOW - timedelta(minutes=5)).replace(tzinfo=None),
    )

    result = protection.stop_per_pair(
        pair="BTC/USDT", date_now=NOW, side="long", starting_balance=50.0
    )
    assert result is not None
    assert result.lock is True
    # Cooldown of 3 candles on a 1h timeframe -> 3 hours.
    assert result.until > NOW
    assert result.until <= NOW + timedelta(hours=3, minutes=1)
