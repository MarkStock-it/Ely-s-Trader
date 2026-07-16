"""Read-only gate for previously validated research approvals."""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from research.factory import request_from_config
from research.hashing import configuration_fingerprint
from research.schemas import utc

@dataclass(frozen=True)
class VibeDecision:
    allowed: bool; reason: str; risk_multiplier: float = 0.0; confidence: float = 0.0
    research_id: str | None = None; state: str = "MISSING"

class VibeResearchGate:
    def __init__(self, cfg: dict[str, Any], strategy=None):
        self.cfg, self.strategy = cfg, strategy
        self.enabled = bool(cfg.get("VIBETRADER_ENABLED", False)); self.enforce = bool(cfg.get("VIBETRADER_ENFORCE", True))
        default = Path(cfg.get("RESEARCH_DATA_PATH", "data/research")) / "current_approval.json"
        self.path = Path(cfg.get("VIBETRADER_APPROVAL_FILE", default))
    def evaluate(self, symbol, timeframe, signal):
        if signal != "buy": return VibeDecision(True, "exits bypass research gate", 1.0, state="VALID")
        if not self.enabled: return VibeDecision(True, "research gate disabled", 1.0, state="DISABLED")
        try:
            p = json.loads(self.path.read_text(encoding="utf-8")); now = datetime.now(timezone.utc)
            expected = configuration_fingerprint(request_from_config(self.cfg, p.get("strategy_id"), symbol, timeframe), self.strategy)
            if p.get("configuration_fingerprint") != expected: return self._deny("configuration mismatch", "CONFIG_MISMATCH")
            if _symbol(p.get("symbol")) != _symbol(symbol) or p.get("timeframe") != timeframe: return self._deny("symbol/timeframe mismatch", "CONFIG_MISMATCH")
            if p.get("direction") != "long": return self._deny("unsupported direction", "REJECTED")
            if utc(p["expires_at"]) <= now: return self._deny("approval expired", "EXPIRED")
            state = "EXPIRING" if utc(p["refresh_after"]) <= now else "VALID"
            multiplier = min(1.0, max(0.0, float(p["risk_multiplier"])))
            return VibeDecision(True, "validated research approval", multiplier, float(p["confidence"]), p.get("research_id"), state)
        except Exception as exc: return self._deny(f"approval unavailable: {exc}", "MISSING")
    def _deny(self, reason, state):
        return VibeDecision(not self.enforce, reason, 1.0 if not self.enforce else 0.0, state=state)

def _symbol(value): return str(value).upper().replace("/", "").replace("-", "")
