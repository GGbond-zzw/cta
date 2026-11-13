"""Shared time-series momentum calculation used by several catalog factors."""

from __future__ import annotations

import numpy as np
import pandas as pd

from china_cta.factors.cta_common import (
    normalize_continuous,
    valid_price,
)


def calculate_time_series_momentum(
    continuous_prices: pd.DataFrame,
    *,
    lookback: int = 252,
    skip: int = 0,
) -> pd.DataFrame:
    """Return ``P_{t-skip} / P_{t-lookback} - 1`` on a complete price window."""

    if lookback < 2:
        raise ValueError("lookback must be >= 2")
    if skip < 0 or skip >= lookback:
        raise ValueError("skip must satisfy 0 <= skip < lookback")
    prices = normalize_continuous(continuous_prices, ("close",))
    close = prices["close"]
    instrument = prices["instrument"]
    numerator = close.groupby(instrument, sort=False).shift(skip)
    denominator = close.groupby(instrument, sort=False).shift(lookback)
    # The complete window runs from t-lookback to t-skip, not to t.
    span = lookback - skip + 1
    valid_flag = valid_price(close).notna().astype("float64")
    complete_at_numerator = valid_flag.groupby(instrument, sort=False).transform(
        lambda values: values.rolling(span, min_periods=span).min()
    )
    complete = complete_at_numerator.groupby(instrument, sort=False).shift(skip)
    raw = (numerator / denominator - 1.0).where(complete.eq(1.0))
    raw = raw.where(np.isfinite(raw))
    result = prices.loc[:, ["trading_date", "instrument"]].copy()
    result["raw_factor"] = raw
    return result
