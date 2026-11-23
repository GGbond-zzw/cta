"""Cross-sectional 12-1 momentum (qualified)."""

from __future__ import annotations

import pandas as pd

from china_cta.factors.cta_common import cross_sectional_table
from china_cta.factors.cta_momentum_base import calculate_time_series_momentum


FACTOR_NAME = "xsmom_252_21"
SIGNAL_SCALE = 1.0


def build(inputs: dict) -> pd.DataFrame:
    raw = calculate_time_series_momentum(
        inputs["continuous_prices"], lookback=252, skip=21
    )
    return cross_sectional_table(
        raw,
        inputs["universe"],
        factor_name=FACTOR_NAME,
        family="B_cross_sectional_momentum",
        definition="per_date_rank_of_tsmom_252_21_in_eligible_universe",
        lookback_trading_periods=252,
        skip_trading_periods=21,
        price_field="close",
        adjust_method="prev_close_ratio",
        direction="IC+ prior; repository call: weak IC+",
        raw_factor_normalization="cross_sectional_rank_minus1_plus1",
    )
