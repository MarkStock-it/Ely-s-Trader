"""mega_trading_bot.py

Refactored, consolidated crypto trading bot using ccxt (Binance), optional LSTM,
XGBoost, indicators, backtesting, Telegram alerts, risk management, and
position monitoring. Designed to run in PAPER or LIVE mode based on config.

Usage: configure via .env or config.json, then run this file.
"""
from __future__ import annotations

import threading
import time
import math
import json
import os
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
import logging
from logging.handlers import RotatingFileHandler
try:
    from pythonjsonlogger import jsonlogger
    JSON_LOGGER_AVAILABLE = True
except Exception:
    JSON_LOGGER_AVAILABLE = False
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import argparse
import ccxt
import pandas as pd
import numpy as np
import requests
import pickle
import safety
import db
from marketdata import MarketDataManager
from execution import ExecutionEngine
import metrics

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Optional ML deps
XGB_AVAILABLE = False
LSTM_AVAILABLE = False
try:
    import xgboost as xgb
    XGB_AVAILABLE = True
except Exception:
    XGB_AVAILABLE = False

try:
    import tensorflow as tf
    from tensorflow import keras
    LSTM_AVAILABLE = True
except Exception:
    LSTM_AVAILABLE = False

# -------------------- Configuration --------------------

DEFAULT_CONFIG = {
    "PAPER_MODE": True,
    "LIVE_MODE": False,
    "EXCHANGE": "binance",
    "API_KEY": "",
    "API_SECRET": "",
    "USE_TESTNET": True,
    "SYMBOL": "BTCUSDT",
    "INTERVAL": "1m",
    "RISK_PER_TRADE": 0.01,
    "MAX_OPEN_POSITIONS": 3,
    "ATR_PERIOD": 14,
    "ATR_MULTIPLIER": 1.5,
    "TELEGRAM_BOT_TOKEN": "",
    "TELEGRAM_CHAT_ID": "",
    "VOL_ALERT_PCT": 5.0,
    "VOL_WINDOW_MINS": 5,
    "HEARTBEAT_ENABLED": True,
    "HEARTBEAT_INTERVAL_MIN": 15,
    "PAPER_START_BALANCE": 10000.0,
    "DATA_PATH": "data",
    "STATE_FILE": "data/state.json",
    "RATE_LIMIT_SLEEP": 0.5,
}


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    """Load configuration. Search order: provided path, CWD config.json, script-dir config.json."""
    cfg = DEFAULT_CONFIG.copy()
    # env overrides first
    for k in cfg:
        if os.getenv(k) is not None:
            val = os.getenv(k)
            try:
                cfg[k] = json.loads(val)
            except Exception:
                cfg[k] = val

    candidates: List[str] = []
    if path:
        candidates.append(path)
    candidates.append(os.path.join(os.getcwd(), "config.json"))
    # script directory
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.join(script_dir, "config.json"))
    except Exception:
        pass

    for p in candidates:
        if p and os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    j = json.load(f)
                    cfg.update(j)
                    # logger may not be initialized yet; fallback to print
                    if "logger" in globals():
                        logger.info("Loaded config from %s", p)
                    else:
                        print(f"Loaded config from {p}")
                    break
            except Exception:
                if "logger" in globals():
                    logger.exception("Failed to load config from %s", p)
                else:
                    print(f"Failed to load config from {p}")
    return cfg


CONFIG = load_config()

# -------------------- Logging --------------------

LOG_PATH = "mega_trading_bot.log"
AUDIT_PATH = "mega_trading_bot.audit.log"
logger = logging.getLogger("mega_trading_bot")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    fh = RotatingFileHandler(LOG_PATH, maxBytes=5_000_000, backupCount=5)
    if JSON_LOGGER_AVAILABLE:
        jf = jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(name)s %(message)s')
        fh.setFormatter(jf)
    else:
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(sh)

