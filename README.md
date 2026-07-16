# Mega Trading Bot

This workspace contains a refactored `mega_trading_bot.py` trading bot using `ccxt` (Binance), optional ML models (XGBoost/LSTM), indicators, Telegram alerts, backtesting, logging, and a simple Flask UI.

Quick start:

1. Copy `.env.sample` to `.env` and fill in API keys and Telegram tokens.
2. Edit `config.json` as needed.
3. Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

4. Run the bot (PAPER mode by default):

```powershell
python "c:\Users\Jumongskie\C\mega_trading_bot.py"
```

5. (Optional) Start the web UI to view logs/config:

```powershell
python "c:\Users\Jumongskie\C\web_ui.py"
```

Notes:
- TensorFlow and XGBoost are optional — the code handles missing ML libs gracefully.
- Use `config.json` to switch strategies, intervals, and risk parameters.
- Review logs in `mega_trading_bot.log`.
