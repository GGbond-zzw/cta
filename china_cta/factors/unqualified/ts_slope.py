"""Per-calendar-day term-structure slope (unqualified)."""

from __future__ import annotations

import pandas as pd

from china_cta.factors.cta_common import standard_table
from china_cta.factors.cta_curve import calculate_curve_metrics


FACTOR_NAME = "ts_slope"
SIGNAL_SCALE = 0.0005


def calculate_ts_slope(
    contract_snapshots: pd.DataFrame, *, min_days_to_maturity: int = 30
) -> pd.DataFrame:
    metrics = calculate_curve_metrics(
        contract_snapshots, min_days_to_maturity=min_days_to_maturity
    )
    return metrics.loc[:, ["trading_date", "instrument", "ts_slope"]].rename(
        columns={"ts_slope": "raw_factor"}
    )


def build(inputs: dict) -> pd.DataFrame:
    raw = calculate_ts_slope(inputs["contract_snapshots"])
    return standard_table(
        raw,
        inputs["universe"],
        factor_name=FACTOR_NAME,
        signal_scale=SIGNAL_SCALE,
        family="D_term_structure",
        definition="log_far_over_near_divided_by_gap_days",
        contract_selection="first_two_real_contracts_by_maturity_after_buffer",
        min_days_to_maturity=30,
        price_field="close",
        direction="IC- prior; repository call: IC+ and best tradable factor",
        raw_factor_normalization="per_calendar_day",
    )
