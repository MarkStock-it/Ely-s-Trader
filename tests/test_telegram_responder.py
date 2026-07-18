import threading

from analytics.database import TradingIntelligenceDatabase
from mega_trading_bot import TelegramClient, TelegramResponder


class Response:
    def raise_for_status(self): pass
    def json(self): return {"ok": True, "result": {"message_id": 1}}


class TradeManager:
    def __init__(self):
        self.lock = threading.Lock(); self.open_positions = {}
    def summary(self):
        return {"cash": 50, "net_equity": 51, "open_positions": 0,
                "realized_pnl": 1, "unrealized_pnl": 0}


def test_telegram_send_reaches_send_message(monkeypatch):
    calls = []
    monkeypatch.setattr("mega_trading_bot.requests.post", lambda url, json, timeout: calls.append((url, json)) or Response())
    result = TelegramClient("token", "123").send("hello")
    assert result["ok"] and calls == [("https://api.telegram.org/bottoken/sendMessage", {"chat_id": "123", "text": "hello"})]


def test_responder_is_read_only_and_reports_status(tmp_path):
    tid = TradingIntelligenceDatabase(tmp_path / "tid.db", asynchronous=False)
    responder = TelegramResponder(TelegramClient("token", "123"), TradeManager(), tid,
                                  {"PAPER_MODE": True})
    assert "Mode: PAPER" in responder.response("/status")
    assert responder.response("/positions") == "No open paper positions."
    assert "No completed trades" in responder.response("/lasttrade")
    assert "Trading commands are disabled" in responder.response("/buy BTCUSDT")
    assert "/why" in responder.response("hello")
