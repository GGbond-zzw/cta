"""Annualized near/second-contract carry (qualified)."""

from __future__ import annotations

import pandas as pd

from china_cta.factors.cta_common import standard_table
from china_cta.factors.cta_curve import calculate_curve_metrics


FACTOR_NAME = "carry_ann"
SIGNAL_SCALE = 0.20


def calculate_carry_ann(
    contract_snapshots: pd.DataFrame, *, min_days_to_maturity: int = 30
) -> pd.DataFrame:
    metrics = calculate_curve_metrics(
        contract_snapshots, min_days_to_maturity=min_days_to_maturity
    )
    return metrics.loc[:, ["trading_date", "instrument", "carry_ann"]].rename(
        columns={"carry_ann": "raw_factor"}
    )


def build(inputs: dict) -> pd.DataFrame:
    raw = calculate_carry_ann(inputs["contract_snapshots"])
    return standard_table(
        raw,
        inputs["universe"],
        factor_name=FACTOR_NAME,
        signal_scale=SIGNAL_SCALE,
        family="C_carry_and_roll",
        definition="near_over_far_minus_1_times_365_over_gap_days",
        contract_selection="first_two_real_contracts_by_maturity_after_buffer",
        min_days_to_maturity=30,
        price_field="close",
        direction="IC+ prior; repository call: IC- in China",
        raw_factor_normalization="annualized",
    )
