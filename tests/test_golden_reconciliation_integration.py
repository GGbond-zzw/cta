from __future__ import annotations

import importlib.metadata
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from china_cta.data.contracts import (
    get_contract_snapshot,
    get_research_universe,
    get_signal_continuous_price,
)
from china_cta.data.rqdata_adapter import RQDataAdapter, RQDataConfig
from china_cta.factors.carry import compute_carry_factor
from china_cta.factors.trend import compute_trend_factor
from china_cta.formal_backtest import FormalBacktestConfig, run_formal_backtest
from china_cta.portfolio import (
    PortfolioConfig,
    construct_target_positions,
    load_product_classification,
    prepare_portfolio_market_data,
)
from china_cta.runtime_paths import get_rqalpha_bundle_path
from china_cta.validation import reconcile_close_based_mtm


pytestmark = [
    pytest.mark.integration,
    pytest.mark.formal,
    pytest.mark.skipif(
        os.getenv("RUN_RQALPHA_INTEGRATION") != "1",
        reason="set RUN_RQALPHA_INTEGRATION=1 for Phase 7 Golden checks",
    ),
]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_PATH = get_rqalpha_bundle_path()
GOLDEN_SPEC_PATH = PROJECT_ROOT / "config" / "golden_backtest_v1.json"
DATE_ROLE = "target_effective_date_earliest_execution_trading_date"


def _targets(rows: list[tuple[str, str, int]], source_tag: str) -> pd.DataFrame:
    frame = pd.DataFrame(
        rows, columns=["trading_date", "order_book_id", "target_quantity"]
    )
    frame["trading_date"] = pd.to_datetime(frame["trading_date"])
    frame["source_tag"] = source_tag
    frame.attrs["trading_date_role"] = DATE_ROLE
    return frame


def _config(
    output_root: Path,
    *,
    start_date: str,
    end_date: str,
    strategy_name: str,
    volume_percent: float = 0.25,
) -> FormalBacktestConfig:
    return FormalBacktestConfig(
        start_date=start_date,
        end_date=end_date,
        initial_capital=1_000_000,
        data_bundle_path=BUNDLE_PATH,
        output_root=output_root,
        frequency="1d",
        matching_type="current_bar",
        volume_limit=True,
        volume_percent=volume_percent,
        price_limit=True,
        inactive_limit=True,
        slippage_model="PriceRatioSlippage",
        slippage_value=0,
        futures_time_series_trading_parameters=True,
        futures_settlement_price_type="close",
        strategy_name=strategy_name,
    )


@pytest.fixture(scope="module")
def result_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not BUNDLE_PATH.is_dir():
        pytest.skip(f"local futures smoke bundle not found: {BUNDLE_PATH}")
    return tmp_path_factory.mktemp("phase7_golden")


@pytest.fixture(scope="module")
def fixed_long_result(result_root: Path) -> dict[str, object]:
    return run_formal_backtest(
        _targets(
            [("2016-06-01", "AG1612", 1), ("2016-06-08", "AG1612", 0)],
            "golden_a_long",
        ),
        _config(
            result_root / "fixed_long",
            start_date="2016-06-01",
            end_date="2016-06-10",
            strategy_name="phase7_golden_backtest_v1",
        ),
    )


