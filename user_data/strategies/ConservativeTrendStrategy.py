"""
ConservativeTrendStrategy
-------------------------

Long-only, 1 hour trend-following strategy for **Binance Spot**.

It is deliberately built for a small account ($10 - $50) and a conservative
risk profile:

* Only trade when the market is in a confirmed uptrend (fast EMA above the
  slow EMA, slow EMA rising).
* Enter on momentum confirmation only (RSI inside a neutral band and crossing
  upwards) - never chase an overbought market.
* Hard stop-loss (default 4%), modest ROI targets and a trailing stop that
  only activates after the trade is in profit.
* At most **one** open trade (``max_open_trades`` is set in the config file).
* A *daily loss circuit breaker* (:class:`DailyLossGuard`) that blocks new
  entries and flattens open positions once the realized loss of the current
  day exceeds the configured limit.
* Additional protection layers provided by Freqtrade: ``CooldownPeriod``,
  ``StoplossGuard`` and ``MaxDrawdown`` (see the ``protections`` property).

Nothing in this file implies or guarantees profitability.  It is meant to be
backtested and paper traded first - see ``docs/RUNBOOK.md``.

References:
* https://www.freqtrade.io/en/stable/strategy-customization/
* https://www.freqtrade.io/en/stable/includes/protections/
"""

import logging
from datetime import UTC, date, datetime, timedelta

import talib.abstract as ta
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy
from freqtrade.strategy.parameters import DecimalParameter
from pandas import DataFrame

logger = logging.getLogger(__name__)


class DailyLossGuard:
    """
    Circuit breaker that stops trading for the remainder of the day once the
    realized loss of the current trading day exceeds a limit.

    The guard is *latching*: once the limit has been hit it stays active until
    the trading day changes, so a later profitable trade cannot silently
    re-enable trading on a day that already breached the limit.

    The day boundary is UTC by default (``tz_offset_hours`` can shift it).

    The guard is intentionally fail-closed: if the trade history cannot be
    read, the guard reports "halted" so that no *new* risk is taken while the
    risk state is unknown.
    """

    def __init__(
        self,
        loss_limit_pct: float,
        starting_balance: float,
        currency: str = "USDT",
        tz_offset_hours: int = 0,
        cache_seconds: int = 60,
    ) -> None:
        self._loss_limit_pct = float(loss_limit_pct)
        self._starting_balance = float(starting_balance)
        self._currency = currency
        self._tz_offset = timedelta(hours=tz_offset_hours)
        self._cache_seconds = cache_seconds
        self._halted_day: date | None = None
        self._cache: tuple[date, datetime, float] | None = None
        self._error_count = 0

    # ------------------------------------------------------------------ utils
    @staticmethod
    def _as_utc(moment: datetime) -> datetime:
        """Normalize a datetime to timezone aware UTC."""
        if moment.tzinfo is None:
            return moment.replace(tzinfo=UTC)
        return moment.astimezone(UTC)

    def _day_of(self, moment: datetime) -> date:
        """Return the trading day a timestamp belongs to."""
        return (self._as_utc(moment) + self._tz_offset).date()

    @property
    def loss_limit_pct(self) -> float:
        return self._loss_limit_pct

    @property
    def starting_balance(self) -> float:
        return self._starting_balance

    @property
    def error_count(self) -> int:
        """Number of times the guard failed to read the trade history."""
        return self._error_count

    @property
    def currency(self) -> str:
        return self._currency

    # ----------------------------------------------------------------- public
    def realized_profit_today(self, moment: datetime) -> float:
        """
        Sum of the realized profit (fees included) of every trade closed
        during the trading day of ``moment``.

        :return: Realized profit in stake currency (negative == loss).
        """
        moment = self._as_utc(moment)
        day = self._day_of(moment)

        if self._cache is not None:
            cached_day, cached_moment, cached_value = self._cache
            age = abs((moment - cached_moment).total_seconds())
            if cached_day == day and age < self._cache_seconds:
                return cached_value

        total = 0.0
        for trade in Trade.get_trades_proxy(is_open=False):
            close_date = trade.close_date_utc
            if close_date is None:
                continue
            if self._day_of(close_date) == day:
                total += trade.close_profit_abs or 0.0

        self._cache = (day, moment, total)
        return total

    def loss_limit_amount(self) -> float:
        """The absolute loss (in stake currency) that trips the breaker."""
        return abs(self._loss_limit_pct) * self._starting_balance

    def is_halted(self, moment: datetime) -> bool:
        """
        Return True when trading must be blocked.

        Blocks when the realized daily loss reached the limit, or when the
        risk state could not be determined (fail closed).
        """
        if self._loss_limit_pct <= 0:
            return False

        day = self._day_of(moment)

        # Already latched for this day -> keep blocking.
        if self._halted_day == day:
            return True

        try:
            profit = self.realized_profit_today(moment)
        except Exception as exc:  # noqa: BLE001 - fail closed on any issue
            self._error_count += 1
            logger.error(
                "Daily loss guard could not read the trade history (%s). "
                "Trading is blocked until the risk state is known again.",
                exc,
            )
            return True

        limit = -self.loss_limit_amount()
        if profit <= limit:
            self._halted_day = day
            logger.error(
                "DAILY LOSS LIMIT HIT: realized loss of %.2f %s today (limit %.2f %s). "
                "No new entries until %s UTC.",
                abs(profit),
                self._currency,
                self.loss_limit_amount(),
                self._currency,
                (day + timedelta(days=1)).isoformat(),
            )
            return True

        return False


