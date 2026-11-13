"""Price-change times open-interest growth (unqualified)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from china_cta.factors.cta_common import (
    normalize_continuous,
    rolling_count,
    standard_table,
    valid_price,
)


FACTOR_NAME = "oi_price_confirm_20"
SIGNAL_SCALE = 0.20


def calculate_oi_price_confirm_20(
    continuous_prices: pd.DataFrame, *, lookback: int = 20
) -> pd.DataFrame:
    if lookback < 1:
        raise ValueError("lookback must be a positive integer")
    prices = normalize_continuous(continuous_prices, ("close", "open_interest"))
    close = valid_price(prices["close"])
    open_interest = prices["open_interest"].where(
        np.isfinite(prices["open_interest"]) & prices["open_interest"].gt(0)
    )
    instrument = prices["instrument"]
    previous_close = close.groupby(instrument, sort=False).shift(lookback)
    previous_oi = open_interest.groupby(instrument, sort=False).shift(lookback)
    price_count = rolling_count(close, instrument, window=lookback + 1)
    oi_count = rolling_count(open_interest, instrument, window=lookback + 1)
    raw = np.sign(close - previous_close) * np.log(open_interest / previous_oi)
    raw = raw.where(
        price_count.eq(lookback + 1)
        & oi_count.eq(lookback + 1)
        & np.isfinite(raw)
    )
    result = prices.loc[:, ["trading_date", "instrument"]].copy()
    result["raw_factor"] = raw
    return result


def build(inputs: dict) -> pd.DataFrame:
    raw = calculate_oi_price_confirm_20(inputs["continuous_prices"])
    return standard_table(
        raw,
        inputs["universe"],
        factor_name=FACTOR_NAME,
        signal_scale=SIGNAL_SCALE,
        family="E_positioning",
        definition="sign_price_change_20_times_log_oi_ratio_20",
        lookback_trading_periods=20,
        price_field="close_open_interest",
        direction="IC+ prior; repository call: ~0 in China",
        raw_factor_normalization="signed_log_growth",
    )
