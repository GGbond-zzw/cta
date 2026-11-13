"""Multi-horizon, volatility-normalized trend for commodity futures."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Final

import numpy as np
import pandas as pd

from china_cta.factors.schema import make_factor_table


MULTI_HORIZON_TREND_DIAGNOSTIC_COLUMNS: Final[tuple[str, ...]] = (
    "trading_date",
    "instrument",
    "annualized_volatility",
    "valid_horizons",
    "raw_factor",
)


def calculate_multi_horizon_trend(
    continuous_prices: pd.DataFrame,
    *,
    horizons: Sequence[int] = (20, 60, 120, 252),
    volatility_lookback: int = 60,
    annualization_factor: int = 252,
    component_clip: float | None = 3.0,
    price_field: str = "close",
) -> pd.DataFrame:
    """Average risk-adjusted price momentum over several horizons.

    For horizon ``h`` the component is the ``h``-period simple return divided
    by the volatility forecast scaled to ``h`` periods. All configured
    horizons must be available; prices are never filled.
    """

    normalized_horizons = _validate_horizons(horizons)
    if (
        isinstance(volatility_lookback, bool)
        or not isinstance(volatility_lookback, int)
        or volatility_lookback < 2
    ):
        raise ValueError("volatility_lookback must be an integer >= 2")
    if (
        isinstance(annualization_factor, bool)
        or not isinstance(annualization_factor, int)
        or annualization_factor < 1
    ):
        raise ValueError("annualization_factor must be a positive integer")
    if component_clip is not None and (
        not np.isfinite(component_clip) or component_clip <= 0
    ):
        raise ValueError("component_clip must be None or a positive finite number")
    _validate_research_prices(continuous_prices)

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
    daily_return = valid_price.groupby(instrument, sort=False).pct_change(
        fill_method=None
    )
    daily_volatility = daily_return.groupby(instrument, sort=False).transform(
        lambda values: values.rolling(
            volatility_lookback, min_periods=volatility_lookback
        ).std(ddof=1)
    )
    annualized_volatility = daily_volatility * math.sqrt(annualization_factor)
    annualized_volatility = annualized_volatility.where(
        np.isfinite(annualized_volatility) & annualized_volatility.gt(0)
    )

    components: list[pd.Series] = []
    for horizon in normalized_horizons:
        grouped_price = valid_price.groupby(instrument, sort=False)
        base = grouped_price.shift(horizon)
        count = grouped_price.transform(
            lambda values, window=horizon + 1: values.rolling(
                window, min_periods=window
            ).count()
        )
        period_return = (valid_price / base - 1.0).where(count.eq(horizon + 1))
        horizon_volatility = annualized_volatility * math.sqrt(
            horizon / annualization_factor
        )
        component = period_return / horizon_volatility
        component = component.where(np.isfinite(component))
        if component_clip is not None:
            component = component.clip(-component_clip, component_clip)
        components.append(component)

    component_frame = pd.concat(components, axis=1)
    complete = component_frame.notna().all(axis=1)
    result = prices.loc[:, ["trading_date", "instrument"]].copy()
    result["annualized_volatility"] = annualized_volatility
    result["valid_horizons"] = component_frame.notna().sum(axis=1).astype("Int64")
    result["raw_factor"] = component_frame.mean(axis=1).where(complete)
    return result.loc[:, MULTI_HORIZON_TREND_DIAGNOSTIC_COLUMNS]


def compute_multi_horizon_trend_factor(
    continuous_prices: pd.DataFrame,
    universe: pd.DataFrame,
    *,
    horizons: Sequence[int] = (20, 60, 120, 252),
    volatility_lookback: int = 60,
    annualization_factor: int = 252,
    component_clip: float | None = 3.0,
    signal_scale: float = 1.0,
    price_field: str = "close",
) -> pd.DataFrame:
    """Return the standard factor table for robust multi-horizon trend."""

    normalized_horizons = _validate_horizons(horizons)
    diagnostics = calculate_multi_horizon_trend(
        continuous_prices,
        horizons=normalized_horizons,
        volatility_lookback=volatility_lookback,
        annualization_factor=annualization_factor,
        component_clip=component_clip,
        price_field=price_field,
    )
    horizon_label = "_".join(str(value) for value in normalized_horizons)
    result = make_factor_table(
        diagnostics.loc[:, ["trading_date", "instrument", "raw_factor"]],
        universe,
        factor_name=f"multi_trend_{horizon_label}d",
        signal_scale=signal_scale,
    )
    result.attrs.update(
        {
            "definition": "mean_horizon_return_divided_by_horizon_volatility",
            "horizons": normalized_horizons,
            "volatility_lookback": volatility_lookback,
            "annualization_factor": annualization_factor,
            "component_clip": component_clip,
            "price_field": price_field,
            "adjust_method": "prev_close_ratio",
            "direction": "long_positive_multi_horizon_trend",
            "raw_factor_normalization": "time_series_volatility",
        }
    )
    return result


def _validate_horizons(horizons: Sequence[int]) -> tuple[int, ...]:
    values = tuple(horizons)
    if not values or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1
        for value in values
    ):
        raise ValueError("horizons must contain positive integers")
    if len(set(values)) != len(values):
        raise ValueError("horizons cannot contain duplicates")
    return tuple(sorted(values))


def _validate_research_prices(continuous_prices: pd.DataFrame) -> None:
    if continuous_prices.attrs.get("usage") != "signal_research_only":
        raise ValueError("multi-horizon trend requires research continuous prices")
    if continuous_prices.attrs.get("cash_pnl_allowed") is not False:
        raise ValueError("multi-horizon trend input cannot be used for cash P&L")
    if (
        continuous_prices.attrs.get("adjust_type") != "pre"
        or continuous_prices.attrs.get("adjust_method") != "prev_close_ratio"
    ):
        raise ValueError(
            "multi-horizon trend requires pre-adjusted prev_close_ratio prices"
        )


def build(inputs: dict) -> pd.DataFrame:
    return compute_multi_horizon_trend_factor(
        inputs["continuous_prices"], inputs["universe"]
    )
