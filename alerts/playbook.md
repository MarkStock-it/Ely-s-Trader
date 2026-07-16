# Alerts & Incident Playbook

Purpose: short runbook for handling system incidents and alerts.

Alert types

- High error rate (exceptions): check logs, restart worker if needed.
- Repeated order failures / circuit-breaker triggered: pause trading, investigate exchange connectivity and API key validity.
- Unexpected reconciler closures or missing fills: run reconciliation and export trades.
- Large drawdown / margin call risk: immediate kill-switch and manual emergency close.

Initial Triage

1. Confirm alert payload (Prometheus alert or Telegram message).
2. Check `/health` and `/status` endpoints and tail `mega_trading_bot.log`.
3. Run `scripts/export_trades.py` to create CSV snapshots for the SRE/Compliance team.

Mitigation Steps

- For connectivity: restart network interface, confirm DNS, check exchange status pages.
- For repeated order failures: enable `STOP` kill-switch, rotate keys, and run reconciliation.
- For data issues: stop market-data ingestion, run backtests offline to reproduce.

Post-incident

- Capture artifacts: logs, DB snapshot, reconciler output.
- Create a post-mortem with timeline and root cause, add to repository `docs/incidents/`.

