"""Web control plane for Ely's Trader.

Serves WEBSITE-RUN and exposes a small JSON API for configuration, status,
logs, paper-account history, bot lifecycle, connectivity, and backtesting.
"""
from __future__ import annotations

import json
import hmac
import math
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from flask import Flask, Response, jsonify, request, send_from_directory
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

import db
import safety
from analytics.database import TradingIntelligenceDatabase
from analytics.trade_history import get_trades
from analytics.decision_log import get_decision_history
from analytics.portfolio_history import get_equity_curve
from analytics.strategy_stats import get_strategy_statistics
from analytics.reports import generate_reports


ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "WEBSITE-RUN"
CFG_PATH = ROOT / "config.json"
LOG_PATH = ROOT / "mega_trading_bot.log"
AUDIT_PATH = ROOT / "mega_trading_bot.audit.log"
DEFAULT_CFG_PATH = CFG_PATH

APP = Flask(__name__, static_folder=None)
_process: subprocess.Popen | None = None
_process_lock = threading.Lock()
_research_job = {"state": "IDLE"}
_research_lock = threading.Lock()
_walkforward_job = {"state": "IDLE", "completed_windows": 0, "total_windows": 0}
_walkforward_lock = threading.Lock()


@APP.before_request
def require_authentication():
    """Protect the control plane with HTTP Basic auth, including static UI."""
    cfg = load_config()
    username = os.getenv("WEB_USERNAME") or cfg.get("WEB_USERNAME")
    password = os.getenv("WEB_PASSWORD") or cfg.get("WEB_PASSWORD")
    auth = request.authorization
    valid = bool(username and password and auth and
                 hmac.compare_digest(auth.username or "", str(username)) and
                 hmac.compare_digest(auth.password or "", str(password)))
    if not valid:
        return Response("Authentication required", 401,
                        {"WWW-Authenticate": 'Basic realm="Ely Trader"'})


def load_config() -> dict[str, Any]:
    with CFG_PATH.open("r", encoding="utf-8") as handle:
        cfg = json.load(handle)
    cfg.setdefault("DATA_PATH", "data")
    cfg.setdefault("PAPER_START_BALANCE", cfg.get("BACKTEST_START_BALANCE", 10000))
    return cfg


def data_path(cfg: dict[str, Any]) -> Path:
    path = Path(str(cfg.get("DATA_PATH", "data")))
    return path if path.is_absolute() else ROOT / path


def db_path(cfg: dict[str, Any]) -> Path:
    return data_path(cfg) / "mega_trades.db"


def intelligence(cfg=None):
    return TradingIntelligenceDatabase(db_path(cfg or load_config()), asynchronous=False)


def save_config(updates: dict[str, Any]) -> dict[str, Any]:
    cfg = load_config()
    allowed = {
        "PAPER_MODE", "LIVE_MODE", "EXCHANGE", "API_KEY", "API_SECRET",
        "SYMBOL", "SYMBOLS", "INTERVAL", "SLEEP_INTERVAL", "RISK_PER_TRADE",
        "MAX_POSITION_SIZE", "MAX_OPEN_POSITIONS", "DAILY_LOSS_LIMIT",
        "MAX_DRAWDOWN", "STOP_LOSS_PERCENT", "TAKE_PROFIT_PERCENT",
        "PAPER_START_BALANCE", "PAPER_FEE_RATE", "PAPER_SPREAD_RATE",
        "PAPER_SLIPPAGE_RATE", "PAPER_ORDER_LATENCY_MS", "XGB_MODEL_PATH",
        "LSTM_MODEL_PATH", "XGB_THRESHOLD", "STRATEGY", "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID", "TELEGRAM_ENABLED",
        "VIBETRADER_ENABLED", "VIBETRADER_ENFORCE",
    }
    for key, value in updates.items():
        if key in allowed:
            cfg[key] = value
    safety.validate_config(cfg)
    temp = CFG_PATH.with_suffix(".json.tmp")
    temp.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, CFG_PATH)
    return cfg


def process_running() -> bool:
    global _process
    with _process_lock:
        if _process is not None and _process.poll() is not None:
            _process = None
        return _process is not None


