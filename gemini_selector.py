"""Gemini-assisted ranking for a controlled spot-market allowlist."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import time
from typing import Any, Dict, List, Optional

import requests


logger = logging.getLogger("mega_trading_bot.gemini")

SYSTEM_CONTEXT = """You are a conservative institutional cryptocurrency spot-market analyst.
Rank only the supplied liquid USDT spot pairs using only the supplied numerical market data.
Prefer adequate liquidity, positive trend, healthy volume, and tradable but controlled volatility.
Do not invent news, prices, indicators, or symbols. Do not recommend leverage, shorts, or trades.
Your ranking is advisory: deterministic strategy, execution, and risk controls make all decisions.
"""


@dataclass(frozen=True)
class SymbolSelection:
    symbols: List[str]
    source: str
    reason: str


class GeminiSymbolSelector:
    def __init__(self, cfg: Dict[str, Any], post=requests.post, clock=time.time):
        self.enabled = bool(cfg.get("GEMINI_SYMBOL_SELECTOR_ENABLED", False))
        self.api_key = str(cfg.get("GEMINI_API_KEY", "")).strip()
        self.model = str(cfg.get("GEMINI_MODEL", "gemini-2.5-flash-lite")).strip()
        self.top_n = max(1, int(cfg.get("GEMINI_SYMBOL_COUNT", 3)))
        self.refresh_seconds = max(60, int(cfg.get("GEMINI_REFRESH_SECONDS", 1800)))
        self.timeout = max(5, int(cfg.get("GEMINI_TIMEOUT_SECONDS", 20)))
        self._post = post
        self._clock = clock
        self._cached: Optional[SymbolSelection] = None
        self._cached_at = 0.0

    def select(self, market_summaries: List[Dict[str, Any]], force: bool = False) -> SymbolSelection:
        allowed = [str(row.get("symbol", "")).upper() for row in market_summaries if row.get("symbol")]
        fallback = SymbolSelection(allowed[: self.top_n], "fallback", "configured liquid-symbol order")
        if not self.enabled:
            return fallback
        if not self.api_key:
            logger.warning("Gemini selector enabled but GEMINI_API_KEY is missing; using fallback")
            return fallback
        now = self._clock()
        if not force and self._cached and now - self._cached_at < self.refresh_seconds:
            return self._cached
        try:
            result = self._request(market_summaries, allowed)
            self._cached, self._cached_at = result, now
            return result
        except Exception as exc:
            logger.warning("Gemini symbol selection failed; using fallback: %s", exc)
            return self._cached or fallback

    def _request(self, market_summaries: List[Dict[str, Any]], allowed: List[str]) -> SymbolSelection:
        schema = {
            "type": "OBJECT",
            "properties": {
                "rankings": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "symbol": {"type": "STRING"},
                            "score": {"type": "NUMBER"},
                            "reason": {"type": "STRING"},
                        },
                        "required": ["symbol", "score", "reason"],
                    },
                },
                "market_summary": {"type": "STRING"},
            },
            "required": ["rankings", "market_summary"],
        }
        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_CONTEXT}]},
            "contents": [{"role": "user", "parts": [{"text": json.dumps({
                "task": f"Rank the best {min(self.top_n, len(allowed))} symbols for monitoring.",
                "allowed_symbols": allowed,
                "market_data": market_summaries,
            }, separators=(",", ":"))}]}],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
                "responseSchema": schema,
            },
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        response = self._post(url, headers={"x-goog-api-key": self.api_key}, json=payload, timeout=self.timeout)
        response.raise_for_status()
        body = response.json()
        text = body["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
        ranked: List[str] = []
        reasons: List[str] = []
        allowed_set = set(allowed)
        for row in parsed.get("rankings", []):
            symbol = str(row.get("symbol", "")).upper()
            if symbol in allowed_set and symbol not in ranked:
                ranked.append(symbol)
                reasons.append(f"{symbol}: {row.get('reason', '')}")
            if len(ranked) >= self.top_n:
                break
        if not ranked:
            raise ValueError("Gemini returned no valid allowlisted symbols")
        return SymbolSelection(ranked, "gemini", "; ".join(reasons))

