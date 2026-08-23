from __future__ import annotations

import pandas as pd
import pytest

from china_cta.validation import reconcile_close_based_mtm


def _single_contract_result(direction: int) -> dict[str, object]:
    dates = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"])
    quantity_column = "LONG_quantity" if direction > 0 else "SHORT_quantity"
    position_pnl = [0.0, direction * 20.0, direction * 10.0]
    transaction_cost = [1.0, 0.0, 1.1]
    daily_pnl = [
        position_pnl[index] - transaction_cost[index] for index in range(3)
    ]
    return {
        "metadata": {
            "formal_config": {
                "frequency": "1d",
                "matching_type": "current_bar",
                "futures_settlement_price_type": "close",
                "slippage_value": 0,
            }
        },
        "future_account": pd.DataFrame(
            {
                "position_pnl": position_pnl,
                "trading_pnl": [0.0, 0.0, 0.0],
                "daily_pnl": daily_pnl,
                "transaction_cost": transaction_cost,
                "total_value": [999.0, 999.0 + sum(daily_pnl[:2]), 999.0 + sum(daily_pnl)],
                "margin": [100.0, 102.0, 0.0],
            },
            index=dates,
        ),
        "future_positions": pd.DataFrame(
            {
                "order_book_id": ["RB2005", "RB2005"],
                "contract_multiplier": [10.0, 10.0],
                "last_price": [100.0, 102.0],
                quantity_column: [1.0, 1.0],
            },
            index=dates[:2],
        ),
        "trades": pd.DataFrame(
            {
                "trading_datetime": [
                    pd.Timestamp("2020-01-02 15:00"),
                    pd.Timestamp("2020-01-06 15:00"),
                ],
                "order_book_id": ["RB2005", "RB2005"],
                "last_price": [100.0, 103.0],
                "commission": [1.0, 1.1],
                "transaction_cost": [1.0, 1.1],
            }
        ),
    }


@pytest.mark.parametrize("direction", [1, -1])
def test_close_based_mtm_reconciles_long_and_short(direction: int) -> None:
    result = reconcile_close_based_mtm(_single_contract_result(direction))
    contract = result["contract_daily"]
    daily = result["daily"]

    assert contract["manual_gross_pnl_component"].tolist() == [
        0.0,
        direction * 20.0,
        direction * 10.0,
    ]
    assert daily["manual_position_pnl"].tolist() == [
        0.0,
        direction * 20.0,
        direction * 10.0,
    ]
    assert daily["reconciliation_difference"].eq(0).all()


def test_close_based_mtm_reconciles_contract_roll_without_overlap() -> None:
    dates = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"])
    formal_result = {
        "metadata": {
            "formal_config": {
                "frequency": "1d",
                "matching_type": "current_bar",
                "futures_settlement_price_type": "close",
                "slippage_value": 0,
            }
        },
        "future_account": pd.DataFrame(
            {
                "position_pnl": [0.0, 10.0, -10.0],
                "trading_pnl": [0.0, 0.0, 0.0],
                "daily_pnl": [-1.0, 8.0, -11.0],
                "transaction_cost": [1.0, 2.0, 1.0],
                "total_value": [999.0, 1007.0, 996.0],
                "margin": [100.0, 100.0, 0.0],
            },
            index=dates,
        ),
        "future_positions": pd.DataFrame(
            {
                "order_book_id": ["RB2005", "RB2010", "RB2010"],
                "contract_multiplier": [10.0, 5.0, 5.0],
                "last_price": [100.0, 200.0, 198.0],
                "LONG_quantity": [1.0, 1.0, 0.0],
            },
            index=[dates[0], dates[1], dates[2]],
        ),
        "trades": pd.DataFrame(
            {
                "trading_datetime": pd.to_datetime(
                    [
                        "2020-01-02 15:00",
                        "2020-01-03 15:00",
                        "2020-01-03 15:00",
                        "2020-01-06 15:00",
                    ]
                ),
                "order_book_id": ["RB2005", "RB2005", "RB2010", "RB2010"],
                "last_price": [100.0, 101.0, 200.0, 198.0],
                "commission": [1.0, 1.0, 1.0, 1.0],
                "transaction_cost": [1.0, 1.0, 1.0, 1.0],
            }
        ),
    }

    result = reconcile_close_based_mtm(formal_result)
    daily = result["daily"]

    assert daily["manual_position_pnl"].tolist() == [0.0, 10.0, -10.0]
    assert daily["reconciliation_difference"].eq(0).all()
    roll_date = result["contract_daily"].loc[
        lambda frame: frame["trading_date"].eq(dates[1])
    ]
    assert roll_date.set_index("order_book_id")["position_at_close"].to_dict() == {
        "RB2005": 0.0,
        "RB2010": 1.0,
    }


def test_reconciliation_rejects_non_golden_accounting_config() -> None:
    formal_result = _single_contract_result(1)
    formal_result["metadata"]["formal_config"]["slippage_value"] = 0.001

    with pytest.raises(ValueError, match="Golden close-based MTM"):
        reconcile_close_based_mtm(formal_result)
