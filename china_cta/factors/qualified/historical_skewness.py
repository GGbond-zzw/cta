"""Absolute historical return skewness factor (unqualified)."""

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


def build(inputs: dict) -> pd.DataFrame:
    return compute_historical_skewness_factor(
        inputs["continuous_prices"], inputs["universe"]
    )