def start_bot() -> tuple[bool, str]:
    global _process
    with _process_lock:
        if _process is not None and _process.poll() is None:
            return False, "Bot is already running"
        stop_file = data_path(load_config()) / "STOP_TRADING"
        stop_file.unlink(missing_ok=True)
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        _process = subprocess.Popen(
            [sys.executable, str(ROOT / "mega_trading_bot.py"), "--config", str(CFG_PATH)],
            cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        return True, f"Bot started (PID {_process.pid})"


def stop_bot(emergency: bool = False) -> tuple[bool, str]:
    global _process
    cfg = load_config()
    if emergency:
        target = data_path(cfg) / "STOP_TRADING"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
    with _process_lock:
        proc = _process
        if proc is None or proc.poll() is not None:
            _process = None
            return True, "Emergency stop engaged" if emergency else "Bot is not running"
        try:
            if os.name == "nt":
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proc.terminate()
            proc.wait(timeout=8)
        except (OSError, subprocess.TimeoutExpired):
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        _process = None
    return True, "Emergency stop engaged" if emergency else "Bot stopped"


def read_rows(cfg: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    path = db_path(cfg)
    db.init_db(str(path))
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        orders = [dict(row) for row in conn.execute(
            "SELECT * FROM orders ORDER BY created_ts DESC LIMIT 100")]
        fills = [dict(row) for row in conn.execute(
            "SELECT * FROM fills ORDER BY ts DESC LIMIT 500")]
    return orders, fills


def account_snapshot(cfg: dict[str, Any], fills: list[dict], orders: list[dict] | None = None) -> dict[str, Any]:
    cash = float(cfg.get("PAPER_START_BALANCE", 10000))
    initial = cash
    holdings: dict[str, dict[str, float]] = {}
    realized = fees = 0.0
    closed: list[dict[str, Any]] = []
    order_symbols = {str(row.get("id")): row.get("symbol", "") for row in (orders or [])}
    for fill in reversed(fills):
        try:
            meta = json.loads(fill.get("meta") or "{}")
        except (TypeError, json.JSONDecodeError):
            meta = {}
        symbol = meta.get("symbol") or order_symbols.get(str(fill.get("order_id")), "")
        side = (fill.get("side") or meta.get("side") or "").lower()
        qty, price, fee = float(fill.get("amount") or 0), float(fill.get("price") or 0), float(fill.get("fee") or 0)
        fees += fee
        item = holdings.setdefault(symbol or "Unknown", {"quantity": 0.0, "cost": 0.0, "price": price})
        item["price"] = price
        if side == "buy":
            cash -= price * qty + fee
            item["quantity"] += qty
            item["cost"] += price * qty + fee
        elif side == "sell":
            held = item["quantity"]
            allocated = item["cost"] * qty / held if held else 0
            cash += price * qty - fee
            item["quantity"] -= qty
            item["cost"] -= allocated
            pnl = float(meta.get("net_profit", price * qty - fee - allocated))
            realized += pnl
            closed.append({"time": fill.get("ts"), "symbol": symbol or "Unknown", "side": side,
                           "entry": float(meta.get("entry_value", 0)) / qty if qty else 0,
                           "exit": price, "pnl": pnl, "status": "closed"})
    active = []
    market_value = 0.0
    for symbol, item in holdings.items():
        if item["quantity"] <= 1e-12:
            continue
        value = item["quantity"] * item["price"]
        market_value += value
        entry = item["cost"] / item["quantity"]
        active.append({"symbol": symbol, "quantity": item["quantity"], "entry_price": entry,
                       "current_price": item["price"], "value": value, "pnl": value - item["cost"]})
    equity = cash + market_value
    profits = [t["pnl"] for t in closed]
    gross_profit = sum(x for x in profits if x > 0)
    gross_loss = abs(sum(x for x in profits if x < 0))
    return {"cash": cash, "equity": equity, "initial": initial, "realized_pnl": realized,
            "fees": fees, "holdings": active, "trades": list(reversed(closed[-20:])),
            "win_rate": sum(x > 0 for x in profits) / len(profits) if profits else None,
            "profit_factor": gross_profit / gross_loss if gross_loss else (None if not gross_profit else gross_profit),
            "drawdown": max(0.0, (initial - equity) / initial) if initial else 0.0}


def tail_logs(limit: int = 300) -> list[dict[str, str]]:
    if not LOG_PATH.exists():
        return []
    lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    result = []
    for line in lines:
        upper = line.upper()
        level = next((level for level in ("ERROR", "WARNING", "INFO", "DEBUG") if level in upper), "INFO")
        result.append({"level": level.lower(), "message": line})
    return result


@APP.get("/")
def index():
    return send_from_directory(STATIC_ROOT, "index.html")


@APP.get("/<path:name>")
def static_file(name: str):
    return send_from_directory(STATIC_ROOT, name)


@APP.get("/api/config")
def get_config():
    cfg = load_config()
    cfg["API_KEY"] = ""  # never return secrets to the browser
    cfg["API_SECRET"] = ""
    cfg["TELEGRAM_BOT_TOKEN"] = ""
    return jsonify(cfg)


@APP.put("/api/config")
def put_config():
    try:
        updates = request.get_json(force=True) or {}
        if updates.get("LIVE_MODE") and updates.get("live_confirmation") != "ENABLE LIVE TRADING":
            return jsonify(error="Live mode requires explicit confirmation"), 400
        updates.pop("live_confirmation", None)
        return jsonify(config=save_config(updates), message="Settings saved")
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        return jsonify(error=str(exc)), 400


@APP.get("/api/status")
def api_status():
    cfg = load_config()
    orders, fills = read_rows(cfg)
    account = account_snapshot(cfg, fills, orders)
    logs = tail_logs(100)
    warnings = [x for x in logs if x["level"] in ("warning", "error")][-10:]
    analytics_status = intelligence(cfg).status()
    return jsonify(running=process_running(), mode="paper" if cfg.get("PAPER_MODE") else "live",
                   account=account, open_orders=[o for o in orders if o.get("status") != "closed"],
                   warnings=warnings, healthy=CFG_PATH.exists(), analytics=analytics_status)


@APP.post("/api/bot/<action>")
def bot_action(action: str):
    if action == "start":
        ok, message = start_bot()
    elif action == "stop":
        ok, message = stop_bot()
    elif action == "restart":
        stop_bot()
        ok, message = start_bot()
    elif action == "emergency-stop":
        ok, message = stop_bot(emergency=True)
    else:
        return jsonify(error="Unknown action"), 404
    return jsonify(ok=ok, message=message), 200 if ok else 409


@APP.get("/api/logs")
def api_logs():
    return jsonify(logs=tail_logs(min(int(request.args.get("limit", 300)), 2000)))


@APP.get("/api/analytics/trades")
def analytics_trades():
    tid = intelligence()
    return jsonify(trades=get_trades(tid, strategy=request.args.get("strategy"),
                   symbol=request.args.get("symbol"), limit=min(int(request.args.get("limit", 100)), 1000),
                   offset=max(int(request.args.get("offset", 0)), 0)))


@APP.get("/api/analytics/decisions")
def analytics_decisions():
    tid = intelligence()
    return jsonify(decisions=get_decision_history(tid, strategy=request.args.get("strategy"),
                   symbol=request.args.get("symbol"), limit=min(int(request.args.get("limit", 100)), 1000),
                   offset=max(int(request.args.get("offset", 0)), 0)))


@APP.get("/api/analytics/portfolio")
def analytics_portfolio():
    tid = intelligence()
    return jsonify(portfolio=get_equity_curve(tid, limit=min(int(request.args.get("limit", 1000)), 10000)))


@APP.get("/api/analytics/strategies")
def analytics_strategies():
    return jsonify(strategies=get_strategy_statistics(intelligence()))


@APP.post("/api/analytics/reports")
def analytics_reports():
    paths = generate_reports(intelligence(), ROOT / "reports")
    return jsonify(reports={key: str(Path(value).relative_to(ROOT)) for key, value in paths.items()})


@APP.delete("/api/logs")
def clear_logs():
    if process_running():
        return jsonify(error="Stop the bot before clearing logs"), 409
    LOG_PATH.write_text("", encoding="utf-8")
    return jsonify(message="Logs cleared")


@APP.post("/api/reset-paper")
def reset_paper():
    if process_running():
        return jsonify(error="Stop the bot before resetting the paper account"), 409
    path = db_path(load_config())
    if path.exists():
        with sqlite3.connect(path) as conn:
            for table in ("orders", "fills", "events", "idempotency"):
                conn.execute(f"DELETE FROM {table}")
    return jsonify(message="Paper account reset")


@APP.post("/api/test-connection")
def test_connection():
    payload = request.get_json(silent=True) or {}
    exchange_name = payload.get("exchange") or load_config().get("EXCHANGE", "binance")
    try:
        import ccxt
        cls = getattr(ccxt, exchange_name)
        exchange = cls({"enableRateLimit": True})
        exchange.load_markets()
        return jsonify(ok=True, message=f"Connected to {exchange_name}; {len(exchange.markets)} markets loaded")
    except Exception as exc:
        return jsonify(error=f"Connection failed: {exc}"), 502


@APP.post("/api/test-telegram")
def test_telegram():
    payload = request.get_json(silent=True) or {}
    cfg = load_config()
    token = payload.get("token") or cfg.get("TELEGRAM_BOT_TOKEN")
    chat_id = payload.get("chat_id") or cfg.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return jsonify(error="Telegram token and chat ID are required"), 400
    try:
        response = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                 json={"chat_id": chat_id, "text": "Ely's Trader test notification"}, timeout=10)
        response.raise_for_status()
        return jsonify(ok=True, message="Test notification sent")
    except requests.RequestException as exc:
        return jsonify(error=f"Telegram test failed: {exc}"), 502


def ema(values: list[float], period: int) -> list[float]:
    factor = 2 / (period + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append(value * factor + result[-1] * (1 - factor))
    return result


@APP.post("/api/backtest")
def backtest():
    payload = request.get_json(force=True) or {}
    symbol = str(payload.get("symbol") or "BTC/USDT").upper()
    timeframe = str(payload.get("timeframe") or "1d")
    initial = float(payload.get("initial_balance") or 10000)
    if initial <= 0:
        return jsonify(error="Initial balance must be positive"), 400
    try:
        import ccxt
        cfg = load_config()
        exchange = getattr(ccxt, cfg.get("EXCHANGE", "binance"))({"enableRateLimit": True})
        since = None
        if payload.get("start"):
            since = int(datetime.fromisoformat(payload["start"]).replace(tzinfo=timezone.utc).timestamp() * 1000)
        rows = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=1000)
        if payload.get("end"):
            end = int(datetime.fromisoformat(payload["end"]).replace(tzinfo=timezone.utc).timestamp() * 1000) + 86_400_000
            rows = [row for row in rows if row[0] < end]
        if len(rows) < 30:
            return jsonify(error="Not enough market data for this backtest (minimum 30 candles)"), 400
        import pandas as pd
        from backtesting.engine import BacktestEngine
        from backtesting.models import BacktestConfig
        from mega_trading_bot import strategy_macd
        data = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        data["timestamp"] = pd.to_datetime(data["timestamp"], unit="ms", utc=True)
        result = BacktestEngine(data, BacktestConfig(strategy="macd", symbol=symbol,
            timeframe=timeframe, starting_balance=initial,
            fee_rate=float(cfg.get("PAPER_FEE_RATE", .001)),
            spread_rate=float(cfg.get("PAPER_SPREAD_RATE", .0002)),
            slippage_rate=float(cfg.get("PAPER_SLIPPAGE_RATE", .0005)),
            risk_fraction=float(cfg.get("MAX_POSITION_FRACTION", 1.0)))).run(strategy_macd)
        return jsonify(result.to_dict())
    except Exception as exc:
        return jsonify(error=f"Backtest failed: {exc}"), 502


@APP.post("/api/strategy-tournament")
def strategy_tournament():
    payload = request.get_json(force=True) or {}; symbol = str(payload.get("symbol") or "BTC/USDT").upper()
    timeframe = str(payload.get("timeframe") or "1h"); initial = float(payload.get("initial_balance") or 10000)
    try:
        import ccxt, pandas as pd
        from backtesting.comparison import compare_walkforward
        from backtesting.models import BacktestConfig
        from strategies.registry import default_registry
        cfg=load_config(); exchange=getattr(ccxt,cfg.get("EXCHANGE","binance"))({"enableRateLimit":True})
        rows=exchange.fetch_ohlcv(symbol,timeframe=timeframe,limit=1000)
        data=pd.DataFrame(rows,columns=["timestamp","open","high","low","close","volume"])
        data["timestamp"]=pd.to_datetime(data.timestamp,unit="ms",utc=True)
        config=BacktestConfig(symbol=symbol,timeframe=timeframe,starting_balance=initial,
            fee_rate=float(cfg.get("PAPER_FEE_RATE",.001)),spread_rate=float(cfg.get("PAPER_SPREAD_RATE",.0002)),
            slippage_rate=float(cfg.get("PAPER_SLIPPAGE_RATE",.0005)),risk_fraction=float(cfg.get("MAX_POSITION_FRACTION",1)))
        from walkforward.models import WalkForwardConfig
        ranking,result=compare_walkforward(data,config,default_registry().enabled(),WalkForwardConfig(400,150,150,150))
        return jsonify(ranking=ranking,candles=len(data),windows=len(result["windows"]))
    except Exception as exc: return jsonify(error=f"Tournament failed: {exc}"),502


def _walkforward_inputs(payload):
    import ccxt, pandas as pd
    from backtesting.models import BacktestConfig
    from walkforward.models import QualificationRules, WalkForwardConfig
    cfg = load_config(); symbol = str(payload.get("symbol") or "BTC/USDT").upper()
    timeframe = str(payload.get("timeframe") or "1h"); initial = float(payload.get("initial_balance") or 10000)
    wf = WalkForwardConfig(int(payload.get("train_size", 400)), int(payload.get("validation_size", 150)),
                           int(payload.get("test_size", 150)), int(payload.get("step_size", 150)))
    needed = wf.train_size + wf.validation_size + wf.test_size
    exchange = getattr(ccxt, cfg.get("EXCHANGE", "binance"))({"enableRateLimit": True})
    rows = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=max(needed, min(2000, needed + wf.step_size * 4)))
    data = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    data["timestamp"] = pd.to_datetime(data.timestamp, unit="ms", utc=True)
    bt = BacktestConfig(symbol=symbol, timeframe=timeframe, starting_balance=initial,
        fee_rate=float(cfg.get("PAPER_FEE_RATE", .001)), spread_rate=float(cfg.get("PAPER_SPREAD_RATE", .0002)),
        slippage_rate=float(cfg.get("PAPER_SLIPPAGE_RATE", .0005)), risk_fraction=float(cfg.get("MAX_POSITION_FRACTION", 1)),
        stop_loss_pct=_optional_fraction(cfg.get("STOP_LOSS_PERCENT")),
        take_profit_pct=_optional_fraction(cfg.get("TAKE_PROFIT_PERCENT")))
    rules = QualificationRules(int(payload.get("minimum_oos_trades", 5)),
        float(payload.get("minimum_profit_factor", 1)), float(payload.get("maximum_drawdown_pct", 20)),
        float(payload.get("maximum_losing_window_pct", 50)), float(payload.get("maximum_degradation_pct", 50)))
    return data, bt, wf, rules