# separate audit logger (structured events)
audit_logger = logging.getLogger("mega_trading_bot.audit")
audit_logger.setLevel(logging.INFO)
if not audit_logger.handlers:
    af = RotatingFileHandler(AUDIT_PATH, maxBytes=10_000_000, backupCount=7)
    if JSON_LOGGER_AVAILABLE:
        af.setFormatter(jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
    else:
        af.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    audit_logger.addHandler(af)


# -------------------- Utilities --------------------

def retry_backoff(max_tries: int = 5, base_delay: float = 0.5):
    def deco(func):
        def wrapper(*args, **kwargs):
            delay = base_delay
            for attempt in range(1, max_tries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    logger.warning("%s failed (attempt %s): %s", func.__name__, attempt, e)
                    if attempt == max_tries:
                        raise
                    time.sleep(delay)
                    delay *= 2
        return wrapper
    return deco


def ensure_paths(cfg: Dict[str, Any]) -> None:
    """Ensure directories and state file exist."""
    data_path = cfg.get("DATA_PATH", "data")
    try:
        os.makedirs(data_path, exist_ok=True)
    except Exception:
        print(f"Failed to create data path: {data_path}")
    state_file = cfg.get("STATE_FILE", os.path.join(data_path, "state.json"))
    if not os.path.exists(state_file):
        try:
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump({"open_positions": {}}, f)
        except Exception:
            print(f"Failed to create state file: {state_file}")


def normalize_symbol(symbol: str) -> str:
    """Normalize common symbol forms to Binance style, e.g., BTC/USDT -> BTCUSDT."""
    s = symbol.replace("/", "").replace("-", "").upper()
    return s


# -------------------- CCXT Exchange Manager --------------------

class ExchangeManager:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.exchange = self._init_exchange()

    def _init_exchange(self):
        ex = cfg_exchange_class(self.cfg.get("EXCHANGE", "binance"))
        params = {
            "enableRateLimit": True,
        }
        api_key = self.cfg.get("API_KEY") or os.getenv("API_KEY")
        api_secret = self.cfg.get("API_SECRET") or os.getenv("API_SECRET")
        if api_key and api_secret:
            try:
                ex.apiKey = api_key
                ex.secret = api_secret
            except Exception:
                pass
        # set sandbox/testnet if requested
        try:
            if self.cfg.get("USE_TESTNET"):
                if hasattr(ex, "set_sandbox_mode"):
                    ex.set_sandbox_mode(True)
        except Exception:
            pass
        ex.options = getattr(ex, "options", {})
        ex.options.update({"defaultType": "spot"})
        ex.enableRateLimit = True
        return ex

    def get_market_info(self, symbol: str) -> Dict[str, Any]:
        try:
            markets = self.exchange.load_markets()
            sym = normalize_symbol(symbol)
            if sym in markets:
                return markets[sym]
            # try variants
            for k, v in markets.items():
                if k.replace("/", "") == sym:
                    return v
        except Exception:
            logger.debug("Failed to load markets for rounding info")
        return {}

    def preflight_validate(self, symbol: str, amount: float, price: Optional[float] = None) -> Tuple[bool, str]:
        """Validate amount/price against market limits. Returns (ok, message)."""
        try:
            info = self.get_market_info(symbol)
            limits = info.get("limits", {})
            # amount limits
            amt_limits = limits.get("amount", {})
            if amt_limits:
                min_amt = float(amt_limits.get("min", 0) or 0)
                max_amt = float(amt_limits.get("max", 0) or float("inf"))
                if amount < min_amt:
                    return False, f"Amount {amount} less than min {min_amt}"
                if max_amt and max_amt > 0 and amount > max_amt:
                    return False, f"Amount {amount} greater than max {max_amt}"
            # notional / cost
            if price is not None:
                notional = price * amount
                cost_limit = limits.get("cost", {})
                if cost_limit:
                    min_cost = float(cost_limit.get("min", 0) or 0)
                    if notional < min_cost:
                        return False, f"Notional {notional} less than min cost {min_cost}"
            return True, "OK"
        except Exception as e:
            logger.debug("Preflight validation failed unexpectedly: %s", e)
            return True, "OK"

    def round_amount(self, symbol: str, amount: float) -> float:
        info = self.get_market_info(symbol)
        try:
            step = info.get("limits", {}).get("amount", {}).get("step")
            if step:
                # round down to step
                precision = int(round(-math.log10(step))) if step < 1 else 0
                factor = 10 ** precision
                return math.floor(amount * factor) / factor
        except Exception:
            pass
        # fallback
        return float(np.floor(amount * 1_000_000) / 1_000_000)

    def round_price(self, symbol: str, price: float) -> float:
        info = self.get_market_info(symbol)
        try:
            step = info.get("precision", {}).get("price")
            if step is not None:
                precision = int(step)
                factor = 10 ** precision
                return math.floor(price * factor) / factor
            tick = info.get("limits", {}).get("price", {}).get("tickSize")
            if tick:
                precision = int(round(-math.log10(float(tick)))) if float(tick) < 1 else 0
                factor = 10 ** precision
                return math.floor(price * factor) / factor
        except Exception:
            pass
        return float(price)

    def validate(self, symbol: str) -> Tuple[bool, str]:
        """Validate connectivity and symbol availability. Returns (ok, message)."""
        try:
            # fetch markets if available
            try:
                markets = self.exchange.load_markets()
            except Exception:
                markets = None
            # check symbol
            sym = normalize_symbol(symbol)
            if markets and sym not in markets and sym.replace("USDT", "/USDT") not in markets:
                # try fetch ticker
                try:
                    self.exchange.fetch_ticker(sym)
                except Exception as e:
                    return False, f"Symbol {sym} not found or ticker fetch failed: {e}"
            # test public call
            try:
                _ = self.exchange.fetch_ticker(sym)
            except Exception as e:
                return False, f"Failed to fetch ticker for {sym}: {e}"
            # if keys provided, test private call
            if self.cfg.get("API_KEY") and self.cfg.get("API_SECRET"):
                try:
                    _ = self.exchange.fetch_balance()
                except Exception as e:
                    return False, f"Failed to fetch balance with provided keys: {e}"
            return True, "OK"
        except Exception as e:
            return False, f"Validation error: {e}"

    @retry_backoff()
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame:
        sym = normalize_symbol(symbol)
        data = self.exchange.fetch_ohlcv(sym, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(data, columns=["ts", "open", "high", "low", "close", "volume"])
        df["ts"] = pd.to_datetime(df["ts"], unit="ms")
        df.set_index("ts", inplace=True)
        return df

    @retry_backoff()
    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        return self.exchange.fetch_ticker(normalize_symbol(symbol))

    @retry_backoff()
    def create_market_order(self, symbol: str, side: str, amount: float) -> Dict[str, Any]:
        sym = normalize_symbol(symbol)
        if self.cfg.get("PAPER_MODE") or not (self.cfg.get("API_KEY") and self.cfg.get("API_SECRET")):
            # Simulate order
            logger.info("Paper: Simulate %s %s %f", side, sym, amount)
            return {"id": f"paper_{int(time.time()*1000)}", "symbol": sym, "side": side, "amount": amount, "status": "closed"}
        return self.exchange.create_order(sym, "market", side, amount)


def cfg_exchange_class(name: str):
    name = name.lower()
    if name == "binance":
        return ccxt.binance()
    try:
        return getattr(ccxt, name)()
    except Exception:
        return ccxt.binance()


# -------------------- Indicators --------------------

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=1).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.rolling(period, min_periods=1).mean()
    ma_down = down.rolling(period, min_periods=1).mean()
    rs = ma_up / (ma_down + 1e-9)
    return 100 - (100 / (1 + rs))


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=1).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def macd(series: pd.Series, fast=12, slow=26, signal=9) -> pd.DataFrame:
    efast = ema(series, fast)
    eslow = ema(series, slow)
    macd_line = efast - eslow
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": hist})


def bollinger(series: pd.Series, period: int = 20, dev: float = 2.0) -> pd.DataFrame:
    mid = sma(series, period)
    std = series.rolling(period).std()
    upper = mid + dev * std
    lower = mid - dev * std
    return pd.DataFrame({"mid": mid, "upper": upper, "lower": lower})


# -------------------- Models --------------------

class ModelManager:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.xgb_model = None
        self.lstm_model = None

    def load_xgb(self, path: str) -> None:
        if not XGB_AVAILABLE:
            logger.warning("XGBoost not available; skipping XGB model load")
            return
        try:
            with open(path, "rb") as f:
                self.xgb_model = pickle.load(f)
            logger.info("Loaded XGBoost model: %s", path)
        except Exception as e:
            logger.exception("Failed to load XGB model: %s", e)

    def load_lstm(self, path: str) -> None:
        if not LSTM_AVAILABLE:
            logger.warning("TensorFlow not available; skipping LSTM model load")
            return
        try:
            self.lstm_model = keras.models.load_model(path)
            logger.info("Loaded LSTM model: %s", path)
        except Exception as e:
            logger.exception("Failed to load LSTM model: %s", e)

    def predict_xgb(self, X: pd.DataFrame) -> np.ndarray:
        if self.xgb_model is None:
            raise RuntimeError("XGB model not loaded")
        dmat = xgb.DMatrix(X)
        return self.xgb_model.predict(dmat)

    def predict_lstm(self, X: np.ndarray) -> np.ndarray:
        if self.lstm_model is None:
            raise RuntimeError("LSTM model not loaded")
        return self.lstm_model.predict(X)


# -------------------- Telegram --------------------

class TelegramClient:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.base = f"https://api.telegram.org/bot{self.token}"

    def send(self, text: str) -> Dict[str, Any]:
        """Send a Telegram message. Failures are logged but do not raise."""
        if not self.token or not self.chat_id:
            logger.debug("Telegram not configured; would send: %s", text)
            return {}
    @retry_backoff()
    def get_updates(self) -> Dict[str, Any]:
        if not self.token:
            return {}
        url = f"{self.base}/getUpdates"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()
        url = f"{self.base}/sendMessage"
        try:
            resp = requests.post(url, json={"chat_id": self.chat_id, "text": text}, timeout=10)
            resp.raise_for_status()
            j = resp.json()
            if not j.get("ok"):
                logger.warning("Telegram API returned not ok: %s", j)
            return j
        except Exception as e:
            logger.exception("Failed to send Telegram message: %s", e)
            return {}


# -------------------- Risk & Execution --------------------

@dataclass
class Position:
    id: str
    symbol: str
    side: str
    amount: float
    entry_price: float
    stop_price: Optional[float]
    take_profit: Optional[float]
    trailing_pct: Optional[float]
    open_ts: float


class TradeManager:
    def __init__(self, exchange: ExchangeManager, cfg: Dict[str, Any], telegram: Optional[TelegramClient] = None, circuit_breaker=None):
        self.ex = exchange
        self.cfg = cfg
        self.telegram = telegram
        self.circuit_breaker = circuit_breaker
        self.open_positions: Dict[str, Position] = {}
        self.lock = threading.Lock()
        # persistent state file
        self.state_file = cfg.get("STATE_FILE", os.path.join(cfg.get("DATA_PATH", "data"), "state.json"))
        # try load previous state
        try:
            self._load_state()
        except Exception:
            # if load fails, ensure file exists
            try:
                ensure_paths(cfg)
                self._save_state()
            except Exception:
                logger.exception("Failed to initialize state file")

    def get_balance(self) -> float:
        # Try fetch balance from exchange if credentials available
        try:
            if self.cfg.get("PAPER_MODE"):
                return float(self.cfg.get("PAPER_START_BALANCE", 10000.0))
            bal = self.ex.exchange.fetch_balance()
            for candidate in ["USDT", "USD", "EUR"]:
                if candidate in bal.get("total", {}):
                    return float(bal["total"][candidate])
        except Exception:
            logger.exception("Failed to fetch balance; using fallback")
        return float(self.cfg.get("PAPER_START_BALANCE", 10000.0))

    def unrealized_pnl(self) -> float:
        total = 0.0
        with self.lock:
            positions = list(self.open_positions.values())
        for pos in positions:
            try:
                ticker = self.ex.fetch_ticker(pos.symbol)
                last = float(ticker.get("last", 0))
                if pos.side.lower() == "buy":
                    pnl = (last - pos.entry_price) * pos.amount
                else:
                    pnl = (pos.entry_price - last) * pos.amount
                total += pnl
            except Exception:
                logger.exception("Failed to compute unrealized pnl for %s", pos.id)
        return float(total)

    def _load_state(self) -> None:
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    open_positions = data.get("open_positions", {})
                    # open_positions persisted as simple dict; we only restore ids and minimal fields
                    for pid, p in open_positions.items():
                        try:
                            pos = Position(**p)
                            self.open_positions[pid] = pos
                        except Exception:
                            logger.debug("Skipping invalid saved position %s", pid)
        except Exception:
            logger.exception("Failed to load state file %s", self.state_file)

    def _save_state(self) -> None:
        try:
            data = {"open_positions": {}}
            with self.lock:
                for pid, pos in self.open_positions.items():
                    data["open_positions"][pid] = {
                        "id": pos.id,
                        "symbol": pos.symbol,
                        "side": pos.side,
                        "amount": pos.amount,
                        "entry_price": pos.entry_price,
                        "stop_price": pos.stop_price,
                        "take_profit": pos.take_profit,
                        "trailing_pct": pos.trailing_pct,
                        "open_ts": pos.open_ts,
                    }
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            logger.exception("Failed to save state to %s", self.state_file)

    def summary(self) -> Dict[str, Any]:
        bal = self.get_balance()
        upnl = self.unrealized_pnl()
        with self.lock:
            open_count = len(self.open_positions)
        return {"balance": bal, "open_positions": open_count, "unrealized_pnl": upnl}

    def calc_qty_by_risk(self, balance: float, risk_pct: float, entry_price: float, stop_price: float) -> float:
        risk_amount = balance * float(risk_pct)
        stop_distance = abs(entry_price - stop_price)
        if stop_distance <= 0:
            return 0.0
        qty = risk_amount / stop_distance
        return float(np.floor(qty * 1000000) / 1000000)

    def open_position(self, symbol: str, side: str, entry_price: float, stop_price: Optional[float], take_profit: Optional[float], trailing_pct: Optional[float]) -> Optional[Position]:
        balance = self.get_balance()
        if stop_price is None:
            logger.warning("Stop price required for risk calc; aborting trade")
            return None
        qty = self.calc_qty_by_risk(balance, float(self.cfg.get("RISK_PER_TRADE", 0.01)), entry_price, stop_price)
        if qty <= 0:
            logger.warning("Calculated qty <= 0; aborting")
            return None
        with self.lock:
            if len(self.open_positions) >= int(self.cfg.get("MAX_OPEN_POSITIONS", 3)):
                logger.warning("Max open positions reached")
                return None
            try:
                # Respect circuit breaker before placing live orders
                if not self.cfg.get("PAPER_MODE") and self.circuit_breaker is not None:
                    if not self.circuit_breaker.allow():
                        logger.error("Circuit breaker prevents placing new orders")
                        return None
                # use ExecutionEngine for idempotent, audited order placement
                try:
                    db_path = os.path.join(self.cfg.get("DATA_PATH", "data"), "mega_trades.db")
                    if hasattr(self, "exec_engine") and self.exec_engine is not None:
                        res = self.exec_engine.create_order(symbol, side, qty)
                        pid = res.get("id", f"order_{int(time.time()*1000)}")
                    else:
                        order = self.ex.create_market_order(symbol, side, qty)
                        pid = order.get("id", f"paper_{int(time.time()*1000)}")
                except Exception:
                    logger.exception("Failed to place order via execution engine")
                    return None
                pos = Position(pid, normalize_symbol(symbol), side, qty, entry_price, stop_price, take_profit, trailing_pct, time.time())
                self.open_positions[pid] = pos
                # send enriched telegram message
                msg = (
                    f"Opened {pos.side.upper()} {pos.symbol}\n"
                    f"Qty: {pos.amount:.6f} @ Entry: {pos.entry_price:.2f}\n"
                    f"Stop: {pos.stop_price:.2f} | TP: {pos.take_profit or 'N/A'}\n"
                )
                try:
                    balance = self.get_balance()
                    risk_amount = balance * float(self.cfg.get("RISK_PER_TRADE", 0.01))
                    msg += f"Risk per trade: {risk_amount:.2f} ({float(self.cfg.get('RISK_PER_TRADE'))*100:.2f}%)\n"
                except Exception:
                    pass
                logger.info("Opened position %s", pos)
                try:
                    self._save_state()
                except Exception:
                    logger.exception("Failed to save state after opening position")
                # record circuit breaker success
                try:
                    if self.circuit_breaker is not None:
                        self.circuit_breaker.record_success()
                except Exception:
                    logger.debug("Failed to update circuit breaker on success")
                if self.telegram:
                    try:
                        self.telegram.send(msg)
                    except Exception:
                        logger.exception("Failed to send open position telegram")
                # audit event
                try:
                    db_path = os.path.join(self.cfg.get("DATA_PATH", "data"), "mega_trades.db")
                    db.save_event(db_path, "INFO", f"OPEN_POSITION {pos.id} {pos.symbol} {pos.amount} {pos.entry_price}")
                    try:
                        audit_logger.info({"event": "open_position", "id": pos.id, "symbol": pos.symbol, "amount": pos.amount, "entry_price": pos.entry_price})
                    except Exception:
                        pass
                except Exception:
                    logger.debug("Failed to write audit event for open position")
                return pos
            except Exception:
                logger.exception("Failed to open position")
                try:
                    if self.circuit_breaker is not None:
                        self.circuit_breaker.record_failure()
                except Exception:
                    logger.debug("Failed to update circuit breaker on failure")
                return None

    def close_position(self, pid: str, reason: str = "manual") -> bool:
        with self.lock:
            if pid not in self.open_positions:
                return False
            pos = self.open_positions.pop(pid)
        try:
            side = "sell" if pos.side.lower() == "buy" else "buy"
            # determine exit price
            try:
                ticker = self.ex.fetch_ticker(pos.symbol)
                exit_price = float(ticker.get("last", 0))
            except Exception:
                logger.exception("Failed to fetch ticker for exit price; using entry as exit")
                exit_price = pos.entry_price
            self.ex.create_market_order(pos.symbol, side, pos.amount)
            # compute pnl
            if pos.side.lower() == "buy":
                pnl = (exit_price - pos.entry_price) * pos.amount
            else:
                pnl = (pos.entry_price - exit_price) * pos.amount
            # compute pct against position value
            pos_value = pos.entry_price * pos.amount
            pnl_pct = (pnl / (pos_value + 1e-9)) * 100
            msg = (
                f"Closed {pos.side.upper()} {pos.symbol}\n"
                f"Entry: {pos.entry_price:.2f} Exit: {exit_price:.2f}\n"
                f"Qty: {pos.amount:.6f}\n"
                f"PnL: {pnl:.2f} ({pnl_pct:.2f}%)\n"
                f"Reason: {reason}"
            )
            logger.info("Closed position %s: %s (PnL: %.2f)", pid, reason, pnl)
            if self.telegram:
                try:
                    self.telegram.send(msg)
                except Exception:
                    logger.exception("Failed to send close position telegram")
            try:
                self._save_state()
            except Exception:
                logger.exception("Failed to save state after closing position")
            # update DB to mark order closed and log fill if possible
            try:
                db.update_order_status(self.state_file.replace(os.path.basename(self.state_file), "mega_trades.db"), pos.id, "closed", "closed")
                db.log_fill(self.state_file.replace(os.path.basename(self.state_file), "mega_trades.db"), pos.id, exit_price, pos.amount, 0.0, side)
            except Exception:
                logger.debug("Failed to update DB for closed position %s", pid)
            # audit event for close
            try:
                db_path = os.path.join(self.cfg.get("DATA_PATH", "data"), "mega_trades.db")
                db.save_event(db_path, "INFO", f"CLOSE_POSITION {pos.id} {pos.symbol} {pos.amount} {exit_price} {reason}")
                try:
                    audit_logger.info({"event": "close_position", "id": pos.id, "symbol": pos.symbol, "amount": pos.amount, "exit_price": exit_price, "reason": reason})
                except Exception:
                    pass
            except Exception:
                logger.debug("Failed to write audit event for close position")
            return True
        except Exception:
            logger.exception("Failed to close position %s", pid)
            return False


# -------------------- Position Monitor --------------------

class PositionMonitor(threading.Thread):
    def __init__(self, trade_mgr: TradeManager, ex_mgr: ExchangeManager, cfg: Dict[str, Any], interval: int = 5):
        super().__init__(daemon=True)
        self.trade_mgr = trade_mgr
        self.ex_mgr = ex_mgr
        self.cfg = cfg
        self.interval = interval
        self.running = True

    def run(self):
        logger.info("Position monitor started")
        while self.running:
            try:
                now = time.time()
                to_close = []
                with self.trade_mgr.lock:
                    positions = list(self.trade_mgr.open_positions.values())
                try:
                    metrics.OPEN_POSITIONS_GAUGE.set(len(positions))
                except Exception:
                    pass
                for pos in positions:
                    ticker = self.ex_mgr.fetch_ticker(pos.symbol)
                    last = float(ticker.get("last", 0))
                    if pos.side.lower() == "buy":
                        if pos.stop_price and last <= pos.stop_price:
                            to_close.append((pos.id, "stop_loss"))
                        if pos.take_profit and last >= pos.take_profit:
                            to_close.append((pos.id, "take_profit"))
                        if pos.trailing_pct and last >= pos.entry_price * (1 + pos.trailing_pct):
                            new_stop = last * (1 - pos.trailing_pct)
                            pos.stop_price = max(pos.stop_price or 0, new_stop)
                    else:
                        if pos.stop_price and last >= pos.stop_price:
                            to_close.append((pos.id, "stop_loss"))
                        if pos.take_profit and last <= pos.take_profit:
                            to_close.append((pos.id, "take_profit"))
                        if pos.trailing_pct and last <= pos.entry_price * (1 - pos.trailing_pct):
                            new_stop = last * (1 + pos.trailing_pct)
                            pos.stop_price = min(pos.stop_price or float('inf'), new_stop)
                for pid, reason in to_close:
                    self.trade_mgr.close_position(pid, reason)
                    try:
                        metrics.POSITION_CLOSES.inc()
                    except Exception:
                        pass
            except Exception:
                logger.exception("Error in position monitor loop")
                try:
                    metrics.POSITION_MONITOR_ERRORS.inc()
                except Exception:
                    pass
            time.sleep(self.interval)


class HeartbeatThread(threading.Thread):
    def __init__(self, trade_mgr: TradeManager, ex_mgr: ExchangeManager, telegram: Optional[TelegramClient], cfg: Dict[str, Any]):
        super().__init__(daemon=True)
        self.trade_mgr = trade_mgr
        self.ex_mgr = ex_mgr
        self.telegram = telegram
        self.cfg = cfg
        self.running = True

    def run(self):
        logger.info("Heartbeat thread started")
        interval = int(self.cfg.get("HEARTBEAT_INTERVAL_MIN", 15))
        while self.running:
            try:
                summary = self.trade_mgr.summary()
                bal = summary.get("balance")
                upnl = summary.get("unrealized_pnl")
                open_cnt = summary.get("open_positions")
                msg = f"Heartbeat: Balance {bal:.2f} | Open: {open_cnt} | Unrealized PnL {upnl:.2f}\n"
                # list open positions
                lines = []
                with self.trade_mgr.lock:
                    for pos in self.trade_mgr.open_positions.values():
                        try:
                            ticker = self.ex_mgr.fetch_ticker(pos.symbol)
                            last = float(ticker.get("last", 0))
                            if pos.side.lower() == "buy":
                                pnl = (last - pos.entry_price) * pos.amount
                            else:
                                pnl = (pos.entry_price - last) * pos.amount
                            lines.append(f"{pos.id}: {pos.side.upper()} {pos.symbol} {pos.amount:.6f} entry {pos.entry_price:.2f} last {last:.2f} pnl {pnl:.2f}")
                        except Exception:
                            lines.append(f"{pos.id}: {pos.side.upper()} {pos.symbol} (failed to fetch price)")
                if lines:
                    msg += "\n" + "\n".join(lines)
                if self.telegram:
                    try:
                        self.telegram.send(msg)
                    except Exception:
                        logger.exception("Heartbeat telegram send failed")
                else:
                    logger.info(msg)
            except Exception:
                logger.exception("Error in heartbeat loop")
            time.sleep(interval * 60)


class WatchdogThread(threading.Thread):
    """Restart monitor/heartbeat if they crash; keeps threads alive."""
    def __init__(self, monitor: PositionMonitor, heartbeat: Optional[HeartbeatThread], trade_mgr: TradeManager, ex_mgr: ExchangeManager, tg: Optional[TelegramClient], cfg: Dict[str, Any]):
        super().__init__(daemon=True)
        self.monitor = monitor
        self.heartbeat = heartbeat
        self.trade_mgr = trade_mgr
        self.ex_mgr = ex_mgr
        self.tg = tg
        self.cfg = cfg
        self.running = True

    def run(self):
        logger.info("Watchdog started")
        while self.running:
            try:
                if not self.monitor.is_alive():
                    logger.warning("PositionMonitor died; restarting")
                    try:
                        self.monitor = PositionMonitor(self.trade_mgr, self.ex_mgr, self.cfg)
                        self.monitor.start()
                        if self.tg:
                            self.tg.send("Position monitor restarted by watchdog")
                    except Exception:
                        logger.exception("Failed to restart PositionMonitor")
                if self.heartbeat and not self.heartbeat.is_alive():
                    logger.warning("Heartbeat died; restarting")
                    try:
                        self.heartbeat = HeartbeatThread(self.trade_mgr, self.ex_mgr, self.tg, self.cfg)
                        self.heartbeat.start()
                        if self.tg:
                            self.tg.send("Heartbeat restarted by watchdog")
                    except Exception:
                        logger.exception("Failed to restart Heartbeat")
            except Exception:
                logger.exception("Error in watchdog loop")
            time.sleep(5)


# -------------------- Backtester --------------------

class Backtester:
    def __init__(self, ohlcv: pd.DataFrame, cfg: Dict[str, Any]):
        self.ohlcv = ohlcv.copy()
        self.cfg = cfg
        self.trades: List[Dict[str, Any]] = []

    def run_strategy(self, strategy_fn) -> Dict[str, Any]:
        cash = float(self.cfg.get("BACKTEST_START_BALANCE", 10000.0))
        pos = None
        for idx in range(len(self.ohlcv)):
            window = self.ohlcv.iloc[: idx + 1]
            signal = strategy_fn(window)
            price = float(window.close.iloc[-1])
            if signal == "buy" and pos is None:
                pos = {"entry_price": price, "size": cash / price}
                logger.debug("Backtest buy at %s", price)
            elif signal == "sell" and pos is not None:
                pnl = (price - pos["entry_price"]) * pos["size"]
                cash += pnl
                self.trades.append({"entry": pos["entry_price"], "exit": price, "pnl": pnl})
                pos = None
        if pos is not None:
            last = float(self.ohlcv.close.iloc[-1])
            pnl = (last - pos["entry_price"]) * pos["size"]
            cash += pnl
            self.trades.append({"entry": pos["entry_price"], "exit": last, "pnl": pnl})
        return self._metrics(cash)

    def _metrics(self, final_cash: float) -> Dict[str, Any]:
        returns = [t["pnl"] for t in self.trades]
        wins = sum(1 for r in returns if r > 0)
        losses = sum(1 for r in returns if r <= 0)
        win_rate = wins / max(len(returns), 1)
        total_return = final_cash - float(self.cfg.get("BACKTEST_START_BALANCE", 10000.0))
        sr = 0.0
        if len(returns) > 1 and np.std(returns) > 0:
            sr = float(np.mean(returns) / np.std(returns) * math.sqrt(len(returns)))
        max_dd = self._max_drawdown()
        return {"final_cash": final_cash, "total_return": total_return, "win_rate": win_rate, "sharpe": sr, "max_drawdown": max_dd}

    def _max_drawdown(self) -> float:
        equity = [float(self.cfg.get("BACKTEST_START_BALANCE", 10000.0))]
        for t in self.trades:
            equity.append(equity[-1] + t["pnl"])
        eq = np.array(equity)
        peak = np.maximum.accumulate(eq)
        dd = (peak - eq) / peak
        return float(np.max(dd)) if len(dd) > 0 else 0.0


# -------------------- Sentiment (CoinGecko status updates) --------------------

def fetch_sentiment_coin_gecko(coin_id: str = "bitcoin") -> float:
    try:
        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/status_updates"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        texts = " ".join([u.get("description", "") + " " + u.get("title", "") for u in data.get("status_updates", [])])
        if not texts:
            return 0.0
        try:
            from textblob import TextBlob
            pol = TextBlob(texts).sentiment.polarity
            return float(pol)
        except Exception:
            logger.debug("TextBlob not available; returning neutral sentiment")
            return 0.0
    except Exception:
        logger.exception("Failed to fetch CoinGecko status updates")
        return 0.0


# -------------------- Strategies --------------------

def strategy_macd(window: pd.DataFrame) -> Optional[str]:
    if len(window) < 30:
        return None
    m = macd(window.close)
    last = m.iloc[-1]
    prev = m.iloc[-2]
    if prev.macd < prev.signal and last.macd > last.signal:
        return "buy"
    if prev.macd > prev.signal and last.macd < last.signal:
        return "sell"
    return None


def strategy_xgb(window: pd.DataFrame, model_mgr: ModelManager) -> Optional[str]:
    if not XGB_AVAILABLE or model_mgr.xgb_model is None:
        return None
    if len(window) < 20:
        return None
    features = pd.DataFrame({"c%03d" % i: [window.close.shift(i).iloc[-1]] for i in range(10)})
    pred = model_mgr.predict_xgb(features)
    return "buy" if pred[-1] > 0.5 else "sell"


# -------------------- Volatility Alerts --------------------

def check_volatility_alert(df: pd.DataFrame, cfg: Dict[str, Any], telegram: Optional[TelegramClient]) -> None:
    mins = int(cfg.get("VOL_WINDOW_MINS", 5))
    pct = float(cfg.get("VOL_ALERT_PCT", 5.0))
    if len(df) < mins:
        return
    window = df.close.iloc[-mins:]
    change = (window.iloc[-1] - window.iloc[0]) / window.iloc[0] * 100
    if abs(change) >= pct:
        msg = f"Volatility alert: {change:.2f}% over last {mins} minutes"
        logger.info(msg)
        if telegram:
            telegram.send(msg)


# -------------------- Main Loop --------------------

def main_loop(cfg: Dict[str, Any]):
    # ensure filesystem paths
    ensure_paths(cfg)
    ex_mgr = ExchangeManager(cfg)
    # safety: basic config validation
    try:
        safety.validate_config(cfg)
    except Exception as e:
        logger.exception("Config validation failed: %s", e)
        return
    # init persistent DB for orders/events
    db_path = os.path.join(cfg.get("DATA_PATH", "data"), "mega_trades.db")
    try:
        db.init_db(db_path)
    except Exception:
        logger.exception("Failed to init DB at %s", db_path)
    tg = TelegramClient(cfg.get("TELEGRAM_BOT_TOKEN"), cfg.get("TELEGRAM_CHAT_ID"))
    # circuit breaker
    cb = safety.CircuitBreaker(max_failures=int(cfg.get("CB_MAX_FAILURES", 5)), cooldown_seconds=int(cfg.get("CB_COOLDOWN", 300)))
    # validate exchange connectivity and symbol
    try:
        ok, msg = ex_mgr.validate(cfg.get("SYMBOL", "BTCUSDT"))
        if not ok:
            logger.error("Exchange validation failed: %s", msg)
            if tg:
                tg.send(f"Exchange validation failed: {msg}")
            return
    except Exception:
        logger.exception("Unexpected error during exchange validation")
    # send a startup test message to confirm Telegram configuration
    try:
        tg.send(f"mega_trading_bot starting. PAPER_MODE={cfg.get('PAPER_MODE')}, SYMBOL={cfg.get('SYMBOL')}")
    except Exception:
        logger.exception("Startup telegram send failed")
    model_mgr = ModelManager(cfg)
    if cfg.get("XGB_MODEL_PATH"):
        model_mgr.load_xgb(cfg.get("XGB_MODEL_PATH"))
    if cfg.get("LSTM_MODEL_PATH"):
        model_mgr.load_lstm(cfg.get("LSTM_MODEL_PATH"))

    trade_mgr = TradeManager(ex_mgr, cfg, tg, circuit_breaker=cb)
    # execution engine
    exec_engine = ExecutionEngine(ex_mgr, db_path, cfg, circuit_breaker=cb)
    trade_mgr.exec_engine = exec_engine
    monitor = PositionMonitor(trade_mgr, ex_mgr, cfg)
    monitor.start()
    heartbeat = None
    if cfg.get("HEARTBEAT_ENABLED"):
        heartbeat = HeartbeatThread(trade_mgr, ex_mgr, tg, cfg)
        heartbeat.start()
    # start watchdog
    watchdog = WatchdogThread(monitor, heartbeat, trade_mgr, ex_mgr, tg, cfg)
    watchdog.start()

    # Order reconciler: background thread to sync DB <-> exchange
    class OrderReconciler(threading.Thread):
        def __init__(self, ex_mgr: ExchangeManager, db_path: str, tg: Optional[TelegramClient], cfg: Dict[str, Any], interval: int = 10):
            super().__init__(daemon=True)
            self.ex_mgr = ex_mgr
            self.db_path = db_path
            self.tg = tg
            self.cfg = cfg
            self.interval = interval
            self.running = True

        def run(self):
            logger.info("OrderReconciler started; interval=%s", self.interval)
            while self.running:
                try:
                    open_orders = db.get_open_orders(self.db_path)
                    # fetch open orders from exchange if supported
                    try:
                        ex_open = []
                        if hasattr(self.ex_mgr.exchange, "fetch_open_orders"):
                            ex_open = self.ex_mgr.exchange.fetch_open_orders()
                    except Exception:
                        logger.debug("Exchange open orders fetch failed; continuing")

                    # reconcile by checking fills/trades
                    for o in open_orders:
                        try:
                            oid = o.get("id")
                            # if exchange reports no open order with same id, mark as closed in DB
                            found = False
                            for eo in ex_open:
                                if str(eo.get("id")) == str(oid):
                                    found = True
                                    break
                            if not found:
                                # try fetch trades for this order id
                                try:
                                    if hasattr(self.ex_mgr.exchange, "fetch_my_trades"):
                                        trades = self.ex_mgr.exchange.fetch_my_trades(symbol=o.get("symbol"))
                                        for t in trades:
                                            if str(t.get("order")) == str(oid) or str(t.get("orderId")) == str(oid):
                                                price = float(t.get("price", 0))
                                                amount = float(t.get("amount", 0))
                                                fee = 0.0
                                                db.log_fill(self.db_path, oid, price, amount, fee, t.get("side"))
                                                db.update_order_status(self.db_path, oid, "closed", "closed")
                                                if self.tg:
                                                    try:
                                                        self.tg.send(f"Order {oid} reconciled as closed (fill found)")
                                                    except Exception:
                                                        logger.debug("Failed to send reconcile telegram")
                                                break
                                except Exception:
                                    logger.debug("Failed to fetch trades to reconcile order %s", oid)
                                # if no trades, mark closed to avoid stale opens
                                db.update_order_status(self.db_path, oid, "closed", "closed")
                                try:
                                    # update reconciler/open-order metrics
                                    metrics.OPEN_ORDERS_GAUGE.set(len(open_orders) if open_orders is not None else 0)
                                    metrics.RECONCILED_ORDERS.inc()
                                    metrics.LAST_RECONCILE.set(time.time())
                                except Exception:
                                    pass
                                if self.tg:
                                    try:
                                        self.tg.send(f"Order {oid} presumed closed during reconciliation")
                                    except Exception:
                                        logger.debug("Failed to send reconcile telegram")
                        except Exception:
                            logger.exception("Error reconciling order %s", o)
                except Exception:
                    logger.exception("Unexpected error in OrderReconciler loop")
                time.sleep(self.interval)

    reconciler = OrderReconciler(ex_mgr, db_path, tg, cfg, interval=int(cfg.get("RECONCILE_INTERVAL", 15)))
    reconciler.start()

    # market data manager: background poller + fan-out
    try:
        mdm = MarketDataManager(ex_mgr, cfg)
        mdm.subscribe(cfg.get("SYMBOL", "BTCUSDT"))
        mdm.start()
    except Exception:
        logger.exception("Failed to start MarketDataManager; continuing with direct fetch")

    symbol = normalize_symbol(cfg.get("SYMBOL", "BTCUSDT"))
    interval = cfg.get("INTERVAL", "1m")
    strategy_name = cfg.get("STRATEGY", "macd")
    strategy_fn = strategy_macd if strategy_name == "macd" else (lambda w: strategy_xgb(w, model_mgr))

    while True:
        try:
            # global kill switch via filesystem
            if safety.kill_switch_engaged(cfg):
                logger.error("Kill switch engaged; shutting down trading loop")
                if tg:
                    try:
                        tg.send("Kill switch engaged; shutting down trading loop")
                    except Exception:
                        logger.exception("Failed to send kill switch telegram")
                break
            # prefer buffered market data from MarketDataManager
            try:
                df = mdm.get_latest(symbol)
                if df is None or len(df) < 50:
                    df = ex_mgr.fetch_ohlcv(symbol, interval, limit=200)
            except Exception:
                df = ex_mgr.fetch_ohlcv(symbol, interval, limit=200)
            check_volatility_alert(df, cfg, tg)
            sig = strategy_fn(df)
            if sig:
                latest = float(df.close.iloc[-1])
                atr_val = atr(df, int(cfg.get("ATR_PERIOD", 14))).iloc[-1]
                if math.isnan(atr_val) or atr_val <= 0:
                    logger.warning("ATR invalid; skipping trade")
                else:
                    stop_price = latest - float(cfg.get("ATR_MULTIPLIER", 1.5)) * atr_val if sig == "buy" else latest + float(cfg.get("ATR_MULTIPLIER", 1.5)) * atr_val
                    pos = trade_mgr.open_position(symbol, "buy" if sig == "buy" else "sell", latest, stop_price, None, float(cfg.get("TRAILING_PCT", 0.01)))
                    if pos:
                        logger.info("Trade opened: %s", pos)
            time.sleep(max(1, int(cfg.get("SLEEP_INTERVAL", 60))))
        except KeyboardInterrupt:
            logger.info("Interrupted by user; shutting down")
            monitor.running = False
            if heartbeat:
                heartbeat.running = False
            break
        except Exception:
            logger.exception("Error in main loop; continuing")
            time.sleep(5)


# -------------------- Unit Tests For Key Functions --------------------

def test_normalize_symbol():
    assert normalize_symbol("BTC/USDT") == "BTCUSDT"
    assert normalize_symbol("eth-usdt") == "ETHUSDT"


def test_atr_basic():
    data = {
        "open": [1, 2, 3, 4, 5],
        "high": [2, 3, 4, 5, 6],
        "low": [0.5, 1.5, 2.5, 3.5, 4.5],
        "close": [1.5, 2.5, 3.5, 4.5, 5.5],
    }
    df = pd.DataFrame(data)
    a = atr(df, period=2)
    assert len(a) == 5


def test_calc_qty():
    em = ExchangeManager(CONFIG)
    tm = TradeManager(em, CONFIG)
    qty = tm.calc_qty_by_risk(10000, 0.01, 50000, 49500)
    assert qty > 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="Path to config.json")
    parser.add_argument("--test-telegram", action="store_true", help="Run Telegram getUpdates and send test message")
    args = parser.parse_args()
    cfg = load_config(args.config)
    logger.info("Starting mega_trading_bot with config: %s", {k: cfg[k] for k in ["PAPER_MODE","EXCHANGE","SYMBOL","INTERVAL"] if k in cfg})
    try:
        tg = TelegramClient(cfg.get("TELEGRAM_BOT_TOKEN"), cfg.get("TELEGRAM_CHAT_ID"))
        if args.test_telegram:
            logger.info("Running Telegram test...")
            try:
                ups = tg.get_updates()
                logger.info("getUpdates: %s", ups)
            except Exception:
                logger.exception("getUpdates failed")
            try:
                resp = tg.send("Test message from mega_trading_bot --test-telegram")
                logger.info("send response: %s", resp)
            except Exception:
                logger.exception("send test failed")
        else:
            if cfg.get("RUN_BACKTEST") and cfg.get("BACKTEST_SYMBOL"):
                ex = ExchangeManager(cfg)
                df = ex.fetch_ohlcv(cfg.get("BACKTEST_SYMBOL"), cfg.get("INTERVAL", "1m"), limit=2000)
                bt = Backtester(df, cfg)
                metrics = bt.run_strategy(strategy_macd)
                logger.info("Backtest metrics: %s", metrics)
            else:
                main_loop(cfg)
    except Exception:
        logger.exception("Fatal error in bot")
