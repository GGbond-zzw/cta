"""3-month time-series momentum (unqualified)."""

from __future__ import annotations

import pandas as pd

from china_cta.factors.cta_common import standard_table
from china_cta.factors.cta_momentum_base import calculate_time_series_momentum


FACTOR_NAME = "tsmom_63"
SIGNAL_SCALE = 0.20


def build(inputs: dict) -> pd.DataFrame:
    raw = calculate_time_series_momentum(
        inputs["continuous_prices"], lookback=63, skip=0
    )
    return standard_table(
        raw,
        inputs["universe"],
        factor_name=FACTOR_NAME,
        signal_scale=SIGNAL_SCALE,
        family="A_time_series_momentum",
        definition="P_t_over_P_t_minus_63_minus_1",
        lookback_trading_periods=63,
        skip_trading_periods=0,
        price_field="close",
        adjust_method="prev_close_ratio",
        direction="IC+ prior; repository call: strong IC- reversal",
        raw_factor_normalization="none",
    )
