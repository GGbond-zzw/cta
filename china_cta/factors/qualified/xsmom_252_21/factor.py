"""Cross-sectional 12-1 momentum (qualified)."""

from __future__ import annotations

from typing import Final

import pandas as pd

from china_cta.factors.cta_common import cross_sectional_table
from china_cta.factors.cta_momentum_base import calculate_time_series_momentum


FACTOR_NAME = "xsmom_252_21"
SIGNAL_SCALE = 1.0

PARAMETERS: Final[dict] = {
    "lookback": 246,
    "skip": 53,
    "signal_scale": 0.6397851035292096,
}


def _finalize(table: pd.DataFrame, name: str) -> pd.DataFrame:
    """Stamp the canonical factor name so every package emits its own key."""

    out = table.copy()
    out["factor_name"] = name
    out.attrs["factor_name"] = name
    return out


def _settings(params: dict | None) -> dict:
    merged = dict(PARAMETERS)
    merged.update({key: value for key, value in (params or {}).items() if value is not None})
    return merged

def _rescale(table: pd.DataFrame, scale: float) -> pd.DataFrame:
    out = table.copy()
    out["signal"] = (pd.to_numeric(out["raw_factor"]) / scale).clip(-1.0, 1.0)
    return out


def build(inputs: dict, params: dict | None = None) -> pd.DataFrame:
    settings = _settings(params)
    raw = calculate_time_series_momentum(
        inputs["continuous_prices"],
        lookback=int(settings["lookback"]),
        skip=int(settings["skip"]),
    )
    table = cross_sectional_table(
        raw,
        inputs["universe"],
        factor_name="xsmom_252_21",
        family="B_cross_sectional_momentum",
        definition="per_date_rank_of_tsmom_in_eligible_universe",
        lookback_trading_periods=int(settings["lookback"]),
        skip_trading_periods=int(settings["skip"]),
        price_field="close",
        adjust_method="prev_close_ratio",
        raw_factor_normalization="cross_sectional_rank_minus1_plus1",
    )
    return _finalize(_rescale(table, float(settings["signal_scale"])), "xsmom_252_21")