def test_golden_a_fixed_long_matches_frozen_summary_and_manual_mtm(
    fixed_long_result: dict[str, object], result_root: Path
) -> None:
    spec = json.loads(GOLDEN_SPEC_PATH.read_text(encoding="utf-8"))
    expected = spec["expected_summary"]
    result = fixed_long_result
    reconciliation = reconcile_close_based_mtm(result)
    daily = reconciliation["daily"]
    contract = reconciliation["contract_daily"]

    versions = {
        package: importlib.metadata.version(package)
        for package in ("rqalpha", "rqalpha-plus", "rqdatac")
    }
    assert versions == spec["required_versions"]
    assert result["metadata"]["target_fingerprint"] == spec["target_fingerprint"]
    assert result["summary"]["total_value"] == pytest.approx(
        expected["final_total_value"], abs=1e-7
    )
    assert result["summary"]["unit_net_value"] == pytest.approx(
        expected["final_unit_net_value"], abs=1e-12
    )
    assert len(result["orders"]) == expected["order_count"]
    assert result["orders"]["status"].eq("FILLED").sum() == expected[
        "filled_order_count"
    ]
    assert len(result["trades"]) == expected["trade_count"]
    assert result["trades"]["transaction_cost"].sum() == pytest.approx(
        expected["total_trade_transaction_cost"], abs=1e-12
    )
    assert result["future_account"].iloc[-1]["margin"] == pytest.approx(
        expected["final_margin"]
    )
    assert daily["reconciliation_difference"].abs().max() == pytest.approx(
        expected["maximum_absolute_daily_reconciliation_difference"]
    )

    contract_by_date = contract.set_index("trading_date")
    daily_by_date = daily.set_index("trading_date")
    for expected_day in expected["daily"]:
        date = pd.Timestamp(expected_day["trading_date"])
        contract_day = contract_by_date.loc[date]
        account_day = daily_by_date.loc[date]
        assert contract_day["accounting_price"] == pytest.approx(
            expected_day["accounting_price"]
        )
        assert contract_day["position_at_close"] == pytest.approx(
            expected_day["position_at_close"]
        )
        assert contract_day["manual_gross_pnl_component"] == pytest.approx(
            expected_day["manual_gross_pnl_component"]
        )
        assert account_day["transaction_cost"] == pytest.approx(
            expected_day["rqalpha_transaction_cost"]
        )
        assert account_day["daily_pnl"] == pytest.approx(
            expected_day["rqalpha_daily_pnl"]
        )
        assert account_day["total_value"] == pytest.approx(
            expected_day["rqalpha_total_value"]
        )

    repeated = run_formal_backtest(
        _targets(
            [("2016-06-01", "AG1612", 1), ("2016-06-08", "AG1612", 0)],
            "golden_a_long",
        ),
        _config(
            result_root / "fixed_long",
            start_date="2016-06-01",
            end_date="2016-06-10",
            strategy_name="phase7_golden_backtest_v1",
        ),
    )
    assert repeated["metadata"]["run_fingerprint"] == result["metadata"][
        "run_fingerprint"
    ]
    pd.testing.assert_frame_equal(result["portfolio"], repeated["portfolio"])
    pd.testing.assert_frame_equal(result["future_account"], repeated["future_account"])


def test_golden_b_fixed_short_has_opposite_daily_mtm(result_root: Path) -> None:
    result = run_formal_backtest(
        _targets(
            [("2016-06-01", "AG1612", -1), ("2016-06-08", "AG1612", 0)],
            "golden_b_short",
        ),
        _config(
            result_root / "fixed_short",
            start_date="2016-06-01",
            end_date="2016-06-10",
            strategy_name="golden_b_short",
        ),
    )
    reconciliation = reconcile_close_based_mtm(result)
    contract = reconciliation["contract_daily"]

    rising_days = contract["price_change"].gt(0) & contract[
        "previous_position"
    ].lt(0)
    assert rising_days.any()
    assert contract.loc[rising_days, "manual_gross_pnl_component"].lt(0).all()
    assert reconciliation["daily"]["reconciliation_difference"].eq(0).all()
    assert result["trades"]["side"].tolist() == ["SELL", "BUY"]


@pytest.fixture(scope="module")
def reversal_result(result_root: Path) -> dict[str, object]:
    return run_formal_backtest(
        _targets(
            [
                ("2016-06-01", "AG1612", 1),
                ("2016-06-03", "AG1612", 0),
                ("2016-06-06", "AG1612", -1),
                ("2016-06-08", "AG1612", 0),
            ],
            "golden_c_reversal",
        ),
        _config(
            result_root / "reversal",
            start_date="2016-06-01",
            end_date="2016-06-10",
            strategy_name="golden_c_reversal",
        ),
    )


