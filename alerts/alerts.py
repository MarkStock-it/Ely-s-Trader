"""Alerting helpers for Slack and PagerDuty (lightweight wrappers).

Place credentials in environment variables: `SLACK_WEBHOOK`, `PAGERDUTY_INTEGRATION_KEY`.
"""
import os
import requests
import logging

logger = logging.getLogger("mega_trading_bot.alerts")


def send_slack(message: str, webhook: str | None = None) -> bool:
    webhook = webhook or os.environ.get("SLACK_WEBHOOK")
    if not webhook:
        logger.debug("No Slack webhook configured")
        return False
    payload = {"text": message}
    try:
        r = requests.post(webhook, json=payload, timeout=5)
        r.raise_for_status()
        return True
    except Exception:
        logger.exception("Failed to send Slack alert")
        return False


def send_pagerduty(summary: str, severity: str = "error", integration_key: str | None = None) -> bool:
    integration_key = integration_key or os.environ.get("PAGERDUTY_INTEGRATION_KEY")
    if not integration_key:
        logger.debug("No PagerDuty integration key configured")
        return False
    payload = {
        "routing_key": integration_key,
        "event_action": "trigger",
        "payload": {"summary": summary, "severity": severity, "source": "mega_trading_bot"},
    }
    try:
        r = requests.post("https://events.pagerduty.com/v2/enqueue", json=payload, timeout=5)
        r.raise_for_status()
        return True
    except Exception:
        logger.exception("Failed to send PagerDuty alert")
        return False
