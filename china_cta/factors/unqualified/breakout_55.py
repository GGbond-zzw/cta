"""Donchian breakout position (qualified)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from china_cta.factors.cta_common import (
    normalize_continuous,
    rolling_count,
    standard_table,
    valid_price,
)


FACTOR_NAME = "breakout_55"
SIGNAL_SCALE = 1.0


def calculate_breakout_55(
    continuous_prices: pd.DataFrame, *, window: int = 55
) -> pd.DataFrame:
    """Donchian breakout position in [-1, 1] from continuous high/low prices."""

    if window < 2:
        raise ValueError("window must be >= 2")
    prices = normalize_continuous(continuous_prices, ("close", "high", "low"))
    instrument = prices["instrument"]
    high = valid_price(prices["high"])
    low = valid_price(prices["low"])
    close = valid_price(prices["close"])
    high_max = high.groupby(instrument, sort=False).transform(
        lambda values: values.rolling(window, min_periods=window).max()
    )
    low_min = low.groupby(instrument, sort=False).transform(
        lambda values: values.rolling(window, min_periods=window).min()
    )
    count_high = rolling_count(high, instrument, window=window)
    count_low = rolling_count(low, instrument, window=window)
    mid = (high_max + low_min) / 2.0
    half_range = 0.5 * (high_max - low_min)
    raw = ((close - mid) / half_range.where(half_range.gt(0))).clip(-1.0, 1.0)
    raw = raw.where(
        count_high.eq(window) & count_low.eq(window) & np.isfinite(raw)
    )
    result = prices.loc[:, ["trading_date", "instrument"]].copy()
    result["raw_factor"] = raw
    return result


def build(inputs: dict) -> pd.DataFrame:
    raw = calculate_breakout_55(inputs["continuous_prices"], window=55)
    return standard_table(
        raw,
        inputs["universe"],
        factor_name=FACTOR_NAME,
        signal_scale=SIGNAL_SCALE,
        family="A_time_series_momentum",
        definition="clip_close_minus_donchian_mid_over_half_range",
        breakout_window=55,
        price_field="close_high_low",
        adjust_method="prev_close_ratio",
        direction="IC+ prior; repository call: IC- reversal",
        raw_factor_normalization="bounded_minus1_plus1",
    )
