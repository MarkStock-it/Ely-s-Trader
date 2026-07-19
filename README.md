# Mega Trading Bot

This project is a crypto trading bot with market data, indicators, backtesting, Telegram alerts, logging, and a Flask UI. Development and normal startup use paper trading. Live trading is disabled by default and must not be enabled during development.

## Setup

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.sample .env
```

Put credentials only in the untracked `.env` file:

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
BINANCE_API_KEY=
BINANCE_API_SECRET=
GEMINI_API_KEY=
```

`GEMINI_API_KEY` is optional. When `GEMINI_SYMBOL_SELECTOR_ENABLED` is true,
Gemini ranks only the liquid USDT spot pairs listed in `SYMBOLS`. The bot sends
calculated market summaries, never exchange credentials, and falls back to the
configured symbol order if Gemini is unavailable. Strategy and risk checks
remain authoritative for every order.

When `AI_COMMITTEE_ENABLED` is true, Yahoo Finance supplies recent headlines
for each deterministic buy candidate and Gemini records an `APPROVE`, `REJECT`,
or `ABSTAIN` opinion in `ai_evaluations`. This first phase is shadow-only: the
opinion is measurable but cannot change execution. Yahoo, Gemini, validation,
timeout, and analytics failures leave the original strategy path unchanged.

The configured private Telegram chat can also use `/ai <question>` or send a
plain-text question to chat with Gemini. `/clearai` clears the bounded in-memory
conversation. Chat receives sanitized paper-account context and has no order,
configuration, credential, or execution capability.

Never commit `.env`. A Telegram credential was previously committed to this repository. Its owner must revoke and replace that token: deleting it from the current files does not remove it from Git history.

## Paper execution

`config.json` enables `PAPER_MODE` and disables `LIVE_MODE`. Configuration validation requires exactly one mode. Live mode additionally requires both API credentials; missing credentials never select or fall back to live execution.

Paper market fills include configurable costs:

- `PAPER_FEE_RATE` charges a fee on each fill (default `0.001`).
- `PAPER_SPREAD_RATE` moves buys toward the ask and sells toward the bid (default `0.0002`).
- `PAPER_SLIPPAGE_RATE` makes market fills less favorable (default `0.0005`).
- `PAPER_ORDER_LATENCY_MS` adds optional simulated latency (default `0`).

Paper fills update cash, holdings, cost basis, fees, realized P&L, and account equity. Profit is net of entry and exit fees. This is still a simplified simulation: paper profitability does not guarantee real profitability.

## Run and test

Run the paper bot:

```powershell
python mega_trading_bot.py
```

Start the UI separately if desired:

```powershell
python web_ui.py
```

Run validation:

```powershell
python -m pytest -v
python -m compileall .
```

Export trades:

```powershell
python scripts/export_trades.py --db data/mega_trades.db --out exports
```

The current development workflow does not authorize real-money orders. Do not set `LIVE_MODE=true` unless the live-trading safeguards, credentials, and confirmation process have been deliberately reviewed outside development.
