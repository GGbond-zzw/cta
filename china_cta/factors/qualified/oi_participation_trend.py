"""Use aggregate open interest as a participation filter for slow trend."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

import numpy as np
import pandas as pd

from china_cta.factors.cta_oi import calculate_aggregate_oi_growth
from china_cta.factors.cta_trend_vote import calculate_consistent_trend
from china_cta.factors.schema import make_factor_table


OI_PARTICIPATION_TREND_DIAGNOSTIC_COLUMNS: Final[tuple[str, ...]] = (
    "trading_date",
    "instrument",
    "trend_score",
    "total_open_interest",
    "open_interest_growth",
    "open_interest_growth_zscore",
    "participation_weight",
    "raw_factor",
)


def calculate_oi_participation_trend(
    continuous_prices: pd.DataFrame,
    contract_snapshots: pd.DataFrame,
    *,
    trend_horizons: Sequence[int] = (63, 126, 252),
    trend_smoothing_span: int = 10,
    trend_deadband: float = 0.05,
    trend_volatility_halflife: int = 20,
    trend_target_annualized_volatility: float = 0.15,
    oi_growth_lookback: int = 60,
    oi_smoothing_span: int = 10,
    oi_normalization_lookback: int = 252,
    minimum_oi_observations: int = 126,
    minimum_contracts: int = 2,
    rebalance_every: int = 5,
    price_field: str = "close",
) -> pd.DataFrame:
    """Scale a slow trend by the strength of aggregate OI participation.

    OI is not treated as a standalone directional signal. Its smoothed growth
    is standardized against the instrument's own history and mapped to a
    bounded 0-1 participation weight. Low relative OI growth suppresses trend;
    high relative OI growth allows it through.
    """

    if (
        isinstance(oi_smoothing_span, bool)
        or not isinstance(oi_smoothing_span, int)
        or oi_smoothing_span < 1
    ):
        raise ValueError("oi_smoothing_span must be a positive integer")
    if (
        isinstance(oi_normalization_lookback, bool)
        or not isinstance(oi_normalization_lookback, int)
        or oi_normalization_lookback < 2
    ):
        raise ValueError("oi_normalization_lookback must be an integer >= 2")
    if (
        isinstance(minimum_oi_observations, bool)
        or not isinstance(minimum_oi_observations, int)
        or not 2 <= minimum_oi_observations <= oi_normalization_lookback
    ):
        raise ValueError(
            "minimum_oi_observations must be between 2 and normalization lookback"
        )
    if (
        isinstance(rebalance_every, bool)
        or not isinstance(rebalance_every, int)
        or rebalance_every < 1
    ):
        raise ValueError("rebalance_every must be a positive integer")

    trend = calculate_consistent_trend(
        continuous_prices,
        horizons=trend_horizons,
        smoothing_span=trend_smoothing_span,
        deadband=trend_deadband,
        rebalance_every=1,
        volatility_halflife=trend_volatility_halflife,
        target_annualized_volatility=trend_target_annualized_volatility,
        price_field=price_field,
    ).rename(columns={"raw_factor": "trend_score"})
    oi = calculate_aggregate_oi_growth(
        contract_snapshots,
        lookback=oi_growth_lookback,
        minimum_contracts=minimum_contracts,
    ).rename(columns={"raw_factor": "open_interest_growth"})
    frame = trend.loc[:, ["trading_date", "instrument", "trend_score"]].merge(
        oi.loc[
            :,
            [
                "trading_date",
                "instrument",
                "total_open_interest",
                "open_interest_growth",
            ],
        ],
        on=["trading_date", "instrument"],
        how="left",
        validate="one_to_one",
    )
    frame = frame.sort_values(["instrument", "trading_date"]).reset_index(drop=True)
    instrument = frame["instrument"]
    smoothed_growth = frame["open_interest_growth"].groupby(
        instrument, sort=False
    ).transform(
        lambda values: values.ewm(
            span=oi_smoothing_span, adjust=False, min_periods=1
        ).mean()
    )
    # EWM otherwise carries the previous observation across a missing OI date.
    # Missing curve data is not evidence of unchanged participation, so keep the
    # date untradeable instead of manufacturing a stale confirmation signal.
    smoothed_growth = smoothed_growth.where(frame["open_interest_growth"].notna())
    rolling_mean = smoothed_growth.groupby(instrument, sort=False).transform(
        lambda values: values.rolling(
            oi_normalization_lookback,
            min_periods=minimum_oi_observations,
        ).mean()
    )
    rolling_std = smoothed_growth.groupby(instrument, sort=False).transform(
        lambda values: values.rolling(
            oi_normalization_lookback,
            min_periods=minimum_oi_observations,
        ).std(ddof=1)
    )
    zscore = ((smoothed_growth - rolling_mean) / rolling_std).where(
        rolling_std.gt(0)
    )
    zscore = zscore.clip(-3.0, 3.0)
    participation_weight = 0.5 * (1.0 + np.tanh(zscore))
    candidate = frame["trend_score"] * participation_weight
    observation_number = frame.groupby("instrument", sort=False).cumcount()
    update = observation_number.mod(rebalance_every).eq(0)
    tradable = candidate.where(update).groupby(instrument, sort=False).ffill()
    tradable = tradable.where(candidate.notna())

    result = frame.loc[
        :,
        [
            "trading_date",
            "instrument",
            "trend_score",
            "total_open_interest",
            "open_interest_growth",
        ],
    ].copy()
    result["open_interest_growth_zscore"] = zscore
    result["participation_weight"] = participation_weight
    result["raw_factor"] = tradable
    return result.loc[:, OI_PARTICIPATION_TREND_DIAGNOSTIC_COLUMNS]


def compute_oi_participation_trend_factor(
    continuous_prices: pd.DataFrame,
    contract_snapshots: pd.DataFrame,
    universe: pd.DataFrame,
    *,
    trend_horizons: Sequence[int] = (63, 126, 252),
    trend_smoothing_span: int = 10,
    trend_deadband: float = 0.05,
    trend_volatility_halflife: int = 20,
    trend_target_annualized_volatility: float = 0.15,
    oi_growth_lookback: int = 60,
    oi_smoothing_span: int = 10,
    oi_normalization_lookback: int = 252,
    minimum_oi_observations: int = 126,
    minimum_contracts: int = 2,
    rebalance_every: int = 5,
    signal_scale: float = 0.50,
    price_field: str = "close",
) -> pd.DataFrame:
    """Return the standard factor table for OI-conditioned trend."""

    diagnostics = calculate_oi_participation_trend(
        continuous_prices,
        contract_snapshots,
        trend_horizons=trend_horizons,
        trend_smoothing_span=trend_smoothing_span,
        trend_deadband=trend_deadband,
        trend_volatility_halflife=trend_volatility_halflife,
        trend_target_annualized_volatility=trend_target_annualized_volatility,
        oi_growth_lookback=oi_growth_lookback,
        oi_smoothing_span=oi_smoothing_span,
        oi_normalization_lookback=oi_normalization_lookback,
        minimum_oi_observations=minimum_oi_observations,
        minimum_contracts=minimum_contracts,
        rebalance_every=rebalance_every,
        price_field=price_field,
    )
    result = make_factor_table(
        diagnostics.loc[:, ["trading_date", "instrument", "raw_factor"]],
        universe,
        factor_name=f"oi_participation_trend_{oi_growth_lookback}d",
        signal_scale=signal_scale,
    )
    result.attrs.update(
        {
            "definition": "consistent_trend_times_bounded_oi_participation_weight",
            "trend_horizons": tuple(sorted(trend_horizons)),
            "trend_smoothing_span": trend_smoothing_span,
            "trend_deadband": trend_deadband,
            "trend_volatility_halflife": trend_volatility_halflife,
            "trend_target_annualized_volatility": (
                trend_target_annualized_volatility
            ),
            "oi_growth_lookback": oi_growth_lookback,
            "oi_smoothing_span": oi_smoothing_span,
            "oi_normalization_lookback": oi_normalization_lookback,
            "minimum_oi_observations": minimum_oi_observations,
            "minimum_contracts": minimum_contracts,
            "rebalance_every": rebalance_every,
            "direction": "trend_direction_scaled_by_relative_oi_participation",
            "raw_factor_normalization": "bounded_vote_vol_scaler_and_oi_weight",
        }
    )
    return result


def build(inputs: dict) -> pd.DataFrame:
    return compute_oi_participation_trend_factor(
        inputs["continuous_prices"],
        inputs["contract_snapshots"],
        inputs["universe"],
    )
