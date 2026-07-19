"""Yahoo-news-aware AI review of deterministic trade candidates."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import logging
import time
from typing import Any, Dict, List, Optional
import requests

logger = logging.getLogger("mega_trading_bot.investment_committee")
PROMPT_VERSION = "investment-committee-v1"
DECISIONS = {"APPROVE", "REJECT", "ABSTAIN"}
SENTIMENTS = {"BULLISH", "BEARISH", "NEUTRAL", "MIXED", "UNKNOWN"}
SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN"}


@dataclass(frozen=True)
class NewsArticle:
    title: str
    publisher: str
    url: str
    published_at: Optional[float]


@dataclass(frozen=True)
class CommitteeDecision:
    decision: str = "ABSTAIN"
    confidence: float = 0.0
    sentiment: str = "UNKNOWN"
    news_severity: str = "UNKNOWN"
    freshness_minutes: Optional[int] = None
    risks: tuple = ()
    reason: str = "AI evaluation unavailable"
    sources: tuple = ()
    model: str = ""
    prompt_version: str = PROMPT_VERSION
    latency_ms: int = 0


class NewsProvider:
    def fetch(self, symbol: str, limit: int = 8) -> List[NewsArticle]:
        raise NotImplementedError


class YahooFinanceNewsProvider(NewsProvider):
    endpoint = "https://query1.finance.yahoo.com/v1/finance/search"

    def __init__(self, get=requests.get, timeout: int = 10):
        self._get, self.timeout = get, timeout

    @staticmethod
    def yahoo_symbol(symbol: str) -> str:
        value = symbol.upper().replace("/", "").replace("-", "")
        return f"{value[:-4]}-USD" if value.endswith("USDT") else symbol

    def fetch(self, symbol: str, limit: int = 8) -> List[NewsArticle]:
        response = self._get(self.endpoint, params={"q": self.yahoo_symbol(symbol),
            "quotesCount": 1, "newsCount": limit}, headers={"User-Agent": "ElysTrader/1.0"},
            timeout=self.timeout)
        response.raise_for_status()
        articles = []
        for row in response.json().get("news", [])[:limit]:
            title, url = str(row.get("title", "")).strip(), str(row.get("link", "")).strip()
            if title and url:
                articles.append(NewsArticle(title, str(row.get("publisher", "Yahoo Finance")), url,
                    float(row["providerPublishTime"]) if row.get("providerPublishTime") else None))
        return articles


class GeminiInvestmentCommittee:
    def __init__(self, cfg: Dict[str, Any], news_provider: Optional[NewsProvider] = None,
                 post=requests.post, clock=time.time):
        self.enabled = bool(cfg.get("AI_COMMITTEE_ENABLED", False))
        self.shadow_mode = bool(cfg.get("AI_COMMITTEE_SHADOW_MODE", True))
        self.api_key = str(cfg.get("GEMINI_API_KEY", "")).strip()
        self.model = str(cfg.get("AI_COMMITTEE_MODEL", cfg.get("GEMINI_MODEL", "gemini-2.5-flash-lite")))
        self.timeout = max(5, int(cfg.get("AI_COMMITTEE_TIMEOUT_SECONDS", 25)))
        self.news_limit = max(1, min(20, int(cfg.get("YAHOO_NEWS_LIMIT", 8))))
        self.news = news_provider or YahooFinanceNewsProvider(timeout=int(cfg.get("YAHOO_NEWS_TIMEOUT_SECONDS", 10)))
        self._post, self._clock = post, clock

    def evaluate(self, candidate: Dict[str, Any]) -> CommitteeDecision:
        started = self._clock()
        if not self.enabled: return CommitteeDecision(reason="AI committee disabled")
        if not self.api_key: return CommitteeDecision(reason="GEMINI_API_KEY missing")
        try:
            articles = self.news.fetch(str(candidate["symbol"]), self.news_limit)
            if not articles:
                return CommitteeDecision(reason="Yahoo Finance news unavailable",
                    latency_ms=int((self._clock() - started) * 1000))
            result = self._request(candidate, articles)
            return CommitteeDecision(**result, latency_ms=int((self._clock() - started) * 1000))
        except Exception as exc:
            logger.warning("Investment Committee abstained: %s", exc)
            return CommitteeDecision(reason=f"evaluation failed: {type(exc).__name__}",
                latency_ms=int((self._clock() - started) * 1000))

    def _request(self, candidate: Dict[str, Any], articles: List[NewsArticle]) -> Dict[str, Any]:
        schema = {"type": "OBJECT", "properties": {
            "decision": {"type": "STRING", "enum": sorted(DECISIONS)}, "confidence": {"type": "NUMBER"},
            "sentiment": {"type": "STRING", "enum": sorted(SENTIMENTS)},
            "news_severity": {"type": "STRING", "enum": sorted(SEVERITIES)},
            "risks": {"type": "ARRAY", "items": {"type": "STRING"}}, "reason": {"type": "STRING"}},
            "required": ["decision", "confidence", "sentiment", "news_severity", "risks", "reason"]}
        prompt = {"candidate_trade": candidate, "recent_yahoo_finance_news": [asdict(a) for a in articles],
                  "instruction": "Evaluate this existing candidate. Do not propose another trade."}
        payload = {"system_instruction": {"parts": [{"text":
            "You are a conservative investment committee news reviewer. Evaluate, never create, a spot trade. "
            "Use only supplied facts. Detect conflicts and event risk. Return only schema JSON. Abstain when evidence is weak."}]},
            "contents": [{"role": "user", "parts": [{"text": json.dumps(prompt, separators=(",", ":"))}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "responseSchema": schema}}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        response = self._post(url, headers={"x-goog-api-key": self.api_key}, json=payload, timeout=self.timeout)
        response.raise_for_status()
        parsed = json.loads(response.json()["candidates"][0]["content"]["parts"][0]["text"])
        decision, sentiment, severity = (str(parsed.get(k, "")).upper() for k in ("decision", "sentiment", "news_severity"))
        confidence = float(parsed.get("confidence", 0))
        if decision not in DECISIONS or sentiment not in SENTIMENTS or severity not in SEVERITIES or not 0 <= confidence <= 1:
            raise ValueError("Gemini response failed semantic validation")
        published = [a.published_at for a in articles if a.published_at]
        freshness = max(0, int((self._clock() - max(published)) / 60)) if published else None
        return {"decision": decision, "confidence": confidence, "sentiment": sentiment,
            "news_severity": severity, "freshness_minutes": freshness,
            "risks": tuple(str(x) for x in parsed.get("risks", []))[:10], "reason": str(parsed.get("reason", ""))[:2000],
            "sources": tuple(a.url for a in articles), "model": self.model, "prompt_version": PROMPT_VERSION}


def log_ai_evaluation(tid, candidate_id: str, symbol: str, decision: CommitteeDecision) -> int:
    with tid.connection() as con:
        cur = con.execute("""INSERT INTO ai_evaluations
          (candidate_id,created_at,symbol,decision,confidence,sentiment,news_severity,freshness_minutes,
           risks,reason,sources,prompt_version,model_version,latency_ms,shadow_mode)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)""", (candidate_id, time.time(), symbol, decision.decision,
          decision.confidence, decision.sentiment, decision.news_severity, decision.freshness_minutes,
          json.dumps(decision.risks), decision.reason, json.dumps(decision.sources), decision.prompt_version,
          decision.model, decision.latency_ms))
        return int(cur.lastrowid)


def link_ai_evaluation(tid, evaluation_id: int, trade_id: str) -> None:
    with tid.connection() as con: con.execute("UPDATE ai_evaluations SET trade_id=? WHERE id=?", (trade_id, evaluation_id))


def ai_evaluation_summary(tid) -> Dict[str, Any]:
    with tid.connection(readonly=True) as con:
        rows = con.execute("SELECT decision,COUNT(*) count,AVG(confidence) confidence,AVG(latency_ms) latency FROM ai_evaluations GROUP BY decision").fetchall()
    return {r["decision"]: {"count": r["count"], "average_confidence": r["confidence"],
            "average_latency_ms": r["latency"]} for r in rows}
