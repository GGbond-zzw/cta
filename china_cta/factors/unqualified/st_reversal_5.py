"""Five-day short-term reversal (unqualified)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from china_cta.factors.cta_common import (
    lagged_return,
    normalize_continuous,
    standard_table,
)


FACTOR_NAME = "st_reversal_5"
SIGNAL_SCALE = 0.05


def calculate_st_reversal_5(
    continuous_prices: pd.DataFrame, *, window: int = 5
) -> pd.DataFrame:
    if window < 1:
        raise ValueError("window must be a positive integer")
    prices = normalize_continuous(continuous_prices, ("close",))
    raw = -lagged_return(prices["close"], prices["instrument"], lag=window)
    raw = raw.where(np.isfinite(raw))
    result = prices.loc[:, ["trading_date", "instrument"]].copy()
    result["raw_factor"] = raw
    return result


def build(inputs: dict) -> pd.DataFrame:
    raw = calculate_st_reversal_5(inputs["continuous_prices"])
    return standard_table(
        raw,
        inputs["universe"],
        factor_name=FACTOR_NAME,
        signal_scale=SIGNAL_SCALE,
        family="G_volatility_and_reversal",
        definition="negative_5d_simple_return",
        lookback_trading_periods=5,
        price_field="close",
        adjust_method="prev_close_ratio",
        direction="IC+ prior; repository call: IC+",
        raw_factor_normalization="none",
    )
