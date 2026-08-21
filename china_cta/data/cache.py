"""Small Parquet cache used by the RQData adapter."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


CACHE_SCHEMA_VERSION = 1


class CacheError(RuntimeError):
    """Raised when an existing cache entry is incomplete or inconsistent."""


def read_frame(
    cache_dir: Path,
    operation: str,
    request_params: Mapping[str, Any],
) -> pd.DataFrame | None:
    """Return a cached frame, or ``None`` when no entry exists."""

    parquet_path, metadata_path = _paths(cache_dir, operation, request_params)
    if not parquet_path.exists() and not metadata_path.exists():
        return None
    if not parquet_path.is_file() or not metadata_path.is_file():
        raise CacheError(f"Incomplete cache entry: {parquet_path.parent}")

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        frame = pd.read_parquet(parquet_path)
    except Exception as exc:
        raise CacheError(f"Unable to read cache entry: {parquet_path}") from exc

    expected_params = _jsonable(dict(request_params))
    if metadata.get("operation") != operation:
        raise CacheError(f"Cache operation mismatch: {metadata_path}")
    if metadata.get("cache_schema_version") != CACHE_SCHEMA_VERSION:
        raise CacheError(f"Cache schema version mismatch: {metadata_path}")
    if metadata.get("request_params") != expected_params:
        raise CacheError(f"Cache parameters mismatch: {metadata_path}")
    if metadata.get("columns") != list(frame.columns):
        raise CacheError(f"Cache column metadata mismatch: {metadata_path}")
    if metadata.get("row_count") != len(frame):
        raise CacheError(f"Cache row-count metadata mismatch: {metadata_path}")
    return frame


def write_frame(
    cache_dir: Path,
    operation: str,
    request_params: Mapping[str, Any],
    frame: pd.DataFrame,
    *,
    rqdatac_version: str,
) -> None:
    """Write one frame and its minimal reproducibility metadata."""

    parquet_path, metadata_path = _paths(cache_dir, operation, request_params)
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    parquet_temp = parquet_path.with_suffix(".parquet.tmp")
    metadata_temp = metadata_path.with_suffix(".json.tmp")
    metadata = {
        "operation": operation,
        "cache_schema_version": CACHE_SCHEMA_VERSION,
        "request_params": _jsonable(dict(request_params)),
        "fetch_time_utc": datetime.now(timezone.utc).isoformat(),
        "rqdatac_version": rqdatac_version,
        "row_count": len(frame),
        "columns": list(frame.columns),
    }

    try:
        frame.to_parquet(parquet_temp, index=False)
        metadata_temp.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        parquet_temp.replace(parquet_path)
        metadata_temp.replace(metadata_path)
    finally:
        parquet_temp.unlink(missing_ok=True)
        metadata_temp.unlink(missing_ok=True)


def _paths(
    cache_dir: Path,
    operation: str,
    request_params: Mapping[str, Any],
) -> tuple[Path, Path]:
    payload = json.dumps(
        {
            "operation": operation,
            "cache_schema_version": CACHE_SCHEMA_VERSION,
            "request_params": _jsonable(dict(request_params)),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    cache_key = hashlib.sha256(payload).hexdigest()
    operation_dir = cache_dir / operation
    return (
        operation_dir / f"{cache_key}.parquet",
        operation_dir / f"{cache_key}.metadata.json",
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported cache parameter type: {type(value).__name__}")
