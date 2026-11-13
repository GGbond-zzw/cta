"""Aggregate open-interest growth factor (unqualified)."""

from __future__ import annotations

from typing import Final

import pandas as pd

from china_cta.factors.cta_oi import calculate_aggregate_oi_growth
from china_cta.factors.schema import make_factor_table


AGGREGATE_OI_DIAGNOSTIC_COLUMNS: Final[tuple[str, ...]] = (
    "trading_date",
    "instrument",
    "contracts_count",
    "total_open_interest",
    "raw_factor",
)


def compute_aggregate_oi_growth_factor(
    contract_snapshots: pd.DataFrame,
    universe: pd.DataFrame,
    *,
    lookback: int = 20,
    minimum_contracts: int = 2,
    signal_scale: float = 0.20,
) -> pd.DataFrame:
    """Return a standard factor table for aggregate OI growth."""

    diagnostics = calculate_aggregate_oi_growth(
        contract_snapshots,
        lookback=lookback,
        minimum_contracts=minimum_contracts,
    )
    result = make_factor_table(
        diagnostics.loc[:, ["trading_date", "instrument", "raw_factor"]],
        universe,
        factor_name=f"aggregate_oi_growth_{lookback}d",
        signal_scale=signal_scale,
    )
    result.attrs.update(
        {
            "definition": "total_curve_open_interest_t_over_t_minus_lookback_minus_1",
            "lookback_trading_periods": lookback,
            "minimum_contracts": minimum_contracts,
            "direction": "long_open_interest_growth_short_contraction",
            "roll_treatment": "sum_all_active_real_contracts",
            "raw_factor_normalization": "none",
        }
    )
    return result


def build(inputs: dict) -> pd.DataFrame:
    return compute_aggregate_oi_growth_factor(
        inputs["contract_snapshots"], inputs["universe"]
    )
