from gemini_selector import GeminiSymbolSelector


class Response:
    def raise_for_status(self): pass
    def json(self):
        return {"candidates": [{"content": {"parts": [{"text":
            '{"rankings":[{"symbol":"ETHUSDT","score":90,"reason":"trend"},'
            '{"symbol":"NOTALLOWED","score":99,"reason":"invalid"},'
            '{"symbol":"BTCUSDT","score":80,"reason":"liquid"}],"market_summary":"ok"}'}]}}]}


def rows():
    return [{"symbol": "BTCUSDT", "return_20": 0.01}, {"symbol": "ETHUSDT", "return_20": 0.02}]


def test_gemini_ranking_is_allowlisted_and_cached():
    calls = []
    selector = GeminiSymbolSelector({"GEMINI_SYMBOL_SELECTOR_ENABLED": True, "GEMINI_API_KEY": "secret",
        "GEMINI_SYMBOL_COUNT": 2}, post=lambda *a, **k: calls.append((a, k)) or Response(), clock=lambda: 100)
    assert selector.select(rows()).symbols == ["ETHUSDT", "BTCUSDT"]
    assert selector.select(rows()).source == "gemini"
    assert len(calls) == 1
    assert calls[0][1]["headers"] == {"x-goog-api-key": "secret"}


def test_missing_key_falls_back_without_network():
    selector = GeminiSymbolSelector({"GEMINI_SYMBOL_SELECTOR_ENABLED": True, "GEMINI_SYMBOL_COUNT": 1})
    result = selector.select(rows())
    assert result.symbols == ["BTCUSDT"] and result.source == "fallback"

