"""Fast/slow EMA crossover (unqualified)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from china_cta.factors.cta_common import (
    annualized_volatility,
    normalize_continuous,
    standard_table,
    valid_price,
)


FACTOR_NAME = "ema_xover_20_100"
SIGNAL_SCALE = 0.50


def calculate_ema_xover(
    continuous_prices: pd.DataFrame,
    *,
    fast: int = 20,
    slow: int = 100,
    volatility_window: int = 20,
) -> pd.DataFrame:
    """Fast/slow EMA spread normalized by volatility times price."""

    if not 2 <= fast < slow:
        raise ValueError("require 2 <= fast < slow")
    if volatility_window < 2:
        raise ValueError("volatility_window must be >= 2")
    prices = normalize_continuous(continuous_prices, ("close",))
    close = valid_price(prices["close"])
    instrument = prices["instrument"]
    ema_fast = close.groupby(instrument, sort=False).transform(
        lambda values: values.ewm(
            span=fast, adjust=False, min_periods=fast
        ).mean()
    )
    ema_slow = close.groupby(instrument, sort=False).transform(
        lambda values: values.ewm(
            span=slow, adjust=False, min_periods=slow
        ).mean()
    )
    volatility = annualized_volatility(
        close, instrument, window=volatility_window
    )
    denominator = volatility * close
    raw = (ema_fast - ema_slow) / denominator.where(denominator.gt(0))
    raw = raw.where(np.isfinite(raw))
    result = prices.loc[:, ["trading_date", "instrument"]].copy()
    result["raw_factor"] = raw
    return result


def build(inputs: dict) -> pd.DataFrame:
    raw = calculate_ema_xover(inputs["continuous_prices"])
    return standard_table(
        raw,
        inputs["universe"],
        factor_name=FACTOR_NAME,
        signal_scale=SIGNAL_SCALE,
        family="A_time_series_momentum",
        definition="ema20_minus_ema100_over_hv20_times_price",
        fast_window=20,
        slow_window=100,
        volatility_window=20,
        price_field="close",
        adjust_method="prev_close_ratio",
        direction="IC+ prior; repository call: IC- reversal",
        raw_factor_normalization="volatility_and_price",
    )
