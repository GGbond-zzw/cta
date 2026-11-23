"""Mined candidate sleeves rebuilt natively, with their searchable windows.

The three sleeves come from a frozen expression-search export.  The formulas are the
frozen ones; only the operator windows are exposed as parameters so the project's
Bayesian optimiser can re-tune them on the local data.  `raw_factor` already carries the
fitted direction, matching the convention of the qualified sleeves (``signal`` is then
``raw_factor / signal_scale`` clipped to ``[-1, 1]``).

Baselines (the frozen export values):

* ``crowded_trend_reversal_60d``      mean 60 / corr 60, direction +1, scale 0.7073720289720415
* ``volume_oi_coflow_10d``            corr 10,         direction +1, scale 0.7148378264008488
* ``volume_burst_vol_reversal_60d``   mean 60 / corr 20 / delta 20 / mean 60, direction -1,
                                      scale 0.3029101622490162
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Final

import pandas as pd

from china_cta.factors.mined.expressions import (
    compute_features,
    evaluate,
    feature_node,
    to_long,
    unary,
)
from china_cta.factors.schema import make_factor_table

FEATURE_CACHE_KEY: Final[str] = "_mined_feature_cache"


def _features(
    prices: pd.DataFrame, product_flows: pd.DataFrame | None = None
) -> dict[str, pd.DataFrame]:
    """Compute (and memoise on the price frame) the causal feature panels.

    ``product_flows`` (optional) carries product-level volume and open-interest totals
    from the RQAlpha bundle.  The frozen export was mined on aggregated product flows
    ("品种量仓聚合"), so passing them keeps the local rebuild close to the export; the
    dominant-contract values are used where a total is unavailable.
    """

    cache_key = None if product_flows is None else f"{FEATURE_CACHE_KEY}_flows"
    if cache_key is not None:
        cache = prices.attrs.get(cache_key)
        if isinstance(cache, dict) and cache:
            return cache
    else:
        cache = prices.attrs.get(FEATURE_CACHE_KEY)
        if isinstance(cache, dict) and cache:
            return cache

    panel = prices.loc[
        :, ["trading_date", "underlying_symbol", "close", "high", "low", "volume", "open_interest"]
    ].copy()
    panel["trading_date"] = pd.to_datetime(panel["trading_date"])
    if product_flows is not None and not product_flows.empty:
        flows = product_flows.loc[:, ["trading_date", "product", "volume_total", "oi_total"]].copy()
        flows["trading_date"] = pd.to_datetime(flows["trading_date"])
        flows = flows.rename(columns={"product": "underlying_symbol"})
        panel = panel.merge(flows, on=["trading_date", "underlying_symbol"], how="left")
        panel["volume"] = panel["volume_total"].combine_first(panel["volume"])
        panel["open_interest"] = panel["oi_total"].combine_first(panel["open_interest"])
        panel = panel.drop(columns=["volume_total", "oi_total"])
    panel = panel.rename(columns={"underlying_symbol": "instrument"})
    features, _ = compute_features(panel)
    if cache_key is not None:
        prices.attrs[cache_key] = features
    else:
        prices.attrs[FEATURE_CACHE_KEY] = features
    return features


def compute_crowded_trend_reversal_factor(
    prices: pd.DataFrame,
    universe: pd.DataFrame,
    *,
    product_flows: pd.DataFrame | None = None,
    trend_window: int = 60,
    correlation_window: int = 60,
    direction: int = 1,
    signal_scale: float = 0.7073720289720415,
) -> pd.DataFrame:
    """Negative correlation of smoothed 60-day momentum with a crowded-trend proxy."""

    features = _features(prices, product_flows)
    expression = unary(
        "neg",
        {
            "op": "corr",
            "args": [
                unary("mean", feature_node("return_60"), int(trend_window)),
                {
                    "op": "mul",
                    "args": [feature_node("channel_position_20"), feature_node("volatility_20")],
                },
            ],
            "window": int(correlation_window),
        },
    )
    values = evaluate(expression, features) * float(direction)
    table = make_factor_table(
        to_long(values, factor_name="crowded_trend_reversal"),
        universe,
        factor_name="crowded_trend_reversal",
        signal_scale=signal_scale,
    )
    table.attrs.update(
        {
            "definition": (
                "-corr(trend_window)(mean(trend_window)(return_60), "
                "channel_position_20 * volatility_20)"
            ),
            "direction": "fade_crowded_high_volatility_trends",
            "trend_window": int(trend_window),
            "correlation_window": int(correlation_window),
            "price_field": "close",
            "adjust_method": "prev_close_ratio",
            "raw_factor_normalization": "none",
        }
    )
    return table




def compute_volume_burst_vol_reversal_factor(
    prices: pd.DataFrame,
    universe: pd.DataFrame,
    *,
    product_flows: pd.DataFrame | None = None,
    smoothing_window: int = 60,
    correlation_window: int = 20,
    delta_window: int = 20,
    volatility_window: int = 60,
    direction: int = -1,
    signal_scale: float = 0.3029101622490162,
) -> pd.DataFrame:
    """Negative smoothed correlation of volume-surprise acceleration with volatility expansion."""

    features = _features(prices, product_flows)
    expression = unary(
        "mean",
        {
            "op": "corr",
            "args": [
                unary("delta", feature_node("volume_surprise_20"), int(delta_window)),
                unary("mean", feature_node("volatility_ratio"), int(volatility_window)),
            ],
            "window": int(correlation_window),
        },
        int(smoothing_window),
    )
    values = evaluate(expression, features) * float(direction)
    table = make_factor_table(
        to_long(values, factor_name="volume_burst_vol_reversal"),
        universe,
        factor_name="volume_burst_vol_reversal",
        signal_scale=signal_scale,
    )
    table.attrs.update(
        {
            "definition": (
                "-mean(smoothing_window)(corr(correlation_window)("
                "delta(delta_window)(volume_surprise_20), "
                "mean(volatility_window)(volatility_ratio)))"
            ),
            "direction": "fade_volume_bursts_made_in_rising_volatility",
            "smoothing_window": int(smoothing_window),
            "correlation_window": int(correlation_window),
            "delta_window": int(delta_window),
            "volatility_window": int(volatility_window),
            "price_field": "close",
            "adjust_method": "prev_close_ratio",
            "raw_factor_normalization": "none",
        }
    )
    return table


@dataclass(frozen=True)
class MinedSleeve:
    name: str
    label: str
    compute: Callable[..., pd.DataFrame]
    baseline: dict[str, Any]
    window_parameters: tuple[str, ...] = field(default_factory=tuple)
    note: str = ""


MINED_SLEEVES: Final[dict[str, MinedSleeve]] = {
    "crowded_trend_reversal_60d": MinedSleeve(
        name="crowded_trend_reversal_60d",
        label="原8号",
        compute=compute_crowded_trend_reversal_factor,
        baseline={
            "trend_window": 60,
            "correlation_window": 60,
            "direction": 1,
            "signal_scale": 0.7073720289720415,
        },
        window_parameters=("trend_window", "correlation_window"),
        note="fades trends that are pushed by high channel position and high volatility",
    ),
    "volume_burst_vol_reversal_60d": MinedSleeve(
        name="volume_burst_vol_reversal_60d",
        label="本轮1号",
        compute=compute_volume_burst_vol_reversal_factor,
        baseline={
            "smoothing_window": 60,
            "correlation_window": 20,
            "delta_window": 20,
            "volatility_window": 60,
            "direction": -1,
            "signal_scale": 0.3029101622490162,
        },
        window_parameters=("smoothing_window", "correlation_window", "delta_window", "volatility_window"),
        note="fades volume bursts that arrive while volatility is expanding",
    ),
}


def build_mined_factor(name: str, params: dict[str, Any], inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build one mined sleeve from a parameter dictionary (used by the tuner)."""

    if name not in MINED_SLEEVES:
        raise ValueError(f"unknown mined sleeve: {name}")
    sleeve = MINED_SLEEVES[name]
    settings = dict(sleeve.baseline)
    settings.update({key: value for key, value in params.items() if value is not None})
    flows = inputs.get("product_flows")
    return sleeve.compute(
        inputs["continuous_prices"], inputs["universe"], product_flows=flows, **settings
    )
