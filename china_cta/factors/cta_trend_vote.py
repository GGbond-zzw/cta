"""Shared slow direction-voting trend calculation used by trend factors."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
import pandas as pd

from china_cta.factors.cta_common import require_research_prices


def calculate_consistent_trend(
    continuous_prices: pd.DataFrame,
    *,
    horizons: Sequence[int] = (63, 126, 252),
    smoothing_span: int = 10,
    deadband: float = 0.05,
    rebalance_every: int = 5,
    volatility_halflife: int = 20,
    target_annualized_volatility: float = 0.15,
    price_field: str = "close",
) -> pd.DataFrame:
    """Vote across slow trend directions, then reduce high-volatility exposure."""

    normalized_horizons = _validate_horizons(horizons)
    if (
        isinstance(smoothing_span, bool)
        or not isinstance(smoothing_span, int)
        or smoothing_span < 1
    ):
        raise ValueError("smoothing_span must be a positive integer")
    if not np.isfinite(deadband) or not 0 <= deadband < 1:
        raise ValueError("deadband must be finite and between 0 and 1")
    if (
        isinstance(rebalance_every, bool)
        or not isinstance(rebalance_every, int)
        or rebalance_every < 1
    ):
        raise ValueError("rebalance_every must be a positive integer")
    if (
        isinstance(volatility_halflife, bool)
        or not isinstance(volatility_halflife, int)
        or volatility_halflife < 2
    ):
        raise ValueError("volatility_halflife must be an integer >= 2")
    if (
        not np.isfinite(target_annualized_volatility)
        or target_annualized_volatility <= 0
    ):
        raise ValueError("target_annualized_volatility must be positive and finite")
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

    instrument = prices["instrument"]
    valid_price = prices[price_field].where(
        np.isfinite(prices[price_field]) & prices[price_field].gt(0)
    )
    log_price = np.log(valid_price)
    daily_log_return = log_price.groupby(instrument, sort=False).diff()
    annualized_volatility = daily_log_return.groupby(
        instrument, sort=False
    ).transform(
        lambda values: values.ewm(
            halflife=volatility_halflife,
            adjust=False,
            min_periods=2,
        ).std(bias=False)
    ) * math.sqrt(252)
    risk_multiplier = (
        target_annualized_volatility / annualized_volatility
    ).clip(upper=1.0)
    risk_multiplier = risk_multiplier.where(
        annualized_volatility.notna(), np.nan
    )
    risk_multiplier = risk_multiplier.where(annualized_volatility.gt(0), 1.0)
    components: list[pd.Series] = []
    for horizon in normalized_horizons:
        grouped_price = valid_price.groupby(instrument, sort=False)
        valid_count = grouped_price.transform(
            lambda values, window=horizon + 1: values.rolling(
                window, min_periods=window
            ).count()
        )
        net_log_return = log_price - log_price.groupby(
            instrument, sort=False
        ).shift(horizon)
        component = np.sign(net_log_return)
        component = component.where(
            valid_count.eq(horizon + 1)
            & np.isfinite(component)
        )
        components.append(component)

    component_frame = pd.concat(components, axis=1)
    complete = component_frame.notna().all(axis=1)
    consensus = component_frame.mean(axis=1).where(complete)
    smoothed = consensus.groupby(instrument, sort=False).transform(
        lambda values: values.ewm(
            span=smoothing_span, adjust=False, min_periods=1
        ).mean()
    )
    with_deadband = smoothed.where(smoothed.abs().ge(deadband), 0.0)
    risk_scaled = with_deadband * risk_multiplier
    observation_number = prices.groupby("instrument", sort=False).cumcount()
    update = observation_number.mod(rebalance_every).eq(0)
    tradable = risk_scaled.where(update).groupby(
        instrument, sort=False
    ).ffill()
    tradable = tradable.where(consensus.notna())

    result = prices.loc[:, ["trading_date", "instrument"]].copy()
    result["trend_consensus"] = consensus
    result["smoothed_consensus"] = smoothed
    result["annualized_volatility"] = annualized_volatility
    result["risk_multiplier"] = risk_multiplier
    result["raw_factor"] = tradable
    return result.loc[
        :,
        [
            "trading_date",
            "instrument",
            "trend_consensus",
            "smoothed_consensus",
            "annualized_volatility",
            "risk_multiplier",
            "raw_factor",
        ],
    ]


def _validate_horizons(horizons: Sequence[int]) -> tuple[int, ...]:
    values = tuple(horizons)
    if not values or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 2
        for value in values
    ):
        raise ValueError("horizons must contain integers >= 2")
    if len(set(values)) != len(values):
        raise ValueError("horizons cannot contain duplicates")
    return tuple(sorted(values))
