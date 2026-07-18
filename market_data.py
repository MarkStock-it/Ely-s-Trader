"""Immutable, reproducible historical OHLCV datasets backed by CCXT."""
from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from backtesting.data_loader import REQUIRED_COLUMNS, validate_ohlcv

SCHEMA_VERSION = "1"
SUPPORTED_SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT")
SUPPORTED_TIMEFRAMES = ("15m", "1h", "4h")
TIMEFRAME_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}


def utc_iso(value) -> str:
    stamp = pd.Timestamp(value)
    stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
    return stamp.isoformat().replace("+00:00", "Z")


def parse_utc(value) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None: stamp = stamp.tz_localize("UTC")
    else: stamp = stamp.tz_convert("UTC")
    return stamp


def validate_market_data(data: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    df = validate_ohlcv(data)
    stamps = pd.to_datetime(df.timestamp, utc=True, errors="coerce")
    if stamps.isna().any(): raise ValueError("Invalid UTC timestamps")
    expected = pd.Timedelta(milliseconds=TIMEFRAME_MS[timeframe])
    gaps = stamps.diff().iloc[1:]
    invalid = gaps[gaps != expected]
    if not invalid.empty:
        index = int(invalid.index[0])
        actual = gaps.loc[index]
        if actual > expected:
            missing = int(actual / expected) - 1
            raise ValueError(f"Missing candles between {utc_iso(stamps.iloc[index-1])} and {utc_iso(stamps.iloc[index])}: {missing}")
        raise ValueError(f"Invalid candle interval at row {index}: expected {expected}, got {actual}")
    df["timestamp"] = stamps.map(utc_iso)
    return df


def canonical_csv(data: pd.DataFrame) -> bytes:
    output = io.StringIO(newline="")
    data.loc[:, REQUIRED_COLUMNS].to_csv(output, index=False, lineterminator="\n",
        float_format="%.12g")
    return output.getvalue().encode("utf-8")


def dataset_hash(data: pd.DataFrame) -> str:
    return hashlib.sha256(canonical_csv(data)).hexdigest()


class MarketDataStore:
    def __init__(self, root: str | Path = "data/market"):
        self.root = Path(root)

    @staticmethod
    def validate_selection(symbol: str, timeframe: str):
        if symbol not in SUPPORTED_SYMBOLS: raise ValueError(f"Unsupported symbol: {symbol}")
        if timeframe not in SUPPORTED_TIMEFRAMES: raise ValueError(f"Unsupported timeframe: {timeframe}")

    def save(self, data: pd.DataFrame, *, exchange: str, symbol: str, timeframe: str,
             downloaded_at: str | None = None) -> dict[str, Any]:
        self.validate_selection(symbol, timeframe)
        df = validate_market_data(data, timeframe)
        content = canonical_csv(df); digest = hashlib.sha256(content).hexdigest()
        start, end = df.timestamp.iloc[0], df.timestamp.iloc[-1]
        folder = self.root / exchange / symbol.replace("/", "_") / timeframe
        folder.mkdir(parents=True, exist_ok=True)
        stem = f"{start.replace(':','').replace('-','')}_{end.replace(':','').replace('-','')}_{digest[:16]}"
        csv_path, metadata_path = folder / f"{stem}.csv", folder / f"{stem}.metadata.json"
        metadata = {"exchange": exchange, "symbol": symbol, "timeframe": timeframe,
            "start": start, "end": end, "candle_count": len(df),
            "download_time": downloaded_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "schema_version": SCHEMA_VERSION, "dataset_hash": digest,
            "dataset_file": csv_path.name}
        encoded_metadata = (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode()
        if csv_path.exists() and csv_path.read_bytes() != content:
            raise FileExistsError(f"Refusing to alter historical dataset: {csv_path}")
        if metadata_path.exists() and metadata_path.read_bytes() != encoded_metadata:
            existing = json.loads(metadata_path.read_text(encoding="utf-8"))
            # Download time is provenance, but an existing immutable artifact wins.
            if any(existing.get(k) != metadata.get(k) for k in metadata if k != "download_time"):
                raise FileExistsError(f"Refusing to alter dataset metadata: {metadata_path}")
            return {**existing, "csv_path": str(csv_path), "metadata_path": str(metadata_path)}
        if not csv_path.exists():
            with csv_path.open("xb") as handle: handle.write(content)
        if not metadata_path.exists():
            with metadata_path.open("xb") as handle: handle.write(encoded_metadata)
        return {**metadata, "csv_path": str(csv_path), "metadata_path": str(metadata_path)}

    def load(self, metadata_or_hash: str | Path) -> tuple[pd.DataFrame, dict]:
        candidate = Path(metadata_or_hash)
        if candidate.exists(): metadata_path = candidate
        else:
            matches = [p for p in self.root.rglob("*.metadata.json")
                       if json.loads(p.read_text(encoding="utf-8")).get("dataset_hash") == str(metadata_or_hash)]
            if len(matches) != 1: raise FileNotFoundError(f"Dataset hash not found uniquely: {metadata_or_hash}")
            metadata_path = matches[0]
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("schema_version") != SCHEMA_VERSION: raise ValueError("Unsupported dataset schema version")
        csv_path = metadata_path.parent / metadata["dataset_file"]
        content = csv_path.read_bytes()
        actual = hashlib.sha256(content).hexdigest()
        if actual != metadata.get("dataset_hash"): raise ValueError("Dataset hash mismatch; file may have been altered")
        df = validate_market_data(pd.read_csv(io.BytesIO(content)), metadata["timeframe"])
        if len(df) != metadata["candle_count"] or df.timestamp.iloc[0] != metadata["start"] or df.timestamp.iloc[-1] != metadata["end"]:
            raise ValueError("Dataset metadata does not match candle contents")
        return df, {**metadata, "csv_path": str(csv_path), "metadata_path": str(metadata_path)}

    def list(self, *, symbols=None, timeframes=None) -> list[dict]:
        results = []
        for path in sorted(self.root.rglob("*.metadata.json")) if self.root.exists() else []:
            metadata = json.loads(path.read_text(encoding="utf-8"))
            if symbols and metadata.get("symbol") not in symbols: continue
            if timeframes and metadata.get("timeframe") not in timeframes: continue
            results.append({**metadata, "metadata_path": str(path)})
        return results


def download_ohlcv(provider, store: MarketDataStore, *, exchange: str, symbol: str,
                   timeframe: str, start, end, limit: int = 1000):
    store.validate_selection(symbol, timeframe)
    start_ms, end_ms = int(parse_utc(start).timestamp() * 1000), int(parse_utc(end).timestamp() * 1000)
    if end_ms <= start_ms: raise ValueError("Dataset end must be after start")
    interval_ms = TIMEFRAME_MS[timeframe]
    if start_ms % interval_ms or end_ms % interval_ms:
        raise ValueError("Dataset start and end must align to candle boundaries")
    exchange_client = getattr(provider, "exchange", provider)
    rows, since = [], start_ms
    while since <= end_ms:
        batch = exchange_client.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=limit)
        if not batch: break
        rows.extend(row[:6] for row in batch if start_ms <= int(row[0]) <= end_ms)
        last = int(batch[-1][0])
        if last < since: raise ValueError("Exchange returned out-of-order pagination")
        since = last + TIMEFRAME_MS[timeframe]
        if last >= end_ms: break
    if not rows: raise ValueError("Exchange returned no candles for requested range")
    if int(rows[0][0]) != start_ms or int(rows[-1][0]) != end_ms:
        raise ValueError("Exchange response is missing requested boundary candles")
    df = pd.DataFrame(rows, columns=REQUIRED_COLUMNS)
    df["timestamp"] = pd.to_datetime(df.timestamp, unit="ms", utc=True)
    return store.save(df, exchange=exchange, symbol=symbol, timeframe=timeframe)