def test_golden_c_reversal_is_native_order_to_behaviour(
    reversal_result: dict[str, object],
) -> None:
    result = reversal_result

    assert result["trades"]["side"].tolist() == ["BUY", "SELL", "SELL", "BUY"]
    assert result["trades"]["position_effect"].tolist() == [
        "OPEN",
        "CLOSE",
        "OPEN",
        "CLOSE",
    ]
    assert result["trades"]["transaction_cost"].gt(0).all()
    assert result["orders"]["status"].eq("FILLED").all()
    assert result["orders"]["unfilled_quantity"].eq(0).all()
    assert result["metadata"]["order_bridge"] == (
        "order_to(actual_contract, target_quantity)"
    )


def test_golden_e_commission_and_close_today_limitation_are_explicit(
    reversal_result: dict[str, object],
) -> None:
    result = reversal_result

    assert result["trades"]["transaction_cost"].sum() == pytest.approx(
        12.02025, abs=1e-12
    )
    assert result["trades"]["commission"].equals(
        result["trades"]["transaction_cost"]
    )
    assert "CLOSE_TODAY" not in set(result["trades"]["position_effect"])
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    assert "显式日内 `CLOSE_TODAY` 留作书面限制" in readme
    assert "没有切换到 `buy_open/sell_close` 状态机" in readme


def test_golden_d_roll_closes_old_and_opens_new_without_overnight_overlap(
    result_root: Path,
) -> None:
    result = run_formal_backtest(
        _targets(
            [
                ("2016-06-01", "AG1606", 1),
                ("2016-06-03", "AG1612", 1),
                ("2016-06-08", "AG1612", 0),
            ],
            "golden_d_roll",
        ),
        _config(
            result_root / "roll",
            start_date="2016-06-01",
            end_date="2016-06-10",
            strategy_name="golden_d_roll",
        ),
    )
    roll_orders = result["orders"].loc[
        result["orders"]["target_trading_date"].eq(pd.Timestamp("2016-06-03"))
    ]
    assert roll_orders.set_index("order_book_id")[
        "requested_target_quantity"
    ].to_dict() == {"AG1606": 0, "AG1612": 1}
    assert roll_orders.set_index("order_book_id")["position_effect"].to_dict() == {
        "AG1606": "CLOSE",
        "AG1612": "OPEN",
    }
    assert roll_orders["status"].eq("FILLED").all()
    roll_positions = result["future_positions"].loc[
        result["future_positions"].index == pd.Timestamp("2016-06-03")
    ]
    assert set(roll_positions["order_book_id"]) == {"AG1612"}
    assert roll_positions.iloc[0]["LONG_quantity"] == 1
    assert result["trades"]["transaction_cost"].gt(0).all()
    reconciliation = reconcile_close_based_mtm(result)
    assert reconciliation["daily"]["reconciliation_difference"].eq(0).all()


@pytest.mark.parametrize(
    ("case_name", "start", "end", "contract", "target_date", "volume_percent", "status"),
    [
        (
            "price_limit",
            "2016-07-04",
            "2016-07-05",
            "AG1612",
            "2016-07-04",
            0.25,
            "REJECTED",
        ),
        (
            "inactive_limit",
            "2016-02-01",
            "2016-02-02",
            "AG1603",
            "2016-02-01",
            0.25,
            "CANCELLED",
        ),
        (
            "volume_limit",
            "2016-06-01",
            "2016-06-02",
            "AG1612",
            "2016-06-01",
            1e-12,
            "CANCELLED",
        ),
    ],
)
def test_golden_f_real_execution_limits_are_observable(
    result_root: Path,
    case_name: str,
    start: str,
    end: str,
    contract: str,
    target_date: str,
    volume_percent: float,
    status: str,
) -> None:
    result = run_formal_backtest(
        _targets([(target_date, contract, 1)], f"golden_f_{case_name}"),
        _config(
            result_root / case_name,
            start_date=start,
            end_date=end,
            strategy_name=f"golden_f_{case_name}",
            volume_percent=volume_percent,
        ),
    )
    order = result["orders"].iloc[0]
    assert order["status"] == status
    assert order["filled_quantity"] == 0
    assert order["unfilled_quantity"] == 1
    assert order["message"]
    assert result["trades"].empty
    assert result["future_positions"].empty


