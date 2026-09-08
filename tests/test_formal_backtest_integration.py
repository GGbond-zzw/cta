from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from china_cta.formal_backtest import FormalBacktestConfig, run_formal_backtest
from china_cta.runtime_paths import get_rqalpha_bundle_path


pytestmark = [
    pytest.mark.integration,
    pytest.mark.formal,
    pytest.mark.skipif(
        os.getenv("RUN_RQALPHA_INTEGRATION") != "1",
        reason="set RUN_RQALPHA_INTEGRATION=1 to run RQAlpha Plus checks",
    ),
]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_PATH = get_rqalpha_bundle_path()
CONTRACT = "AG1612"


def target_schedule() -> pd.DataFrame:
    targets = pd.DataFrame(
        {
            "trading_date": pd.to_datetime(
                ["2016-06-01", "2016-06-03", "2016-06-06", "2016-06-08"]
            ),
            "order_book_id": [CONTRACT] * 4,
            "target_quantity": [1, 0, -1, 0],
            "source_tag": ["phase6_integration"] * 4,
        }
    )
    targets.attrs["trading_date_role"] = (
        "target_effective_date_earliest_execution_trading_date"
    )
    return targets


def test_real_rqalpha_long_flat_short_flat_and_reproducibility(tmp_path) -> None:
    if not BUNDLE_PATH.is_dir():
        pytest.skip(f"local futures smoke bundle not found: {BUNDLE_PATH}")
    config = FormalBacktestConfig(
        start_date="2016-06-01",
        end_date="2016-06-10",
        initial_capital=1_000_000,
        data_bundle_path=BUNDLE_PATH,
        output_root=tmp_path / "formal_results",
        frequency="1d",
        matching_type="current_bar",
        volume_limit=True,
        volume_percent=0.25,
        price_limit=True,
        inactive_limit=True,
        slippage_model="PriceRatioSlippage",
        slippage_value=0,
        futures_time_series_trading_parameters=True,
        futures_settlement_price_type="close",
    )

    first = run_formal_backtest(target_schedule(), config)
    second = run_formal_backtest(target_schedule(), config)

    assert not first["portfolio"].empty
    assert not first["future_account"].empty
    assert not first["future_positions"].empty
    assert not first["trades"].empty
    assert not first["orders"].empty
    assert "transaction_cost" in first["transaction_costs"].columns
    assert first["future_positions"]["LONG_quantity"].max() == 1
    assert first["future_positions"]["SHORT_quantity"].max() == 1
    assert first["future_account"].iloc[-1]["margin"] == pytest.approx(0)
    assert first["trades"].iloc[-1]["position_effect"] == "CLOSE"
    assert set(first["orders"]["status"]) == {"FILLED"}
    assert first["orders"]["unfilled_quantity"].eq(0).all()
    assert first["target_executions"]["target_trading_date"].tolist() == list(
        target_schedule()["trading_date"]
    )
    assert first["metadata"]["additional_adapter_lag_sessions"] == 0
    assert first["metadata"]["formal_config"][
        "futures_time_series_trading_parameters"
    ] is True

    artifacts = first["metadata"]["artifacts"]
    assert Path(artifacts["native_result"]).is_file()
    assert Path(artifacts["native_report"]).is_dir()
    assert Path(artifacts["metadata"]).is_file()
    assert Path(artifacts["orders"]).is_file()

    assert first["metadata"]["run_fingerprint"] == second["metadata"][
        "run_fingerprint"
    ]
    pd.testing.assert_frame_equal(first["portfolio"], second["portfolio"])
    stable_trade_columns = [
        column
        for column in (
            "datetime",
            "trading_datetime",
            "order_book_id",
            "side",
            "position_effect",
            "commission",
            "last_quantity",
            "last_price",
            "transaction_cost",
        )
        if column in first["trades"]
    ]
    pd.testing.assert_frame_equal(
        first["trades"].loc[:, stable_trade_columns].reset_index(drop=True),
        second["trades"].loc[:, stable_trade_columns].reset_index(drop=True),
    )
