"""
Shared pytest fixtures for the conservative trading bot.

The tests run completely offline - no exchange connection, no network.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STRATEGY_DIR = ROOT / "user_data" / "strategies"
STRATEGY_FILE = STRATEGY_DIR / "ConservativeTrendStrategy.py"


def _load_strategy_module():
    """Import the strategy file directly (it is not a package)."""
    if str(STRATEGY_DIR) not in sys.path:
        sys.path.insert(0, str(STRATEGY_DIR))
    spec = importlib.util.spec_from_file_location("ConservativeTrendStrategy", STRATEGY_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ConservativeTrendStrategy"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def strategy_module():
    return _load_strategy_module()


@pytest.fixture
def base_config() -> dict:
    """A minimal but valid configuration for the strategy under test."""
    return {
        "max_open_trades": 1,
        "stake_currency": "USDT",
        "stake_amount": 20,
        "tradable_balance_ratio": 0.99,
        "available_capital": 50,
        "dry_run": True,
        "dry_run_wallet": 50,
        "timeframe": "1h",
        "fee": 0.001,
        "strategy": "ConservativeTrendStrategy",
        "exchange": {"name": "binance", "pair_whitelist": ["BTC/USDT", "ETH/USDT"]},
        "candle_type_def": "spot",
        "entry_pricing": {"price_side": "same", "use_order_book": True, "order_book_top": 1},
        "exit_pricing": {"price_side": "same", "use_order_book": True, "order_book_top": 1},
    }


@pytest.fixture
def strategy(strategy_module, base_config):
    """A strategy instance with an isolated in-memory database."""
    from freqtrade.persistence import init_db
    from freqtrade.persistence.models import Trade

    init_db("sqlite://")
    Trade.use_db = True
    inst = strategy_module.ConservativeTrendStrategy(base_config)
    yield inst
    Trade.session.query(Trade).delete()
    Trade.commit()


@pytest.fixture
def db():
    """In-memory trade database (fresh per test)."""
    from freqtrade.persistence import init_db
    from freqtrade.persistence.models import Trade

    init_db("sqlite://")
    Trade.use_db = True
    yield Trade
    Trade.session.query(Trade).delete()
    Trade.commit()


def make_trade(
    trade_model,
    *,
    pair: str = "BTC/USDT",
    stake_amount: float = 20.0,
    profit_abs: float = 0.0,
    close_date: datetime | None = None,
    is_open: bool = False,
    exit_reason: str = "roi",
    open_date: datetime | None = None,
):
    """Create and persist a (closed) trade in the database."""
    now = datetime.now(UTC).replace(tzinfo=None)
    open_dt = open_date or (now - timedelta(hours=2))
    close_dt = close_date or now

    trade = trade_model(
        pair=pair,
        stake_currency="USDT",
        base_currency=pair.split("/")[0],
        is_open=is_open,
        amount=0.0001,
        amount_requested=0.0001,
        stake_amount=stake_amount,
        max_stake_amount=stake_amount,
        open_rate=100.0,
        open_rate_requested=100.0,
        open_date=open_dt,
        close_date=None if is_open else close_dt,
        close_rate=None if is_open else 100.0,
        close_rate_requested=None if is_open else 100.0,
        fee_open=0.1,
        fee_close=0.1,
        close_profit=None if is_open else (profit_abs / stake_amount),
        close_profit_abs=None if is_open else profit_abs,
        realized_profit=0.0,
        exchange="binance",
        strategy="ConservativeTrendStrategy",
        timeframe=60,
        is_short=False,
        leverage=1.0,
        exit_reason=None if is_open else exit_reason,
        enter_tag="trend_pullback",
    )
    trade_model.session.add(trade)
    trade_model.commit()
    return trade


@pytest.fixture
def trade_factory(db):
    """Factory fixture that persists trades into the in-memory database."""

    def _factory(**kwargs):
        return make_trade(db, **kwargs)

    return _factory
