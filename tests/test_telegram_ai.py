from telegram_ai import GeminiTelegramChat


class Response:
    def raise_for_status(self): pass
    def json(self):
        return {"candidates": [{"content": {"parts": [{"text": "The bot is in paper spot mode."}]}}]}


def test_chat_sends_sanitized_context_and_keeps_bounded_history():
    calls = []
    chat = GeminiTelegramChat({"GEMINI_TELEGRAM_CHAT_ENABLED": True, "GEMINI_API_KEY": "secret",
        "GEMINI_TELEGRAM_CHAT_HISTORY_TURNS": 1}, post=lambda *a, **k: calls.append(k) or Response())
    assert "paper spot" in chat.ask("What mode?", {"mode": "PAPER", "trading_mode": "spot"})
    chat.ask("And now?", {"mode": "PAPER"})
    assert calls[0]["headers"] == {"x-goog-api-key": "secret"}
    assert "BOT_CONTEXT" in calls[0]["json"]["contents"][0]["parts"][0]["text"]
    assert len(chat._history) == 2


def test_chat_fails_closed_without_key():
    chat = GeminiTelegramChat({"GEMINI_TELEGRAM_CHAT_ENABLED": True})
    assert "GEMINI_API_KEY" in chat.ask("hello", {})

