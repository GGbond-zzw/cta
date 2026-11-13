"""3-month cross-sectional momentum (unqualified)."""

from __future__ import annotations

import pandas as pd

from china_cta.factors.cta_common import cross_sectional_table
from china_cta.factors.cta_momentum_base import calculate_time_series_momentum


FACTOR_NAME = "xsmom_63"
SIGNAL_SCALE = 1.0


def build(inputs: dict) -> pd.DataFrame:
    raw = calculate_time_series_momentum(
        inputs["continuous_prices"], lookback=63, skip=0
    )
    return cross_sectional_table(
        raw,
        inputs["universe"],
        factor_name=FACTOR_NAME,
        family="B_cross_sectional_momentum",
        definition="per_date_rank_of_tsmom_63_in_eligible_universe",
        lookback_trading_periods=63,
        skip_trading_periods=0,
        price_field="close",
        adjust_method="prev_close_ratio",
        direction="IC+ prior; repository call: strong IC- reversal",
        raw_factor_normalization="cross_sectional_rank_minus1_plus1",
    )
