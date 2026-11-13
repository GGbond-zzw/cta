from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from china_cta.factors.unqualified.basis_momentum import (
    calculate_basis_momentum,
    compute_basis_momentum_factor,
)
from china_cta.factors.schema import FACTOR_COLUMNS


def snapshots(
    first_prices: list[float],
    second_prices: list[float],
    *,
    roll_on_last_day: bool = False,
) -> pd.DataFrame:
    dates = pd.date_range("2020-01-02", periods=len(first_prices), freq="B")
    rows: list[dict[str, object]] = []
    for index, (date, first_price, second_price) in enumerate(
        zip(dates, first_prices, second_prices, strict=True)
    ):
        contracts = [
            ("RB2005", "2020-05-15", first_price),
            ("RB2010", "2020-10-15", second_price),
            ("RB2101", "2021-01-15", 90.0 + index),
        ]
        if roll_on_last_day and index == len(dates) - 1:
            # RB2005 remains in the curve so yesterday's holding can be priced,
            # but falls inside the selection buffer for the next holding.
            contracts[0] = ("RB2005", date + pd.Timedelta(days=1), first_price)
        for contract, maturity, price in contracts:
            maturity_date = pd.Timestamp(maturity)
            rows.append(
                {
                    "trading_date": date,
                    "underlying_symbol": "RB",
                    "order_book_id": contract,
                    "maturity_date": maturity_date,
                    "days_to_maturity": (maturity_date - date).days,
                    "price": price,
                    "price_field": "close",
                }
            )
    return pd.DataFrame(rows)


def universe(dates: pd.Series | pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(
        {"trading_date": dates, "instrument": "RB", "eligible": True}
    )


def test_basis_momentum_matches_manual_compounded_return_difference() -> None:
    curves = snapshots(
        [100.0, 110.0, 121.0],
        [200.0, 202.0, 204.02],
    )

    diagnostics = calculate_basis_momentum(
        curves, lookback=2, min_days_to_maturity=0
    )
    factor = compute_basis_momentum_factor(
        curves,
        universe(diagnostics["trading_date"]),
        lookback=2,
        min_days_to_maturity=0,
        signal_scale=0.20,
    )

    expected = (1.10 * 1.10 - 1.0) - (1.01 * 1.01 - 1.0)
    assert diagnostics.loc[2, "first_momentum"] == pytest.approx(0.21)
    assert diagnostics.loc[2, "second_momentum"] == pytest.approx(0.0201)
    assert diagnostics.loc[2, "raw_factor"] == pytest.approx(expected)
    assert tuple(factor.columns) == FACTOR_COLUMNS
    assert factor.loc[2, "raw_factor"] == pytest.approx(expected)
    assert factor.loc[2, "signal"] == pytest.approx(expected / 0.20)
    assert factor.attrs["earliest_trade_at"] == "next_trading_session"


def test_roll_prices_previous_selection_on_same_contract() -> None:
    curves = snapshots(
        [100.0, 101.0, 102.0],
        [200.0, 202.0, 204.0],
        roll_on_last_day=True,
    )

    result = calculate_basis_momentum(curves, lookback=1, min_days_to_maturity=5)

    last = result.iloc[-1]
    assert last["first_contract"] == "RB2010"
    assert last["first_holding_contract"] == "RB2005"
    assert last["first_return"] == pytest.approx(102.0 / 101.0 - 1.0)


def test_missing_selected_price_is_not_replaced_by_farther_contract() -> None:
    curves = snapshots([100.0, np.nan], [200.0, 202.0])

    result = calculate_basis_momentum(curves, lookback=1, min_days_to_maturity=0)

    assert pd.isna(result.loc[1, "first_return"])
    assert pd.isna(result.loc[1, "raw_factor"])


def test_incomplete_window_and_future_prices_do_not_leak() -> None:
    curves = snapshots(
        [100.0, 101.0, 102.0, 1_000.0],
        [200.0, 201.0, 202.0, 2_000.0],
    )
    original = calculate_basis_momentum(curves, lookback=2, min_days_to_maturity=0)
    changed = curves.copy()
    changed.loc[changed["trading_date"].eq(changed["trading_date"].max()), "price"] = 1.0
    recomputed = calculate_basis_momentum(
        changed, lookback=2, min_days_to_maturity=0
    )

    assert original["raw_factor"].iloc[:2].isna().all()
    assert original.loc[2, "raw_factor"] == recomputed.loc[2, "raw_factor"]


def test_basis_momentum_rejects_settlement_prices_and_duplicate_rows() -> None:
    curves = snapshots([100.0, 101.0], [200.0, 202.0])
    settlement_curves = curves.copy()
    settlement_curves["price_field"] = "settlement"
    with pytest.raises(ValueError, match="close"):
        calculate_basis_momentum(settlement_curves)

    duplicated = pd.concat([curves, curves.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate"):
        calculate_basis_momentum(duplicated)
