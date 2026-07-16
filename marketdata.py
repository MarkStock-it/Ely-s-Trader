"""marketdata.py

Provides MarketDataManager: background polling (and Binance websocket fallback)
that maintains an OHLCV buffer per symbol and allows subscribers to register
callbacks for new candle updates.
"""
import threading
import time
import logging
import metrics
from typing import Dict, Any, Callable, List

import pandas as pd

logger = logging.getLogger("mega_trading_bot.marketdata")


class MarketDataManager:
    def __init__(self, ex_mgr, cfg: Dict[str, Any]):
        self.ex_mgr = ex_mgr
        self.cfg = cfg
        self.buffers: Dict[str, pd.DataFrame] = {}
        self.callbacks: Dict[str, List[Callable[[pd.DataFrame], None]]] = {}
        self.subscribed: set = set()
        self.poll_interval = float(cfg.get("MD_POLL_INTERVAL", 5))
        self.timeframe = cfg.get("INTERVAL", "1m")
        self.limit = int(cfg.get("MD_BUFFER_LIMIT", 500))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("MarketDataManager started; poll_interval=%s", self.poll_interval)

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def subscribe(self, symbol: str, callback: Callable[[pd.DataFrame], None] | None = None):
        sym = symbol.upper().replace("/", "").replace("-", "")
        self.subscribed.add(sym)
        if callback:
            self.callbacks.setdefault(sym, []).append(callback)
        # prime buffer
        try:
            df = self.ex_mgr.fetch_ohlcv(sym, self.timeframe, limit=self.limit)
            self.buffers[sym] = df
        except Exception:
            logger.exception("Failed to prime buffer for %s", sym)

    def get_latest(self, symbol: str) -> pd.DataFrame | None:
        sym = symbol.upper().replace("/", "").replace("-", "")
        return self.buffers.get(sym)

    def _run(self):
        while not self._stop.is_set():
            for sym in list(self.subscribed):
                try:
                    df = self.ex_mgr.fetch_ohlcv(sym, self.timeframe, limit=self.limit)
                    try:
                        metrics.MD_FETCHES.inc()
                        metrics.MD_BUFFER_SIZE.set(len(df) if df is not None else 0)
                        metrics.LAST_MD_FETCH.set(time.time())
                    except Exception:
                        pass
                    old = self.buffers.get(sym)
                    self.buffers[sym] = df
                    # detect new candle(s)
                    if old is None or len(df) > len(old):
                        # call callbacks
                        for cb in self.callbacks.get(sym, []):
                            try:
                                cb(df)
                            except Exception:
                                logger.exception("Callback failed for %s", sym)
                except Exception:
                    logger.exception("MarketData fetch failed for %s", sym)
                time.sleep(min(self.poll_interval, 1))
            # sleep between cycles
            time.sleep(self.poll_interval)
