from analytics.database import TradingIntelligenceDatabase
from investment_committee import (GeminiInvestmentCommittee, NewsArticle, YahooFinanceNewsProvider,
                                  ai_evaluation_summary, link_ai_evaluation, log_ai_evaluation)


class News:
    def fetch(self, symbol, limit=8):
        return [NewsArticle("Bitcoin adoption expands", "Yahoo Finance", "https://finance.yahoo.com/a", 940)]


class Response:
    def raise_for_status(self): pass
    def json(self):
        return {"candidates": [{"content": {"parts": [{"text":
            '{"decision":"APPROVE","confidence":0.8,"sentiment":"BULLISH",'
            '"news_severity":"LOW","risks":["volatility"],"reason":"Fresh positive report"}'}]}}]}


def test_yahoo_symbol_mapping():
    assert YahooFinanceNewsProvider.yahoo_symbol("BTCUSDT") == "BTC-USD"
    assert YahooFinanceNewsProvider.yahoo_symbol("ETH/USDT") == "ETH-USD"


def test_committee_returns_schema_validated_decision():
    committee = GeminiInvestmentCommittee({"AI_COMMITTEE_ENABLED": True, "GEMINI_API_KEY": "key"},
        news_provider=News(), post=lambda *a, **k: Response(), clock=lambda: 1000)
    result = committee.evaluate({"symbol": "BTCUSDT", "side": "BUY_SPOT"})
    assert result.decision == "APPROVE" and result.confidence == 0.8
    assert result.freshness_minutes == 1 and result.sources == ("https://finance.yahoo.com/a",)


def test_committee_fails_safe_without_key():
    result = GeminiInvestmentCommittee({"AI_COMMITTEE_ENABLED": True}, news_provider=News()).evaluate({"symbol": "BTCUSDT"})
    assert result.decision == "ABSTAIN" and "missing" in result.reason


def test_evaluation_is_queryable_and_linked(tmp_path):
    tid = TradingIntelligenceDatabase(tmp_path / "trades.db", asynchronous=False)
    decision = GeminiInvestmentCommittee({"AI_COMMITTEE_ENABLED": True, "GEMINI_API_KEY": "key"},
        news_provider=News(), post=lambda *a, **k: Response(), clock=lambda: 1000).evaluate({"symbol": "BTCUSDT"})
    evaluation_id = log_ai_evaluation(tid, "candidate-1", "BTCUSDT", decision)
    link_ai_evaluation(tid, evaluation_id, "trade-1")
    with tid.connection(readonly=True) as con:
        row = con.execute("SELECT * FROM ai_evaluations").fetchone()
    assert row["trade_id"] == "trade-1" and row["shadow_mode"] == 1
    assert ai_evaluation_summary(tid)["APPROVE"]["count"] == 1
