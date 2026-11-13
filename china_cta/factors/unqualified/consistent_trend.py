"""Slow direction-voting trend factor (unqualified)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

import pandas as pd

from china_cta.factors.cta_trend_vote import calculate_consistent_trend
from china_cta.factors.schema import make_factor_table


CONSISTENT_TREND_DIAGNOSTIC_COLUMNS: Final[tuple[str, ...]] = (
    "trading_date",
    "instrument",
    "trend_consensus",
    "smoothed_consensus",
    "annualized_volatility",
    "risk_multiplier",
    "raw_factor",
)


def compute_consistent_trend_factor(
    continuous_prices: pd.DataFrame,
    universe: pd.DataFrame,
    *,
    horizons: Sequence[int] = (63, 126, 252),
    smoothing_span: int = 10,
    deadband: float = 0.05,
    rebalance_every: int = 5,
    volatility_halflife: int = 20,
    target_annualized_volatility: float = 0.15,
    signal_scale: float = 0.50,
    price_field: str = "close",
) -> pd.DataFrame:
    """Return the standard factor table for slow direction-voting trend."""

    horizons = tuple(sorted(horizons))
    diagnostics = calculate_consistent_trend(
        continuous_prices,
        horizons=horizons,
        smoothing_span=smoothing_span,
        deadband=deadband,
        rebalance_every=rebalance_every,
        volatility_halflife=volatility_halflife,
        target_annualized_volatility=target_annualized_volatility,
        price_field=price_field,
    )
    horizon_label = "_".join(str(value) for value in horizons)
    result = make_factor_table(
        diagnostics.loc[:, ["trading_date", "instrument", "raw_factor"]],
        universe,
        factor_name=f"consistent_trend_{horizon_label}d_{rebalance_every}r",
        signal_scale=signal_scale,
    )
    result.attrs.update(
        {
            "definition": "mean_horizon_sign_then_ewm_and_downside_only_vol_scaling",
            "horizons": horizons,
            "smoothing_span": smoothing_span,
            "deadband": deadband,
            "rebalance_every": rebalance_every,
            "volatility_halflife": volatility_halflife,
            "target_annualized_volatility": target_annualized_volatility,
            "price_field": price_field,
            "adjust_method": "prev_close_ratio",
            "direction": "long_persistent_uptrend_short_persistent_downtrend",
            "raw_factor_normalization": "bounded_vote_times_downside_only_vol_scaler",
        }
    )
    return result


def build(inputs: dict) -> pd.DataFrame:
    return compute_consistent_trend_factor(
        inputs["continuous_prices"], inputs["universe"]
    )
