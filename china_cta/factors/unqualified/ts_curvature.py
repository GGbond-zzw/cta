"""Three-point term-structure curvature (unqualified)."""

from __future__ import annotations

import pandas as pd

from china_cta.factors.cta_common import standard_table
from china_cta.factors.cta_curve import calculate_curve_metrics


FACTOR_NAME = "ts_curvature"
SIGNAL_SCALE = 0.05


def calculate_ts_curvature(
    contract_snapshots: pd.DataFrame, *, min_days_to_maturity: int = 30
) -> pd.DataFrame:
    metrics = calculate_curve_metrics(
        contract_snapshots, min_days_to_maturity=min_days_to_maturity
    )
    return metrics.loc[:, ["trading_date", "instrument", "ts_curvature"]].rename(
        columns={"ts_curvature": "raw_factor"}
    )


def build(inputs: dict) -> pd.DataFrame:
    raw = calculate_ts_curvature(inputs["contract_snapshots"])
    return standard_table(
        raw,
        inputs["universe"],
        factor_name=FACTOR_NAME,
        signal_scale=SIGNAL_SCALE,
        family="D_term_structure",
        definition="third_minus_2_second_plus_near_divided_by_second",
        contract_selection="first_three_real_contracts_by_maturity_after_buffer",
        min_days_to_maturity=30,
        price_field="close",
        direction="exploratory; repository call: not tested",
        raw_factor_normalization="dimensionless_price_curvature",
    )
