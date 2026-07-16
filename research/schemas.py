from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math
from typing import Any


def utc(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None: parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def finite(value, name):
    if isinstance(value, bool): raise ValueError(f"{name} has incorrect type")
    result = float(value)
    if not math.isfinite(result): raise ValueError(f"{name} must be finite")
    return result


@dataclass(frozen=True)
class ResearchRequest:
    request_id: str; strategy_id: str; strategy_version: str; symbol: str; timeframe: str
    direction: str; strategy_parameters: dict; risk_parameters: dict
    execution_assumptions: dict; data_period: dict; minimum_oos_trades: int
    minimum_expectancy: float; maximum_drawdown: float; minimum_confidence: float
    created_at: str; strategy_source_hash: str = ""
    minimum_profit_factor: float | None = None

    def __post_init__(self):
        if self.direction != "long": raise ValueError("Only long research is supported")
        if not self.request_id or not self.strategy_id or not self.symbol or not self.timeframe: raise ValueError("request identifiers are required")
        if self.minimum_oos_trades < 0: raise ValueError("minimum_oos_trades must be non-negative")
        finite(self.minimum_expectancy, "minimum_expectancy"); finite(self.maximum_drawdown, "maximum_drawdown")
        confidence = finite(self.minimum_confidence, "minimum_confidence")
        if not 0 <= confidence <= 1 or not 0 <= self.maximum_drawdown <= 100: raise ValueError("threshold out of range")
        utc(self.created_at)

    def to_dict(self): return asdict(self)
    def fingerprint_payload(self):
        value = self.to_dict()
        for key in ("request_id", "created_at", "minimum_oos_trades", "minimum_expectancy",
                    "maximum_drawdown", "minimum_confidence", "minimum_profit_factor"):
            value.pop(key, None)
        return value


@dataclass(frozen=True)
class ResearchResult:
    schema_version: int; request_id: str; strategy_id: str; symbol: str; timeframe: str
    direction: str; generated_at: str; data_start: str; data_end: str
    in_sample_metrics: dict; out_of_sample_metrics: dict; confidence: float
    warnings: list; limitations: list; source_run_id: str; configuration_fingerprint: str

    @classmethod
    def parse(cls, value: Any):
        if not isinstance(value, dict): raise ValueError("structured JSON object required")
        required = set(cls.__dataclass_fields__)
        missing = sorted(required - set(value))
        if missing: raise ValueError("missing fields: " + ", ".join(missing))
        obj = cls(**{k: value[k] for k in required})
        obj.validate_types(); return obj

    def validate_types(self):
        if self.schema_version != 1: raise ValueError("unsupported schema version")
        if self.direction != "long": raise ValueError("unsupported direction")
        if not all(isinstance(x, str) and x for x in (self.request_id, self.strategy_id, self.symbol, self.timeframe, self.source_run_id, self.configuration_fingerprint)): raise ValueError("incorrect string field")
        if not isinstance(self.warnings, list) or not isinstance(self.limitations, list): raise ValueError("warnings and limitations must be lists")
        if not isinstance(self.in_sample_metrics, dict) or not isinstance(self.out_of_sample_metrics, dict): raise ValueError("metrics must be objects")
        confidence = finite(self.confidence, "confidence")
        if not 0 <= confidence <= 1: raise ValueError("confidence outside 0-1")
        required = {"trade_count", "expectancy", "maximum_drawdown_percentage", "net_return_percentage", "profit_factor"}
        missing = required - set(self.out_of_sample_metrics)
        if missing: raise ValueError("missing OOS metrics: " + ", ".join(sorted(missing)))
        count = self.out_of_sample_metrics["trade_count"]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0: raise ValueError("invalid trade_count")
        for key in required - {"trade_count"}: finite(self.out_of_sample_metrics[key], key)
        dd = float(self.out_of_sample_metrics["maximum_drawdown_percentage"])
        if not 0 <= dd <= 100: raise ValueError("drawdown outside 0-100")
        utc(self.generated_at); utc(self.data_start); utc(self.data_end)

    def to_dict(self): return asdict(self)