def _optional_fraction(value):
    value = float(value or 0)
    return value / 100 if value > 0 else None


@APP.post("/api/walkforward")
def walkforward_start():
    payload = request.get_json(silent=True) or {}
    with _walkforward_lock:
        if _walkforward_job.get("state") == "RUNNING": return jsonify(error="Walk-forward validation already running"), 409
        _walkforward_job.clear(); _walkforward_job.update(state="RUNNING", completed_windows=0, total_windows=0,
            started_at=datetime.now(timezone.utc).isoformat())
    def worker():
        try:
            from backtesting.comparison import compare_walkforward
            from strategies.registry import default_registry
            from walkforward.report import write_reports
            data, bt, wf, rules = _walkforward_inputs(payload)
            def progress(completed, total, strategy, window):
                with _walkforward_lock: _walkforward_job.update(completed_windows=completed, total_windows=total,
                    current_strategy=strategy, current_window=window)
            ranking, result = compare_walkforward(data, bt, default_registry().enabled(), wf, rules, progress)
            paths = write_reports(result, ROOT / "reports")
            outcome = {"state": "COMPLETED", "ranking": ranking, "reports": [Path(x).name for x in paths]}
        except Exception as exc: outcome = {"state": "ERROR", "error": str(exc)}
        with _walkforward_lock: _walkforward_job.update(outcome, finished_at=datetime.now(timezone.utc).isoformat())
    threading.Thread(target=worker, daemon=True, name="walk-forward-validation").start()
    return jsonify(state="RUNNING"), 202


