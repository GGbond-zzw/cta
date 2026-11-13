"""Negative 20-day realized volatility (unqualified)."""

from __future__ import annotations

import pandas as pd

from china_cta.factors.cta_common import (
    annualized_volatility,
    normalize_continuous,
    standard_table,
    valid_price,
)


FACTOR_NAME = "lowvol"
SIGNAL_SCALE = 0.20


def calculate_lowvol(
    continuous_prices: pd.DataFrame, *, window: int = 20
) -> pd.DataFrame:
    if window < 2:
        raise ValueError("window must be >= 2")
    prices = normalize_continuous(continuous_prices, ("close",))
    close = valid_price(prices["close"])
    volatility = annualized_volatility(close, prices["instrument"], window=window)
    result = prices.loc[:, ["trading_date", "instrument"]].copy()
    result["raw_factor"] = -volatility
    return result


def build(inputs: dict) -> pd.DataFrame:
    raw = calculate_lowvol(inputs["continuous_prices"])
    return standard_table(
        raw,
        inputs["universe"],
        factor_name=FACTOR_NAME,
        signal_scale=SIGNAL_SCALE,
        family="G_volatility_and_reversal",
        definition="negative_20d_annualized_log_return_volatility",
        volatility_window=20,
        price_field="close",
        adjust_method="prev_close_ratio",
        direction="IC+ prior; repository call: strongest IC+ but weak tradable Sharpe",
        raw_factor_normalization="annualized_volatility",
    )
