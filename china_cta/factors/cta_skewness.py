"""Shared historical-skewness calculation used by absolute and CS factors."""

from __future__ import annotations

import numpy as np
import pandas as pd

from china_cta.factors.cta_common import require_research_prices, valid_price


def calculate_historical_skewness(
    continuous_prices: pd.DataFrame,
    *,
    lookback: int = 252,
    price_field: str = "close",
) -> pd.DataFrame:
    """Negative skewness from complete rolling return windows."""

    if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback < 3:
        raise ValueError("lookback must be an integer >= 3")
    require_research_prices(continuous_prices)

    required = ("trading_date", "underlying_symbol", price_field)
    missing = sorted(set(required) - set(continuous_prices.columns))
    if missing:
        raise ValueError(f"continuous_prices is missing fields: {missing}")
    prices = continuous_prices.loc[:, required].copy().rename(
        columns={"underlying_symbol": "instrument"}
    )
    prices["trading_date"] = pd.to_datetime(
        prices["trading_date"], errors="raise"
    ).dt.normalize()
    prices["instrument"] = (
        prices["instrument"].astype("string").str.strip().str.upper()
    )
    prices[price_field] = pd.to_numeric(prices[price_field], errors="coerce")
    if prices.duplicated(["trading_date", "instrument"]).any():
        raise ValueError("continuous_prices contains duplicate date/instrument rows")
    prices = prices.sort_values(["instrument", "trading_date"]).reset_index(drop=True)

    valid = valid_price(prices[price_field])
    daily_return = valid.groupby(
        prices["instrument"], sort=False
    ).pct_change(fill_method=None)
    grouped_returns = daily_return.groupby(prices["instrument"], sort=False)
    window_count = grouped_returns.transform(
        lambda values: values.rolling(lookback, min_periods=lookback).count()
    )
    raw_skewness = grouped_returns.transform(
        lambda values: values.rolling(lookback, min_periods=lookback).skew()
    )
    raw_skewness = raw_skewness.where(
        window_count.eq(lookback) & np.isfinite(raw_skewness)
    )

    result = prices.loc[:, ["trading_date", "instrument"]].copy()
    result["daily_return"] = daily_return.astype("float64")
    result["raw_skewness"] = raw_skewness.astype("float64")
    result["raw_factor"] = -result["raw_skewness"]
    return result.loc[
        :, ["trading_date", "instrument", "daily_return", "raw_skewness", "raw_factor"]
    ]
