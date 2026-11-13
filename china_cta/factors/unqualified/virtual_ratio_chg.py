"""Change in the OI/volume virtual-ratio proxy (unqualified)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from china_cta.factors.cta_common import (
    normalize_continuous,
    rolling_count,
    standard_table,
)


FACTOR_NAME = "virtual_ratio_chg"
SIGNAL_SCALE = 0.20


def calculate_virtual_ratio_chg(
    continuous_prices: pd.DataFrame, *, lookback: int = 20
) -> pd.DataFrame:
    if lookback < 1:
        raise ValueError("lookback must be a positive integer")
    prices = normalize_continuous(continuous_prices, ("volume", "open_interest"))
    volume = prices["volume"].where(
        np.isfinite(prices["volume"]) & prices["volume"].gt(0)
    )
    open_interest = prices["open_interest"].where(
        np.isfinite(prices["open_interest"]) & prices["open_interest"].gt(0)
    )
    ratio = (open_interest / volume).where(
        np.isfinite(open_interest / volume)
    )
    instrument = prices["instrument"]
    previous = ratio.groupby(instrument, sort=False).shift(lookback)
    count = rolling_count(ratio, instrument, window=lookback + 1)
    raw = (ratio - previous).where(count.eq(lookback + 1))
    result = prices.loc[:, ["trading_date", "instrument"]].copy()
    result["raw_factor"] = raw
    return result


def build(inputs: dict) -> pd.DataFrame:
    raw = calculate_virtual_ratio_chg(inputs["continuous_prices"])
    return standard_table(
        raw,
        inputs["universe"],
        factor_name=FACTOR_NAME,
        signal_scale=SIGNAL_SCALE,
        family="E_positioning",
        definition="change_in_open_interest_over_volume_ratio_20d",
        lookback_trading_periods=20,
        price_field="volume_open_interest",
        direction="exploratory; repository call: not tested",
        raw_factor_normalization="none",
        proxy=True,
        proxy_note="virtual ratio uses OI/volume because the provider has no direct field",
    )
