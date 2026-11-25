"""Absolute historical return skewness factor (qualified sleeve)."""

from __future__ import annotations

from typing import Final

import pandas as pd

from china_cta.factors.cta_skewness import calculate_historical_skewness
from china_cta.factors.schema import make_factor_table


HISTORICAL_SKEWNESS_DIAGNOSTIC_COLUMNS: Final[tuple[str, ...]] = (
    "trading_date",
    "instrument",
    "daily_return",
    "raw_skewness",
    "raw_factor",
)


def compute_historical_skewness_factor(
    continuous_prices: pd.DataFrame,
    universe: pd.DataFrame,
    *,
    lookback: int = 252,
    signal_scale: float = 1.0,
    price_field: str = "close",
) -> pd.DataFrame:
    """Return the standard absolute historical-skewness factor."""

    diagnostics = calculate_historical_skewness(
        continuous_prices, lookback=lookback, price_field=price_field
    )
    result = make_factor_table(
        diagnostics.loc[:, ["trading_date", "instrument", "raw_factor"]],
        universe,
        factor_name=f"historical_skewness_{lookback}d",
        signal_scale=signal_scale,
    )
    result.attrs.update(
        {
            "definition": "-rolling_skewness(close_to_close_return, lookback)",
            "lookback_trading_periods": lookback,
            "price_field": price_field,
            "adjust_method": "prev_close_ratio",
            "direction": "long_negative_skewness_short_positive_skewness",
            "raw_factor_normalization": "none",
            "skewness_estimator": "pandas_rolling_unbiased_skewness",
        }
    )
    return result

PARAMETERS: Final[dict] = {
    "lookback": 441,
    "signal_scale": 0.9999802791509596,
}


def _finalize(table: pd.DataFrame, name: str) -> pd.DataFrame:
    """Stamp the canonical factor name so every package emits its own key."""

    out = table.copy()
    out["factor_name"] = name
    out.attrs["factor_name"] = name
    return out


def _settings(params: dict | None) -> dict:
    merged = dict(PARAMETERS)
    merged.update({key: value for key, value in (params or {}).items() if value is not None})
    return merged

def build(inputs: dict, params: dict | None = None) -> pd.DataFrame:
    settings = _settings(params)
    table = compute_historical_skewness_factor(
        inputs["continuous_prices"],
        inputs["universe"],
        lookback=int(settings["lookback"]),
        signal_scale=float(settings["signal_scale"]),
    )
    return _finalize(table, "historical_skewness_252d")
