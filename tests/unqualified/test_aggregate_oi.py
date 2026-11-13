from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from china_cta.factors.unqualified.aggregate_oi import calculate_aggregate_oi_growth


def oi_snapshots() -> pd.DataFrame:
    rows = []
    for date_index, date in enumerate(pd.date_range("2024-01-02", periods=3, freq="B")):
        for contract_index, contract in enumerate(("RB2405", "RB2410"), start=1):
            rows.append(
                {
                    "trading_date": date,
                    "underlying_symbol": "RB",
                    "order_book_id": contract,
                    "open_interest": (100 * contract_index) * (1 + 0.1 * date_index),
                }
            )
    return pd.DataFrame(rows)


def test_aggregate_oi_growth_uses_all_contracts_and_compounds_window() -> None:
    result = calculate_aggregate_oi_growth(oi_snapshots(), lookback=2)
    assert result.loc[0, "total_open_interest"] == pytest.approx(300.0)
    assert result.loc[2, "total_open_interest"] == pytest.approx(360.0)
    assert result.loc[2, "raw_factor"] == pytest.approx(0.20)


def test_aggregate_oi_missing_contract_value_invalidates_total_and_window() -> None:
    snapshots = oi_snapshots()
    snapshots.loc[2, "open_interest"] = np.nan
    result = calculate_aggregate_oi_growth(snapshots, lookback=1)
    assert pd.isna(result.loc[1, "total_open_interest"])
    assert pd.isna(result.loc[1, "raw_factor"])
    assert pd.isna(result.loc[2, "raw_factor"])
