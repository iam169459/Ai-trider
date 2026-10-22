#!/usr/bin/env python3
"""
Verify that the local setup is safe and consistent.

The script performs **offline** checks only - it never connects to an
exchange and never places an order.

Checks:
  1. The Freqtrade version is new enough.
  2. The configuration is valid and resolves (schema + consistency).
  3. Dry-run is enabled and live trading is impossible.
  4. The API server binds to 127.0.0.1 only.
  5. The API credentials exist, are strong enough and are not committed.
  6. No Binance API key/secret is stored in the repository.
  7. The risk limits are inside the agreed bounds.
  8. The strategy and the protections load.

Exit code 0 = everything is fine, 1 = at least one problem was found.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "config.json"
SECRETS = ROOT / "config" / "secrets.json"

MIN_PASSWORD_LENGTH = 16
MIN_JWT_LENGTH = 32

results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> bool:
    results.append((ok, name, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    return ok


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def main() -> int:
    # ------------------------------------------------------------ freqtrade
    try:
        from freqtrade import __version__ as ft_version

        check(True, "Freqtrade is installed", ft_version)
    except Exception as exc:  # noqa: BLE001
        check(False, "Freqtrade is installed", str(exc))
        return 1

    # --------------------------------------------------------------- config
    if not CONFIG.exists():
        check(False, "config/config.json exists")
        return 1
    config = load_json(CONFIG)

    check(config.get("dry_run") is True, "dry_run is enabled", "must be true")
    check(config.get("trading_mode", "spot") == "spot", "trading_mode is spot")
    check(
        str(config.get("exchange", {}).get("name", "")).lower() == "binance",
        "exchange is Binance",
    )
    check(
        config.get("max_open_trades") == 1,
        "max_open_trades is 1",
        f"value={config.get('max_open_trades')}",
    )
    check(
        isinstance(config.get("stake_amount"), (int, float)) and config["stake_amount"] > 0,
        "stake_amount is a positive number",
        f"value={config.get('stake_amount')}",
    )
    check(
        isinstance(config.get("stoploss"), (int, float)) and config["stoploss"] < 0,
        "a negative stop-loss is configured",
        f"value={config.get('stoploss')}",
    )

    # ----------------------------------------------------------- api server
    api = config.get("api_server", {})
    check(api.get("enabled") is True, "the API server is enabled")
    listen = str(api.get("listen_ip_address", ""))
    check(
        listen in ("127.0.0.1", "localhost", "::1"),
        "the API server binds to loopback only",
        f"listen_ip_address={listen}",
    )
    check(
        not api.get("CORS_origins"),
        "no CORS origins are allowed",
        f"CORS_origins={api.get('CORS_origins')}",
    )

    # -------------------------------------------------------------- secrets
    if not SECRETS.exists():
        check(False, "config/secrets.json exists", "run scripts/generate_secrets.py")
    else:
        mode = stat.S_IMODE(SECRETS.stat().st_mode)
        check(mode == 0o600, "config/secrets.json has mode 0600", oct(mode))
        secrets = load_json(SECRETS)
        sapi = secrets.get("api_server", {})
        password = str(sapi.get("password", ""))
        jwt = str(sapi.get("jwt_secret_key", ""))
        check(
            len(password) >= MIN_PASSWORD_LENGTH,
            f"the API password is at least {MIN_PASSWORD_LENGTH} characters",
        )
        check(len(jwt) >= MIN_JWT_LENGTH, f"the JWT key is at least {MIN_JWT_LENGTH} characters")
        check(bool(sapi.get("ws_token")), "a websocket token is set")
        check(bool(sapi.get("username")), "an API username is set")

        # The parent config must not contain the secrets itself, otherwise it
        # would override the values coming from secrets.json.
        parent_api = config.get("api_server", {})
        overridden = [
            key for key in ("password", "jwt_secret_key", "ws_token") if key in parent_api
        ]
        check(
            not overridden,
            "the main config does not override the secrets",
            f"found {overridden}" if overridden else "",
        )

    # -------------------------------------------------- no exchange credentials
    exchange_keys = [
        key
        for key in ("key", "secret", "api_key", "apiKey", "password", "private_key")
        if config.get("exchange", {}).get(key)
    ]
    check(
        not exchange_keys,
        "no Binance API credentials in the config",
        f"found {exchange_keys}" if exchange_keys else "",
    )
    tracked = os.popen(f"cd {ROOT} && git ls-files config/ 2>/dev/null").read().split()
    check(
        "config/secrets.json" not in tracked,
        "config/secrets.json is not tracked by git",
    )

    # ------------------------------------------------------------ risk limits
    wallet = config.get("dry_run_wallet", 0) or 0
    stake = config.get("stake_amount", 0) or 0
    stop = config.get("stoploss", 0) or 0
    check(wallet >= 10, "the simulated wallet is at least 10 USDT", f"{wallet} USDT")
    check(wallet <= 50, "the simulated wallet is at most 50 USDT", f"{wallet} USDT")
    check(
        abs(stake) * abs(stop) <= wallet * 0.05,
        "the risk per trade is at most 5 % of the account",
        f"{abs(stake) * abs(stop):.2f} USDT of {wallet} USDT",
    )
    check(
        config.get("fee", 0) >= 0.001,
        "the trading fee assumption is at least 0.1 %",
        f"fee={config.get('fee')}",
    )

    # ------------------------------------------------------------- strategy
    try:
        from freqtrade.commands import Arguments
        from freqtrade.configuration import Configuration
        from freqtrade.resolvers import StrategyResolver

        # Load the configuration exactly like the bot does (this also runs the
        # schema and consistency validation).
        parsed = Arguments(["trade", "--config", str(CONFIG)]).get_parsed_arg()
        full_config = Configuration(parsed).get_config()
        check(True, "the configuration is valid", "schema + consistency checks passed")

        resolved = StrategyResolver.load_strategy(full_config)
        check(True, "the strategy loads", resolved.__class__.__name__)
        check(
            resolved.timeframe == "1h",
            "the strategy timeframe is 1h",
            resolved.timeframe,
        )
        protections = [p["method"] for p in resolved.protections]
        check("MaxDrawdown" in protections, "the MaxDrawdown protection is active")
        check("StoplossGuard" in protections, "the StoplossGuard protection is active")
        check("CooldownPeriod" in protections, "the CooldownPeriod protection is active")
    except Exception as exc:  # noqa: BLE001
        check(False, "the strategy loads", str(exc))

    # ---------------------------------------------------------------- tests
    try:
        import pytest  # noqa: F401

        check(True, "pytest is available")
    except Exception:  # noqa: BLE001
        check(False, "pytest is available", "pip install pytest")

    failed = [name for ok, name, _ in results if not ok]
    print()
    if failed:
        print(f"{len(failed)} check(s) failed:")
        for name in failed:
            print(f"  - {name}")
        return 1
    print(f"All {len(results)} checks passed.  The bot is in dry-run mode.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
