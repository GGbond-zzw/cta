"""Eligible-universe cross-sectional ranks of historical return skewness."""

from __future__ import annotations

import numpy as np
import pandas as pd

from china_cta.factors.cta_skewness import calculate_historical_skewness
from china_cta.factors.schema import make_factor_table


def _cross_sectional_rank_score(values: pd.Series) -> pd.Series:
    """Map valid same-date ranks to [-1, 1], leaving fewer than two peers NA."""

    result = pd.Series(np.nan, index=values.index, dtype="float64")
    valid = values.dropna()
    if len(valid) < 2:
        return result
    ranks = valid.rank(method="average", ascending=True)
    result.loc[valid.index] = 2.0 * (ranks - 1.0) / (len(valid) - 1.0) - 1.0
    return result


def compute_historical_skewness_factor_cs_rank(
    continuous_prices: pd.DataFrame,
    universe: pd.DataFrame,
    *,
    lookback: int = 252,
    price_field: str = "close",
) -> pd.DataFrame:
    """Rank ``-historical_skewness`` within each eligible daily universe."""

    diagnostics = calculate_historical_skewness(
        continuous_prices, lookback=lookback, price_field=price_field
    )
    factor_name = f"historical_skewness_{lookback}d_cs_rank"
    eligible_raw = make_factor_table(
        diagnostics.loc[:, ["trading_date", "instrument", "raw_factor"]],
        universe,
        factor_name=factor_name,
        signal_scale=1.0,
    )
    eligible_raw["raw_factor"] = eligible_raw.groupby(
        "trading_date", sort=False
    )["raw_factor"].transform(_cross_sectional_rank_score)
    result = make_factor_table(
        eligible_raw.loc[:, ["trading_date", "instrument", "raw_factor"]],
        universe,
        factor_name=factor_name,
        signal_scale=1.0,
    )
    result.attrs.update(
        {
            "definition": (
                "per_date_eligible_cross_sectional_rank_of("
                "-rolling_skewness(close_to_close_return, lookback))"
            ),
            "lookback_trading_periods": lookback,
            "price_field": price_field,
            "adjust_method": "prev_close_ratio",
            "direction": "long_relative_negative_skewness_short_relative_positive_skewness",
            "raw_factor_normalization": (
                "per_date_eligible_cross_sectional_rank_mapped_to_minus1_plus1"
            ),
            "rank_tie_method": "average",
            "minimum_valid_peers": 2,
            "skewness_estimator": "pandas_rolling_unbiased_skewness",
        }
    )
    return result


def build(inputs: dict) -> pd.DataFrame:
    return compute_historical_skewness_factor_cs_rank(
        inputs["continuous_prices"], inputs["universe"]
    )
