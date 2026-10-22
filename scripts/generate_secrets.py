#!/usr/bin/env python3
"""
Generate the FreqUI / REST API credentials for the local dashboard.

The generated file (``config/secrets.json``) contains **secrets** and is
therefore:

* created with ``0600`` permissions,
* listed in ``.gitignore``,
* never printed to stdout in full.

The FreqUI credentials are read by Freqtrade through ``add_config_files``
(``config/config.json`` -> ``config/secrets.json``).  The main config file
deliberately does **not** contain the secret keys, because Freqtrade gives
priority to the parent config over the files listed in ``add_config_files``.

Usage:
    python3 scripts/generate_secrets.py            # create config/secrets.json
    python3 scripts/generate_secrets.py --force    # overwrite existing file
    python3 scripts/generate_secrets.py --print    # also print the values
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS_FILE = ROOT / "config" / "secrets.json"

# Password alphabet: avoid characters that are easy to confuse in a browser
# login form or that need shell escaping.
PASSWORD_ALPHABET = string.ascii_letters + string.digits + "!@#%^*_-+="
USERNAME_ALPHABET = string.ascii_lowercase + string.digits


def _password(length: int = 28) -> str:
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))


def _username(length: int = 12) -> str:
    return "trader_" + "".join(secrets.choice(USERNAME_ALPHABET) for _ in range(length))


def build_secrets() -> dict:
    return {
        "$schema": "https://schema.freqtrade.io/schema.json",
        "api_server": {
            "username": _username(),
            "password": _password(),
            # Schema requires at least 32 characters.
            "jwt_secret_key": secrets.token_urlsafe(48),
            "ws_token": secrets.token_urlsafe(32),
        },
    }


def write_secrets(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Create with restrictive permissions from the start.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=4)
        fh.write("\n")
    os.chmod(path, 0o600)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="overwrite an existing secrets.json"
    )
    parser.add_argument(
        "--print",
        dest="print_values",
        action="store_true",
        help="print the generated credentials (only do this on a trusted machine)",
    )
    parser.add_argument(
        "--output", type=Path, default=SECRETS_FILE, help="target file"
    )
    args = parser.parse_args()

    target: Path = args.output
    if target.exists() and not args.force:
        print(f"{target} already exists - refusing to overwrite (use --force).")
        return 1

    data = build_secrets()
    write_secrets(target, data)

    print(f"Wrote {target} (permissions 0600).")
    print("These credentials protect the local FreqUI dashboard on 127.0.0.1.")
    if args.print_values:
        api = data["api_server"]
        print("\n--- FreqUI login ---")
        print(f"username: {api['username']}")
        print(f"password: {api['password']}")
        print("url:      http://127.0.0.1:8080")
    else:
        print("Run with --print to show the credentials, or read the file directly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
