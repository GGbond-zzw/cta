"""Causal expression language used by the mined candidate sleeves.

Ported from the frozen export package (`expressions.py`, package sha256 recorded in
`factors.json`) so the mined formulas can be rebuilt natively and re-tuned with the
project's Bayesian optimiser.  The operator semantics are kept identical:

* windowed operators require a full window (`min_periods=window`),
* `delta` is a difference of levels, `ts_rank` is a positive percentile,
* `corr` is the rolling Pearson correlation of two aligned columns,
* infinities are replaced by NaN, and missing values are never forward filled.
"""

from __future__ import annotations

from typing import Any, Final, Mapping

import numpy as np
import pandas as pd

UNARY: Final[tuple[str, ...]] = ("mean", "std", "delta", "ts_rank", "neg", "abs")
BINARY: Final[tuple[str, ...]] = ("add", "sub", "mul", "div", "corr")
WINDOWED: Final[tuple[str, ...]] = ("mean", "std", "delta", "ts_rank", "corr")

FEATURE_COLUMNS: Final[tuple[str, ...]] = (
    "close",
    "high",
    "low",
    "volume",
    "open_interest",
    "total_turnover",
)


def _wide(
    panel: pd.DataFrame, field: str, dates: pd.DatetimeIndex, instruments: list[str]
) -> pd.DataFrame:
    values = panel.pivot(index="trading_date", columns="instrument", values=field)
    return values.reindex(index=dates, columns=instruments)


def compute_features(
    panel: pd.DataFrame,
    *,
    dates: pd.DatetimeIndex | None = None,
    instruments: list[str] | None = None,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Return the causal feature panels plus the wide close matrix."""

    required = [column for column in FEATURE_COLUMNS if column in panel.columns]
    for column in ("close", "high", "low", "volume", "open_interest"):
        if column not in panel.columns:
            raise ValueError(f"panel is missing the {column!r} column")

    if dates is None:
        dates = pd.DatetimeIndex(sorted(pd.to_datetime(panel["trading_date"]).unique()))
    if instruments is None:
        instruments = sorted(panel["instrument"].astype(str).unique())

    def wide(field: str) -> pd.DataFrame:
        return _wide(panel, field, dates, instruments)

    close = wide("close")
    if (close[close.notna()] <= 0).any().any():
        raise ValueError("research closes must be positive")
    returns = close / close.shift(1) - 1
    features: dict[str, pd.DataFrame] = {
        "return_1": returns,
        "return_5": close / close.shift(5) - 1,
        "return_20": close / close.shift(20) - 1,
        "return_60": close / close.shift(60) - 1,
        "range_ratio": (wide("high") - wide("low")) / close,
        "volatility_20": returns.rolling(20, min_periods=20).std(ddof=1),
    }
    volatility_60 = returns.rolling(60, min_periods=60).std(ddof=1)
    features["volatility_ratio"] = features["volatility_20"] / volatility_60.where(
        volatility_60 > 1e-10
    )

    high_20 = wide("high").rolling(20, min_periods=20).max()
    low_20 = wide("low").rolling(20, min_periods=20).min()
    width = high_20 - low_20
    features["channel_position_20"] = (close - low_20) / width.where(width > 1e-10) - 0.5

    for field, key in (
        ("volume", "volume_change"),
        ("open_interest", "oi_change"),
        ("total_turnover", "turnover_change"),
    ):
        if field not in required:
            continue
        value = wide(field)
        features[key] = value / value.shift(5).where(value.shift(5) > 0) - 1

    for field, key in (
        ("volume", "volume_surprise_20"),
        ("open_interest", "oi_surprise_20"),
        ("total_turnover", "turnover_surprise_20"),
    ):
        if field not in required:
            continue
        value = wide(field)
        history = value.shift(1).rolling(20, min_periods=20).mean()
        features[key] = value / history.where(history > 0) - 1

    if "total_turnover" in required:
        open_interest = wide("open_interest")
        features["volume_oi_ratio"] = wide("volume") / open_interest.where(open_interest > 0)

    features["price_oi_interaction"] = features["return_5"] * features["oi_change"]
    features["risk_adjusted_momentum_20"] = features["return_20"] / (
        features["volatility_20"].where(features["volatility_20"] > 1e-10) * np.sqrt(20)
    )

    cleaned = {key: value.replace([np.inf, -np.inf], np.nan) for key, value in features.items()}
    return cleaned, close


def evaluate(node: Mapping[str, Any], features: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Evaluate an expression tree against pre-computed feature panels."""

    op = node["op"]
    if op == "feature":
        name = node["name"]
        if name not in features:
            raise ValueError(f"unknown feature {name!r}")
        return features[name]

    args = [evaluate(arg, features) for arg in node.get("args", [])]
    window = node.get("window")

    if op == "mean":
        out = args[0].rolling(window, min_periods=window).mean()
    elif op == "std":
        out = args[0].rolling(window, min_periods=window).std(ddof=1)
    elif op == "delta":
        out = args[0] - args[0].shift(window)
    elif op == "ts_rank":
        out = args[0].rolling(window, min_periods=window).rank(pct=True)
    elif op == "neg":
        out = -args[0]
    elif op == "abs":
        out = args[0].abs()
    elif op == "add":
        out = args[0] + args[1]
    elif op == "sub":
        out = args[0] - args[1]
    elif op == "mul":
        out = args[0] * args[1]
    elif op == "div":
        out = args[0] / args[1].where(args[1].abs() > 1e-8)
    elif op == "corr":
        out = args[0].rolling(window, min_periods=window).corr(args[1])
    else:
        raise ValueError(f"unknown expression operator {op!r}")
    return out.replace([np.inf, -np.inf], np.nan)


def feature_node(name: str) -> dict[str, Any]:
    return {"op": "feature", "name": name}


def unary(op: str, arg: dict[str, Any], window: int | None = None) -> dict[str, Any]:
    node: dict[str, Any] = {"op": op, "args": [arg]}
    if window is not None:
        node["window"] = int(window)
    return node


def binary(
    op: str, left: dict[str, Any], right: dict[str, Any], window: int | None = None
) -> dict[str, Any]:
    node: dict[str, Any] = {"op": op, "args": [left, right]}
    if window is not None:
        node["window"] = int(window)
    return node


def to_long(matrix: pd.DataFrame, *, factor_name: str) -> pd.DataFrame:
    """Flatten a wide feature matrix into the (trading_date, instrument, raw_factor) shape."""

    stacked = matrix.rename_axis(index="trading_date", columns="instrument").stack()
    stacked.name = "raw_factor"
    frame = stacked.reset_index()
    frame["trading_date"] = pd.to_datetime(frame["trading_date"])
    frame["instrument"] = frame["instrument"].astype(str)
    frame = frame.loc[frame["raw_factor"].notna()].reset_index(drop=True)
    frame["factor_name"] = factor_name
    return frame.loc[:, ["trading_date", "instrument", "raw_factor", "factor_name"]]
