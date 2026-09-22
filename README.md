# VPN subscription health checker

This project fetches proxy/VPN subscriptions, validates the parsed nodes with `sing-box`, and publishes healthy outputs. It can run once from the command line, on a schedule through GitHub Actions, or as an admin-only Telegram bot.

## What it does

1. Reads subscription URLs from `subscriptions.txt` or the Telegram bot database.
2. Parses VMess, VLESS, Trojan, Shadowsocks, and common Clash YAML entries.
3. Filters malformed nodes before starting `sing-box`.
4. Runs delay checks through the local Clash API.
5. Optionally checks TCP reachability from check-host nodes in a selected country.
6. Optionally performs a small sequential speed test.
7. Writes protocol, country, Iran-reachable, and fast-node outputs.

## Run locally

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements_run_once.txt
export TELEGRAM_BOT_TOKEN=...
export ADMIN_CHAT_ID=...
export SINGBOX_PATH=/path/to/sing-box
python run_once.py
```

`subscriptions.txt` is one HTTP(S) subscription URL per line. Empty lines are ignored. Subscription responses are capped at 2 MiB to avoid unbounded memory use.

## GitHub Actions

`.github/workflows/healthcheck.yml` runs manually or every two hours. It requires `TELEGRAM_BOT_TOKEN` and `ADMIN_CHAT_ID` repository secrets.

The workflow writes generated files back to the repository. Those files can contain live proxy endpoints or credentials. Use a **private repository** or change the workflow to publish artifacts through a private destination before enabling it on public code. Rotate any endpoint or token that has already been exposed publicly.

The workflow uses a pinned `sing-box` version, bounded network operations, concurrency control, and a conditional commit so it does not create a commit when outputs are unchanged.

## Telegram bot

Install the bot dependencies with `pip install -r requirements.txt`. Required variables are `TELEGRAM_BOT_TOKEN` and `ADMIN_CHAT_ID`. Only the configured admin chat can use bot commands. Subscription URLs are validated and stored in `bot.db`, which is ignored by Git.

## Configuration

Useful optional variables include `REFRESH_HOURS`, `TEST_URL`, `TEST_TIMEOUT_MS`, `MAX_CONCURRENCY`, `CHECK_HOST_COUNTRY`, `CHECK_HOST_MAX_ENDPOINTS`, `CHECK_HOST_CONCURRENCY`, `SPEED_TEST_ENABLED`, `SPEED_TEST_MAX_NODES`, `SPEED_TEST_THRESHOLD_KIB_S`, and `GEOIP_MIN_INTERVAL_SECONDS` (default `1.5`). Output paths must be relative paths inside the workspace; absolute paths and `..` path components are rejected.

## Development

```bash
pip install -r requirements-dev.txt
pytest -q
ruff check .
python -m compileall -q .
```

Network-dependent health and speed checks are deliberately not part of the unit-test suite.
