import csv
import json
import math
from pathlib import Path


def export_json(result, path: str):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(_json_safe(result.to_dict() if hasattr(result, "to_dict") else result), handle,
                  indent=2, default=str, allow_nan=False)
    return path


def export_csv(result, path: str):
    """Export a self-describing multi-section CSV (summary, trades, equity)."""
    obj = result.to_dict() if hasattr(result, "to_dict") else result
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        for section in ("configuration", "metadata", "metrics"):
            writer.writerow([section]); writer.writerow(["key", "value"])
            writer.writerows((k, _safe(v)) for k, v in obj.get(section, {}).items())
        for section in ("trades", "equity", "ranking"):
            rows = obj.get(section, [])
            if rows:
                writer.writerow([section]); writer.writerow(rows[0].keys())
                writer.writerows([_safe(v) for v in row.values()] for row in rows)
    return path


def _safe(value):
    if isinstance(value, float) and not math.isfinite(value): return str(value)
    if isinstance(value, (dict, list)): return json.dumps(value, default=str)
    return value


def _json_safe(value):
    if isinstance(value, dict): return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list): return [_json_safe(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value): return str(value)
    return value
