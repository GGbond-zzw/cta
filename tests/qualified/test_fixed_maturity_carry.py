from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from china_cta.factors.qualified.fixed_maturity_carry import (
    calculate_curve_carry,
    compute_curve_carry_factor,
)


def curve_snapshot(*, missing_second: bool = False) -> pd.DataFrame:
    date = pd.Timestamp("2024-01-02")
    slope = -0.10
    rows = []
    for index, days in enumerate((60, 120, 180, 240, 300), start=1):
        rows.append(
            {
                "trading_date": date,
                "underlying_symbol": "RB",
                "order_book_id": f"RB{index}",
                "maturity_date": date + pd.Timedelta(days=days),
                "days_to_maturity": days,
                "price": (
                    np.nan
                    if missing_second and index == 2
                    else 100.0 * math.exp(slope * days / 365.0)
                ),
                "price_field": "close",
            }
        )
    return pd.DataFrame(rows)


def test_curve_carry_uses_linear_fixed_prices_and_annualized_log_spread() -> None:
    snapshot = curve_snapshot()
    result = calculate_curve_carry(snapshot)
    near = (snapshot.loc[0, "price"] + snapshot.loc[1, "price"]) / 2
    far = snapshot.loc[2, "price"]
    assert result.loc[0, "near_price"] == pytest.approx(near)
    assert result.loc[0, "far_price"] == pytest.approx(far)
    assert result.loc[0, "near_lower_weight"] == pytest.approx(0.5)
    assert result.loc[0, "far_status"] == "exact"
    assert result.loc[0, "raw_factor"] == pytest.approx(np.log(near / far) * 365 / 90)


def test_curve_carry_does_not_skip_selected_missing_contract() -> None:
    result = calculate_curve_carry(
        curve_snapshot(missing_second=True),
        min_days_to_maturity=30,
    )
    assert result.loc[0, "near_upper_contract"] == "RB2"
    assert result.loc[0, "near_status"] == "invalid_price"
    assert pd.isna(result.loc[0, "raw_factor"])


def test_fixed_carry_does_not_require_four_contracts_or_depend_on_extra_contracts():
    snapshot = curve_snapshot()
    sparse = snapshot.iloc[[0, 3]].copy()
    result = calculate_curve_carry(sparse, max_gap_days=180)
    assert result.loc[0, "near_lower_weight"] == pytest.approx(5 / 6)
    assert result.loc[0, "far_lower_weight"] == pytest.approx(1 / 3)
    assert np.isfinite(result.loc[0, "raw_factor"])
    base = calculate_curve_carry(snapshot.iloc[:3])
    snapshot.loc[3:, "price"] = 1e9
    assert calculate_curve_carry(snapshot).loc[0, "raw_factor"] == base.loc[0, "raw_factor"]


def test_fixed_carry_no_extrapolation_and_gap_limit():
    snapshot = curve_snapshot()
    result = calculate_curve_carry(snapshot.iloc[[0, 3]])
    assert result.loc[0, "near_status"] == "gap_too_large"
    assert pd.isna(result.loc[0, "raw_factor"])
    result = calculate_curve_carry(snapshot.iloc[:2])
    assert result.loc[0, "far_status"] == "unbracketed"
    assert pd.isna(result.loc[0, "raw_factor"])


def test_fixed_carry_factor_schema_metadata_and_direction():
    snapshot = curve_snapshot().iloc[[1, 2]].copy()
    universe = pd.DataFrame(
        {
            "trading_date": [snapshot.iloc[0]["trading_date"]],
            "instrument": ["RB"],
            "eligible": [True],
        }
    )
    result = compute_curve_carry_factor(snapshot, universe, near_days=120)
    assert result.loc[0, "factor_name"] == "fixed_maturity_carry_120_180d"
    assert result.loc[0, "raw_factor"] == pytest.approx(0.1)
    assert result.loc[0, "signal"] == pytest.approx(0.5)
    assert result.attrs["interpolation"] == "linear_price"
    snapshot["price"] = 1 / snapshot["price"]
    assert calculate_curve_carry(snapshot, near_days=120).loc[0, "raw_factor"] == pytest.approx(-0.1)


@pytest.mark.parametrize(
    "parameters",
    [
        {"near_days": 180},
        {"near_days": 30},
        {"max_gap_days": 0},
        {"near_days": True},
        {"far_days": 180.5},
    ],
)
def test_fixed_carry_rejects_invalid_parameters(parameters):
    with pytest.raises(ValueError):
        calculate_curve_carry(curve_snapshot(), **parameters)


def test_fixed_carry_rejects_inconsistent_dates_and_preserves_empty_schema():
    snapshot = curve_snapshot()
    assert list(calculate_curve_carry(snapshot.iloc[:0]).columns) == list(
        calculate_curve_carry(snapshot).columns
    )
    snapshot.loc[0, "days_to_maturity"] = 61
    with pytest.raises(ValueError, match="calendar days"):
        calculate_curve_carry(snapshot)


@pytest.mark.parametrize("invalid", [0, -1, np.inf])
def test_fixed_carry_invalid_bracket_prices(invalid):
    snapshot = curve_snapshot()
    snapshot.loc[1, "price"] = invalid
    assert pd.isna(calculate_curve_carry(snapshot).loc[0, "raw_factor"])


def test_fixed_carry_buffer_duplicate_tenor_and_future_independence():
    snapshot = curve_snapshot()
    assert (
        calculate_curve_carry(snapshot, min_days_to_maturity=60).loc[0, "near_status"]
        == "unbracketed"
    )
    duplicate = snapshot.iloc[[0]].copy()
    duplicate["order_book_id"] = "RB_DUPLICATE"
    assert (
        calculate_curve_carry(pd.concat([snapshot, duplicate])).loc[0, "near_status"]
        == "duplicate_tenor"
    )
    future = snapshot.copy()
    future["trading_date"] += pd.Timedelta(days=1)
    future["days_to_maturity"] -= 1
    future["price"] *= 100
    combined = calculate_curve_carry(pd.concat([snapshot, future]))
    assert combined.loc[0, "raw_factor"] == calculate_curve_carry(snapshot).loc[0, "raw_factor"]