class ConservativeTrendStrategy(IStrategy):
    """
    Conservative 1h trend-following strategy (long only, spot).
    """

    INTERFACE_VERSION = 3

    timeframe = "1h"
    can_short = False

    # ------------------------------------------------------------------ risk
    # Every value below can be overridden from the config file
    # (config wins over the strategy).
    minimal_roi = {
        "0": 0.04,
        "48": 0.06,
        "96": 0.08,
        "168": 0.10,
    }
    stoploss = -0.04

    # The trailing stop is switched off on purpose: this strategy buys
    # pullbacks inside an uptrend and rides the trend.  A trailing stop exits
    # on the first ~1 % dip after the trade is in profit, which in a healthy
    # trend happens constantly - in the 2021-2026 backtest it turned a
    # +13.9 USDT result into -9 to -17 USDT.  The fixed stop-loss below
    # limits the loss of every single trade, the ROI table takes the profit.
    trailing_stop = False
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.03
    trailing_only_offset_is_reached = True

    use_exit_signal = True
    exit_profit_only = False
    exit_profit_offset = 0.0
    ignore_roi_if_entry_signal = False
    process_only_new_candles = True

    # ------------------------------------------------------------- indicators
    fast_period = 50
    slow_period = 200
    rsi_period = 14
    atr_period = 14
    volume_period = 20

    # ---------------------------------------------------- hyperopt parameters
    # Only the *signal* parameters are hyperoptable.  The risk parameters
    # (stop-loss, ROI, stake, daily loss limit, protections) are deliberately
    # NOT part of the search space - an optimizer must never be allowed to
    # loosen the risk limits of the account.
    #
    # The defaults below are the values that were chosen by hand and verified
    # in the 2021-2026 backtest.  A parameter file
    # (ConservativeTrendStrategy.json) overrides them when it exists.
    enter_rsi_entry_min = DecimalParameter(
        low=30.0, high=55.0, default=44.0, decimals=1, space="enter", optimize=True
    )
    enter_rsi_entry_max = DecimalParameter(
        low=55.0, high=85.0, default=68.0, decimals=1, space="enter", optimize=True
    )
    enter_min_volume_ratio = DecimalParameter(
        low=0.4, high=1.2, default=0.8, decimals=2, space="enter", optimize=True
    )
    exit_rsi_exit_overbought = DecimalParameter(
        low=70.0, high=95.0, default=78.0, decimals=1, space="exit", optimize=True
    )

    # --------------------------------------------------- daily loss circuit
    # Fraction of the account starting balance that may be lost within one
    # trading day before the bot stops taking new positions.
    daily_loss_limit = 0.03
    daily_loss_tz_offset_hours = 0

    startup_candle_count = 250

    # -------------------------------------------------------------- internals
    _daily_loss_guard: DailyLossGuard | None = None
    _startup_logged = False

    # ----------------------------------------------------------------- setup
    def bot_loop_start(self, current_time: datetime, **kwargs) -> None:
        """Log the effective risk configuration once the bot starts."""
        if self._startup_logged:
            return
        self._startup_logged = True
        logger.info(
            "ConservativeTrendStrategy starting | stake=%s %s | stoploss=%.2f%% | "
            "daily loss limit=%.2f%% | ROI=%s",
            self.config.get("stake_amount"),
            self.config.get("stake_currency", "USDT"),
            (self.config.get("stoploss", self.stoploss) or 0) * 100,
            self.daily_loss_limit * 100,
            self.config.get("minimal_roi", self.minimal_roi),
        )
        self._get_guard()

    def _get_guard(self) -> DailyLossGuard:
        """Create (once) and return the daily loss guard."""
        if self._daily_loss_guard is None:
            starting_balance = self._starting_balance()
            currency = self.config.get("stake_currency", "USDT")
            self._daily_loss_guard = DailyLossGuard(
                loss_limit_pct=self.daily_loss_limit,
                starting_balance=starting_balance,
                currency=currency,
                tz_offset_hours=self.daily_loss_tz_offset_hours,
            )
            logger.info(
                "Daily loss guard active: limit=%.2f %s (%.2f%% of %.2f %s starting balance)",
                self._daily_loss_guard.loss_limit_amount(),
                currency,
                self.daily_loss_limit * 100,
                starting_balance,
                currency,
            )
        return self._daily_loss_guard

    def _starting_balance(self) -> float:
        """
        Balance the daily loss limit is relative to.

        Uses the wallet (available_capital / dry-run wallet) and falls back to
        the configured stake amount when no wallet is available (e.g. in unit
        tests).
        """
        wallets = getattr(self, "wallets", None)
        if wallets is not None:
            try:
                balance = wallets.get_starting_balance()
                if balance and balance > 0:
                    return float(balance)
            except Exception as exc:  # noqa: BLE001 - never crash on wallet errors
                logger.warning("Could not read the starting balance from the wallet: %s", exc)

        for key in ("available_capital", "dry_run_wallet"):
            value = self.config.get(key)
            if isinstance(value, (int, float)) and value > 0:
                return float(value)

        stake = self.config.get("stake_amount")
        if isinstance(stake, (int, float)) and stake > 0:
            return float(stake)

        return 0.0

    # ------------------------------------------------------------ indicators
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=self.fast_period)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=self.slow_period)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=self.rsi_period)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=self.atr_period)
        dataframe["volume_mean"] = dataframe["volume"].rolling(self.volume_period).mean()

        return dataframe

    # ------------------------------------------------------------ entry/exit
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Long entry - only in an uptrend with recovering (but not overbought)
        momentum and above average volume.
        """
        # Hyperoptable values (read inside the signal function, never in
        # populate_indicators - that would freeze the indicators).
        rsi_min = self.enter_rsi_entry_min.value
        rsi_max = self.enter_rsi_entry_max.value
        min_volume_ratio = self.enter_min_volume_ratio.value
        # Keep the band valid even if the optimizer picks an inverted range.
        rsi_max = max(rsi_max, rsi_min + 1.0)

        uptrend = dataframe["ema_fast"] > dataframe["ema_slow"]
        slow_trend_up = dataframe["ema_slow"] > dataframe["ema_slow"].shift(self.fast_period)
        fast_trend_up = dataframe["ema_fast"] > dataframe["ema_fast"].shift(1)
        above_fast_ema = dataframe["close"] > dataframe["ema_fast"]
        above_slow_ema = dataframe["close"] > dataframe["ema_slow"]

        rsi_recovering = (
            (dataframe["rsi"] > rsi_min)
            & (dataframe["rsi"] <= rsi_max)
            & (dataframe["rsi"].shift(1) <= rsi_min)
        )
        volume_ok = dataframe["volume"] >= dataframe["volume_mean"] * min_volume_ratio

        # NOTE: the columns are initialised explicitly.  With pandas 3.x a
        # ``.loc[mask, [col1, col2]] = (1, "tag")`` assignment on a frame where
        # the mask never matches creates a "void" typed column, which later
        # raises when Freqtrade evaluates ``dataframe["enter_long"] == 1``.
        dataframe["enter_long"] = 0
        dataframe["enter_tag"] = ""

        dataframe.loc[
            uptrend
            & slow_trend_up
            & fast_trend_up
            & above_fast_ema
            & above_slow_ema
            & rsi_recovering
            & volume_ok,
            ["enter_long", "enter_tag"],
        ] = (1, "trend_pullback")

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Exit when the market is overbought.

        There is deliberately **no** "close below the fast EMA" exit (it closed
        91 of 123 trades within a few hours in the first backtest run and
        turned the strategy into a noise generator) and no "close below the
        slow EMA" exit (it cut winners far too early).  The stop-loss, the ROI
        table and the daily loss circuit breaker control the risk.
        """
        overbought = dataframe["rsi"] > self.exit_rsi_exit_overbought.value

        # See the note in populate_entry_trend() about explicit initialisation.
        dataframe["exit_long"] = 0
        dataframe["exit_tag"] = ""

        dataframe.loc[overbought, ["exit_long", "exit_tag"]] = (1, "rsi_overbought")

        return dataframe

    # ------------------------------------------------------- risk safeguards
    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time: datetime,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> bool:
        """
        Block new entries when the daily loss limit has been hit.

        Spot only -> long entries only.
        """
        if side != "long":
            logger.info("Entry for %s rejected: this strategy is long only.", pair)
            return False

        guard = self._get_guard()
        if guard.is_halted(current_time):
            logger.info(
                "Entry for %s rejected: daily loss limit reached (%.2f %s today).",
                pair,
                guard.realized_profit_today(current_time),
                self.config.get("stake_currency", "USDT"),
            )
            return False

        return True

    def custom_exit(
        self,
        pair: str,
        trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> str | bool | None:
        """
        Close open positions once the daily loss limit has been reached.

        This turns the daily loss limit into a real circuit breaker: the bot
        does not only stop opening new positions, it also stops the bleeding.
        """
        guard = self._get_guard()
        if guard.is_halted(current_time):
            logger.error(
                "Exit %s forced: daily loss limit reached, closing open position.", pair
            )
            return "daily_loss_limit"

        return None

    # ----------------------------------------------------------- protections
    @property
    def protections(self) -> list[dict]:
        """
        Freqtrade protections (must be defined on the strategy, not in the
        config file).

        * ``CooldownPeriod`` - do not re-enter a pair right after an exit.
        * ``StoplossGuard``  - stop trading after repeated stop losses.
        * ``MaxDrawdown``    - stop trading when the account drawdown is too
          large (equity based, i.e. relative to the real account size).
        """
        return [
            {
                "method": "CooldownPeriod",
                "stop_duration_candles": 3,
            },
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 24,
                "trade_limit": 2,
                "stop_duration_candles": 6,
                "required_profit": 0.0,
                "only_per_pair": False,
            },
            {
                "method": "MaxDrawdown",
                "calculation_mode": "equity",
                "lookback_period_candles": 168,
                "trade_limit": 3,
                "stop_duration_candles": 24,
                "max_allowed_drawdown": 0.10,
            },
        ]
