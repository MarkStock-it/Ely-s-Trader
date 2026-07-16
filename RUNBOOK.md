# RUNBOOK — Mega Trading Bot

This document contains emergency, deploy, and operational procedures.

Emergency Stop

- To immediately halt trading: create an empty file named `STOP` in the project root (the bot checks filesystem kill-switch).
- Alternatively, stop the process or systemd service running the bot.

Rotate Keys

- If API keys or Telegram tokens were exposed, rotate them immediately via exchange console and update `config.json` / environment variables.

Restarting

- Use the process manager (systemd, supervisor) or re-run:

```powershell
# Activate venv, then run
.\.venv\Scripts\activate
python -m TRADE.mega_trading_bot
```

Observability

- Metrics: open `/metrics` endpoint from `web_ui.py` (default port 8080) for Prometheus scraping.
- Logs: check `TRADE/mega_trading_bot.log` and audit entries in the SQLite DB `data/mega_trades.db`.

Backups

- Backup the `data/mega_trades.db` file regularly. Exports can be produced with `scripts/export_trades.py`.

On-call Playbook (high level)

1. If an incident is detected (large drawdown, repeated order failures): enable kill-switch (`STOP`), investigate logs and DB.
2. Identify recent orders and reconciliations: `SELECT * FROM orders ORDER BY created_ts DESC LIMIT 50;` in the DB.
3. If needed, restore from backup and replay fills in a sandbox for post-mortem.

Contact

- Store on-call contacts and escalation paths in your secure vault.

