"""Point-in-time rolling volatility for the Phase 5 portfolio layer."""

from __future__ import annotations

import math
from typing import Final

import numpy as np
import pandas as pd


VOLATILITY_COLUMNS: Final[tuple[str, ...]] = (
    "trading_date",
    "instrument",
    "raw_volatility",
    "vol_forecast",
    "vol_floor_applied",
)


def compute_rolling_volatility(
    continuous_prices: pd.DataFrame,
    *,
    lookback: int,
    minimum_observations: int,
    annualization_factor: int,
    volatility_floor: float,
    price_field: str = "close",
) -> pd.DataFrame:
    """Return an annualized rolling close-to-close volatility forecast.

    The observation dated ``t`` uses only ratio-adjusted research prices
    through the close of ``t``. Missing prices are never filled. A raw
    volatility that is missing, zero, or negative remains unavailable; the
    positive floor only guards small, otherwise valid forecasts.
    """

    _validate_settings(
        lookback,
        minimum_observations,
        annualization_factor,
        volatility_floor,
    )
    if continuous_prices.attrs.get("usage") != "signal_research_only":
        raise ValueError(
            "volatility requires Phase 2 signal/research continuous prices"
        )
    if continuous_prices.attrs.get("cash_pnl_allowed") is not False:
        raise ValueError("volatility input must be prohibited from cash P&L")
    if continuous_prices.attrs.get("adjust_type") != "pre" or (
        continuous_prices.attrs.get("adjust_method") != "prev_close_ratio"
    ):
        raise ValueError(
            "volatility requires pre-adjusted prev_close_ratio prices"
        )

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
    prices[price_field] = prices[price_field].where(
        np.isfinite(prices[price_field]) & prices[price_field].gt(0)
    )
    if prices.duplicated(["trading_date", "instrument"]).any():
        raise ValueError("continuous_prices contains duplicate date/instrument rows")
    prices = prices.sort_values(["instrument", "trading_date"]).reset_index(
        drop=True
    )

    returns = prices.groupby("instrument", sort=False)[price_field].pct_change(
        fill_method=None
    )
    rolling = returns.groupby(prices["instrument"], sort=False).transform(
        lambda values: values.rolling(
            lookback,
            min_periods=minimum_observations,
        ).std(ddof=1)
    )
    raw = rolling * math.sqrt(annualization_factor)
    raw = raw.where(np.isfinite(raw) & raw.gt(0))

    result = prices.loc[:, ["trading_date", "instrument"]].copy()
    result["raw_volatility"] = raw.astype("float64")
    result["vol_forecast"] = result["raw_volatility"].clip(
        lower=float(volatility_floor)
    )
    result["vol_floor_applied"] = (
        result["raw_volatility"].notna()
        & result["raw_volatility"].lt(float(volatility_floor))
    )
    result = result.loc[:, VOLATILITY_COLUMNS]
    result.attrs.update(
        {
            "method": "rolling_close_to_close_simple_return",
            "return_definition": "price_t / price_t_minus_1 - 1",
            "information_date": "trading_date",
            "available_at": "after_close_of_trading_date",
            "lookback": lookback,
            "minimum_observations": minimum_observations,
            "annualization_factor": annualization_factor,
            "volatility_floor": float(volatility_floor),
            "missing_price_rule": "no_fill",
            "non_positive_volatility_rule": "unavailable",
        }
    )
    return result


def _validate_settings(
    lookback: int,
    minimum_observations: int,
    annualization_factor: int,
    volatility_floor: float,
) -> None:
    for name, value in (
        ("lookback", lookback),
        ("minimum_observations", minimum_observations),
        ("annualization_factor", annualization_factor),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    if minimum_observations < 2 or minimum_observations > lookback:
        raise ValueError(
            "minimum_observations must be between 2 and lookback"
        )
    if not np.isfinite(volatility_floor) or volatility_floor <= 0:
        raise ValueError("volatility_floor must be a positive finite number")