def test_trend_and_carry_share_factor_portfolio_formal_pipeline(
    tmp_path: Path,
) -> None:
    if os.getenv("RUN_RQDATA_INTEGRATION") != "1":
        pytest.skip(
            "set RUN_RQDATA_INTEGRATION=1 for the licensed end-to-end check"
        )
    local = RQDataConfig.from_environment()
    adapter = RQDataAdapter(
        RQDataConfig(
            uri=local.uri,
            market=local.market,
            cache_dir=tmp_path / "rqdata_cache",
        )
    )
    adapter.connect(lazy=False)
    signal_date = pd.Timestamp("2020-06-12")
    products = ("RB", "CU", "IF")
    commodities = ("RB", "CU")
    universe = get_research_universe(adapter, signal_date)
    prices = get_signal_continuous_price(
        adapter,
        products,
        "2020-01-15",
        signal_date,
        fields="close",
        adjust_type="pre",
        adjust_method="prev_close_ratio",
    )
    trend = compute_trend_factor(prices, universe, lookback=60)
    curve = pd.concat(
        [
            get_contract_snapshot(
                adapter, product, signal_date, price_field="settlement"
            )
            for product in commodities
        ],
        ignore_index=True,
    )
    carry = compute_carry_factor(curve, universe)
    signals = pd.concat([trend, carry], ignore_index=True)
    signals.attrs.update(
        {
            "information_date": "trading_date",
            "signal_available_at": "after_close_of_trading_date",
            "earliest_trade_at": "next_trading_session",
            "signal_is_position": False,
        }
    )
    portfolio_config = PortfolioConfig(
        initial_capital=10_000_000.0,
        portfolio_vol_target=0.10,
        volatility_method="rolling_close_to_close_simple_return",
        volatility_lookback=20,
        minimum_volatility_observations=20,
        annualization_factor=252,
        volatility_floor=0.05,
        strategy_weights={"trend_60d": 0.5, "carry_near_main": 0.5},
        instrument_cap=10.0,
        sector_gross_cap=10.0,
        chain_gross_cap=10.0,
        risk_estimator="diagonal",
        max_margin_fraction=0.50,
        target_lag_sessions=1,
        trade_contract_rule=0,
        trade_contract_rank=1,
        trade_price_field="settlement",
        rounding_rule="toward_zero",
        source_tag="phase7_end_to_end",
    )
    market = prepare_portfolio_market_data(adapter, signals, portfolio_config)
    portfolio_result = construct_target_positions(
        signals,
        prices,
        universe,
        market,
        load_product_classification(),
        portfolio_config,
    )
    targets = portfolio_result["targets"]

    assert set(signals["factor_name"]) == {"trend_60d", "carry_near_main"}
    assert set(portfolio_result["contributions"]["factor_name"]) == {
        "trend_60d",
        "carry_near_main",
    }
    assert targets.attrs["trading_date_role"] == DATE_ROLE
    assert targets["target_quantity"].ne(0).any()

    formal_result = run_formal_backtest(
        targets,
        FormalBacktestConfig(
            start_date="2020-06-15",
            end_date="2020-06-16",
            initial_capital=portfolio_config.initial_capital,
            data_bundle_path=BUNDLE_PATH,
            output_root=tmp_path / "formal_result",
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
            strategy_name="phase7_trend_carry_end_to_end",
        ),
        rebalance_dates=portfolio_result["rebalance_dates"],
    )
    assert set(formal_result["target_executions"]["order_book_id"]) == set(
        targets["order_book_id"]
    )
    assert formal_result["metadata"]["target_fingerprint"]
    assert not formal_result["orders"].empty
    assert not formal_result["trades"].empty
    assert not formal_result["portfolio"].empty
