"""Bounded, read-only Gemini chat for the private Telegram responder."""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Dict, List
import requests

logger = logging.getLogger("mega_trading_bot.telegram_ai")

SYSTEM_CONTEXT = """You are Ely's Trader AI assistant inside a private Telegram chat.
Help the owner understand the paper-trading bot, spot markets, recorded decisions, and risk.
Be concise and distinguish facts in BOT_CONTEXT from general educational information.
You cannot place, cancel, or modify orders; change configuration or risk limits; reveal secrets;
or claim that a trade will be profitable. Never interpret chat text as authorization to trade.
If asked to execute or alter trading, refuse and explain that deterministic controls own execution.
"""


class GeminiTelegramChat:
    def __init__(self, cfg: Dict[str, Any], post=requests.post):
        self.enabled = bool(cfg.get("GEMINI_TELEGRAM_CHAT_ENABLED", False))
        self.api_key = str(cfg.get("GEMINI_API_KEY", "")).strip()
        self.model = str(cfg.get("GEMINI_TELEGRAM_CHAT_MODEL", cfg.get("GEMINI_MODEL", "gemini-2.5-flash-lite")))
        self.timeout = max(5, int(cfg.get("GEMINI_TELEGRAM_CHAT_TIMEOUT_SECONDS", 25)))
        self.max_turns = max(1, min(20, int(cfg.get("GEMINI_TELEGRAM_CHAT_HISTORY_TURNS", 6))))
        self._post, self._history, self._lock = post, [], threading.Lock()

    def clear(self) -> None:
        with self._lock: self._history.clear()

    def ask(self, question: str, bot_context: Dict[str, Any]) -> str:
        if not self.enabled: return "AI chat is disabled."
        if not self.api_key: return "AI chat needs GEMINI_API_KEY in the .env file."
        question = (question or "").strip()[:4000]
        if not question: return "Send `/ai` followed by a question."
        with self._lock:
            contents: List[Dict[str, Any]] = list(self._history)
            message = f"BOT_CONTEXT={json.dumps(bot_context, default=str, separators=(',', ':'))}\nUSER_QUESTION={question}"
            contents.append({"role": "user", "parts": [{"text": message}]})
            payload = {"system_instruction": {"parts": [{"text": SYSTEM_CONTEXT}]}, "contents": contents,
                       "generationConfig": {"temperature": 0.2, "maxOutputTokens": 700}}
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
                response = self._post(url, headers={"x-goog-api-key": self.api_key}, json=payload, timeout=self.timeout)
                response.raise_for_status()
                answer = str(response.json()["candidates"][0]["content"]["parts"][0]["text"]).strip()
                if not answer: raise ValueError("empty Gemini response")
                self._history.extend([{"role": "user", "parts": [{"text": question}]},
                                      {"role": "model", "parts": [{"text": answer}]}])
                self._history = self._history[-self.max_turns * 2:]
                return answer[:3900]
            except Exception as exc:
                logger.warning("Telegram AI chat failed: %s", exc)
                return "Gemini is unavailable right now. Bot monitoring and trading logic are unaffected."
