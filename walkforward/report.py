import csv
import json
import math
from pathlib import Path


def write_reports(result, directory="reports"):
    root = Path(directory); root.mkdir(parents=True, exist_ok=True)
    json_path, csv_path = root / "walkforward_summary.json", root / "walkforward_summary.csv"
    json_path.write_text(json.dumps(_safe(result), indent=2, default=str, allow_nan=False), encoding="utf-8")
    fields = ["strategy", "window", "is_metrics", "validation_metrics", "oos_metrics",
              "qualification_result", "degradation_pct", "stability_score"]
    summaries = {x["strategy"]: x for x in result["strategies"]}
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
        for row in result["windows"]:
            summary = summaries[row["strategy"]]
            writer.writerow({"strategy": row["strategy"], "window": row["window"],
                "is_metrics": json.dumps(_safe(row["is_metrics"])),
                "validation_metrics": json.dumps(_safe(row["validation_metrics"])),
                "oos_metrics": json.dumps(_safe(row["oos_metrics"])),
                "qualification_result": summary["qualification_result"],
                "degradation_pct": summary["degradation_pct"], "stability_score": summary["stability_score"]})
    return str(json_path), str(csv_path)


def _safe(value):
    if isinstance(value, dict): return {k: _safe(v) for k, v in value.items()}
    if isinstance(value, list): return [_safe(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value): return str(value)
    return value
