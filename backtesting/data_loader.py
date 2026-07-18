import math
import os
from pathlib import Path
from typing import Any

import pandas as pd

REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")


def validate_ohlcv(data: pd.DataFrame, *, sort_unordered: bool = False) -> pd.DataFrame:
    missing = [c for c in REQUIRED_COLUMNS if c not in data.columns]
    if missing:
        raise ValueError("Missing required columns: " + ", ".join(missing))
    df = data.loc[:, REQUIRED_COLUMNS].copy()
    if df.empty:
        raise ValueError("Historical data is empty")
    if df["timestamp"].isna().any():
        raise ValueError("Invalid timestamp values")
    if df["timestamp"].duplicated().any():
        values = df.loc[df["timestamp"].duplicated(False), "timestamp"].astype(str).tolist()
        raise ValueError(f"Duplicate timestamps: {values}")
    if not df["timestamp"].is_monotonic_increasing:
        if not sort_unordered:
            raise ValueError("Timestamps must be ordered")
        import warnings
        warnings.warn("Unordered timestamps were explicitly sorted", UserWarning)
        df = df.sort_values("timestamp").reset_index(drop=True)
    for column in REQUIRED_COLUMNS[1:]:
        converted = pd.to_numeric(df[column], errors="coerce")
        bad = converted.isna() | ~converted.map(lambda x: bool(pd.notna(x)) and math.isfinite(float(x)))
        if bad.any():
            raise ValueError(f"Invalid numeric value in {column} at rows {df.index[bad].tolist()}")
        df[column] = converted.astype(float)
    if (df[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("Prices must be greater than zero")
    if (df["volume"] < 0).any():
        raise ValueError("Volume must not be negative")
    if ((df["high"] < df[["open", "close", "low"]].max(axis=1)) |
            (df["low"] > df[["open", "close", "high"]].min(axis=1))).any():
        raise ValueError("OHLC price relationships are invalid")
    df.attrs["missing_candles"] = detect_missing_candles(df)
    return df


def detect_missing_candles(df: pd.DataFrame):
    parsed = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    if parsed.isna().any() or len(parsed) < 3:
        return []
    gaps = parsed.diff().dropna()
    interval = gaps.mode().iloc[0]
    return [{"after": str(parsed.iloc[i - 1]), "before": str(parsed.iloc[i]),
             "missing": int(gaps.iloc[i - 1] / interval) - 1}
            for i in range(1, len(parsed)) if gaps.iloc[i - 1] > interval]


def load_csv(path: str, *, sort_unordered: bool = False) -> pd.DataFrame:
    try:
        return validate_ohlcv(pd.read_csv(path), sort_unordered=sort_unordered)
    except pd.errors.ParserError as exc:
        raise ValueError(f"Invalid CSV: {exc}") from exc


def load_market_dataset(metadata_or_hash: str, *, root: str = "data/market"):
    """Deterministically reload a validated immutable dataset without network access."""
    from market_data import MarketDataStore
    return MarketDataStore(root).load(metadata_or_hash)


def load_provider(provider: Any, symbol: str, timeframe: str, *, limit: int = 2000,
                  cache_dir: str = "data/backtesting") -> pd.DataFrame:
    """Download through the existing read-only provider and cache as CSV."""
    raw = provider.fetch_ohlcv(symbol, timeframe, limit=limit)
    if not isinstance(raw, pd.DataFrame):
        raw = pd.DataFrame(raw, columns=REQUIRED_COLUMNS)
    df = validate_ohlcv(raw)
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    safe = symbol.replace("/", "_").replace(":", "_")
    df.to_csv(os.path.join(cache_dir, f"{safe}_{timeframe}.csv"), index=False)
    return df