@APP.get("/api/walkforward/status")
def walkforward_status():
    with _walkforward_lock: return jsonify(dict(_walkforward_job))


@APP.get("/api/walkforward/report/<name>")
def walkforward_report(name):
    if name not in ("walkforward_summary.json", "walkforward_summary.csv"):
        return jsonify(error="Unknown walk-forward report"), 404
    return send_from_directory(ROOT / "reports", name, as_attachment=True)


@APP.get("/api/research/status")
def research_status():
    from research.manager import ResearchManager
    cfg = load_config(); status = ResearchManager(cfg).status()
    try:
        approval = ResearchManager(cfg).store.read_current()
        status.update({k: approval.get(k) for k in ("strategy_id", "symbol", "timeframe", "confidence",
            "risk_multiplier", "generated_at", "expires_at", "refresh_after", "warnings", "oos_metrics")})
    except Exception: pass
    with _research_lock: status["job"] = dict(_research_job)
    status["enabled"] = bool(cfg.get("VIBETRADER_ENABLED")); status["enforcement"] = bool(cfg.get("VIBETRADER_ENFORCE"))
    return jsonify(status)


@APP.post("/api/research/run")
def research_run():
    payload = request.get_json(silent=True) or {}; cfg = load_config()
    allowed_strategy = str(payload.get("strategy") or cfg.get("STRATEGY", "macd"))
    if allowed_strategy != "macd": return jsonify(error="Only the registered macd strategy is supported"), 400
    with _research_lock:
        if _research_job.get("state") == "RUNNING": return jsonify(error="Research already running"), 409
        _research_job.clear(); _research_job.update(state="RUNNING", started_at=datetime.now(timezone.utc).isoformat())
    def worker():
        from research.factory import request_from_config
        from research.manager import ResearchManager
        from mega_trading_bot import strategy_macd
        try:
            req = request_from_config(cfg, "macd", str(payload.get("symbol") or cfg.get("SYMBOL")), str(payload.get("timeframe") or cfg.get("INTERVAL")))
            approval = ResearchManager(cfg, audit_db=str(db_path(cfg))).run(req, strategy_macd)
            result = {"state": "COMPLETED", "approval_id": approval["approval_id"]}
        except Exception as exc: result = {"state": "ERROR", "error": str(exc)}
        with _research_lock: _research_job.update(result, finished_at=datetime.now(timezone.utc).isoformat())
    threading.Thread(target=worker, daemon=True, name="bounded-research-job").start()
    return jsonify(state="RUNNING"), 202


@APP.post("/api/research/disable")
def research_disable():
    save_config({"VIBETRADER_ENABLED": False})
    db.save_event(str(db_path(load_config())), "INFO", "RESEARCH GATE_DISABLED")
    return jsonify(state="DISABLED")


@APP.post("/api/research/validate")
def research_validate():
    from research.manager import ResearchManager
    payload = request.get_json(silent=True) or {}; name = Path(str(payload.get("filename", ""))).name
    if not name or name != str(payload.get("filename", "")) or not name.endswith(".json"):
        return jsonify(error="Select a JSON filename from the research raw directory"), 400
    cfg = load_config(); target = Path(cfg.get("RESEARCH_DATA_PATH", "data/research")) / "raw" / name
    try: return jsonify(approval=ResearchManager(cfg).validate_file(target))
    except (ValueError, OSError, json.JSONDecodeError) as exc: return jsonify(error=str(exc)), 400


@APP.get("/health")
def health():
    cfg = load_config()
    return jsonify(config_loaded=True, db_exists=db_path(cfg).exists(), bot_running=process_running())


@APP.get("/metrics")
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    cfg = load_config()
    if not ((os.getenv("WEB_USERNAME") or cfg.get("WEB_USERNAME")) and
            (os.getenv("WEB_PASSWORD") or cfg.get("WEB_PASSWORD"))):
        raise SystemExit("Set WEB_USERNAME and WEB_PASSWORD before starting the web UI")
    APP.run(host="127.0.0.1", port=8080, debug=False, threaded=True)
