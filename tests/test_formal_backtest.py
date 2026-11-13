from __future__ import annotations

import pickle
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

# This module exercises the legacy RQAlpha Plus adapter. Its native modules are
# blocked on some Windows hosts by the code-integrity policy, so skip instead of
# failing collection there; the native result layer is covered by
# tests/test_native_account.py and does not need rqalpha_plus.
pytest.importorskip(
    "rqalpha_plus",
    reason="legacy RQAlpha Plus adapter is unavailable on this host",
)

from china_cta.formal_backtest import adapter
from china_cta.formal_backtest.adapter import (
    ORDER_COLUMNS,
    TARGET_EXECUTION_COLUMNS,
    FormalBacktestConfig,
    run_formal_backtest,
)
from china_cta.formal_backtest.results import load_formal_result


DATES = pd.date_range("2020-06-01", periods=5, freq="B")


def target_frame(rows: list[tuple[object, str, int]]) -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            {
                "trading_date": date,
                "order_book_id": contract,
                "target_quantity": quantity,
                "source_tag": "portfolio_v1",
            }
            for date, contract, quantity in rows
        ]
    )
    frame.attrs["trading_date_role"] = (
        "target_effective_date_earliest_execution_trading_date"
    )
    return frame


def formal_config(tmp_path: Path, **changes) -> FormalBacktestConfig:
    bundle = tmp_path / "bundle"
    bundle.mkdir(exist_ok=True)
    config = FormalBacktestConfig(
        start_date="2020-06-01",
        end_date="2020-06-05",
        initial_capital=1_000_000,
        data_bundle_path=bundle,
        output_root=tmp_path / "results",
    )
    return replace(config, **changes)


def install_fake_rqalpha(
    monkeypatch: pytest.MonkeyPatch,
    *,
    rejected: bool = False,
) -> dict[str, object]:
    observed: dict[str, object] = {
        "orders": [],
        "universes": [],
        "current_date": None,
        "configs": [],
    }

    def fake_instruments(contract_ids):
        return [
            SimpleNamespace(order_book_id=contract, type="FUTURE")
            for contract in contract_ids
        ]

    def fake_update_universe(contract_ids):
        observed["universes"].append(list(contract_ids))

    def fake_order_to(contract, quantity):
        call = (
            pd.Timestamp(observed["current_date"]).normalize(),
            contract,
            int(quantity),
        )
        observed["orders"].append(call)
        order_id = len(observed["orders"])
        return [
            SimpleNamespace(
                order_id=order_id,
                quantity=abs(int(quantity)),
                filled_quantity=0 if rejected else abs(int(quantity)),
                unfilled_quantity=abs(int(quantity)) if rejected else 0,
                status="REJECTED" if rejected else "FILLED",
                message="cash validation failed" if rejected else "",
                side="BUY" if quantity >= 0 else "SELL",
                position_effect="OPEN",
                avg_price=0.0 if rejected else 100.0,
                transaction_cost=0.0,
            )
        ]

    def fake_run_func(*, config, init, handle_bar):
        observed["configs"].append(config)
        context = SimpleNamespace()
        init(context)
        dates = pd.date_range(
            config["base"]["start_date"], config["base"]["end_date"], freq="B"
        )
        for date in dates:
            observed["current_date"] = date
            context.now = date + pd.Timedelta(hours=15)
            handle_bar(context, {})
        portfolio = pd.DataFrame(
            {
                "cash": [1_000_000.0] * len(dates),
                "total_value": [1_000_000.0] * len(dates),
                "unit_net_value": [1.0] * len(dates),
            },
            index=dates,
        )
        account = pd.DataFrame(
            {"transaction_cost": [0.0] * len(dates)}, index=dates
        )
        return {
            "sys_analyser": {
                "summary": {"unit_net_value": 1.0},
                "portfolio": portfolio,
                "future_account": account,
                "future_positions": pd.DataFrame(),
                "trades": pd.DataFrame(),
            }
        }

    monkeypatch.setattr(adapter, "instruments", fake_instruments)
    monkeypatch.setattr(adapter, "update_universe", fake_update_universe)
    monkeypatch.setattr(adapter, "order_to", fake_order_to)
    monkeypatch.setattr(adapter, "run_func", fake_run_func)
    return observed


def test_target_schedule_uses_effective_date_without_another_lag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    observed = install_fake_rqalpha(monkeypatch)
    targets = target_frame(
        [
            (DATES[0], "AG2012", 1),
            (DATES[2], "AG2012", 0),
            (DATES[3], "AG2012", -1),
            (DATES[4], "AG2012", 0),
        ]
    )

    result = run_formal_backtest(targets, formal_config(tmp_path))

    assert observed["orders"] == [
        (DATES[0], "AG2012", 1),
        (DATES[2], "AG2012", 0),
        (DATES[3], "AG2012", -1),
        (DATES[4], "AG2012", 0),
    ]
    assert observed["universes"] == [["AG2012"]]
    assert result["metadata"]["additional_adapter_lag_sessions"] == 0
    assert result["metadata"]["callback"] == "handle_bar"
    assert result["metadata"]["target_trading_date_definition"] == (
        "target_effective_date_earliest_execution_trading_date"
    )
    assert result["target_executions"].columns.tolist() == list(
        TARGET_EXECUTION_COLUMNS
    )


def test_complete_snapshot_closes_contract_omitted_after_roll(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    observed = install_fake_rqalpha(monkeypatch)
    targets = target_frame(
        [
            (DATES[0], "AG2012", 1),
            (DATES[1], "AU2012", 1),
        ]
    )

    result = run_formal_backtest(targets, formal_config(tmp_path))

    assert observed["orders"] == [
        (DATES[0], "AG2012", 1),
        (DATES[1], "AG2012", 0),
        (DATES[1], "AU2012", 1),
    ]
    implicit = result["target_executions"].loc[
        result["target_executions"]["implicit_zero"]
    ].iloc[0]
    assert implicit["order_book_id"] == "AG2012"
    assert implicit["requested_target_quantity"] == 0


def test_empty_complete_snapshot_flattens_all_previously_targeted_contracts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    observed = install_fake_rqalpha(monkeypatch)
    targets = target_frame(
        [
            (DATES[0], "RB2010", 1),
            (DATES[0], "CU2007", 1),
        ]
    )
    targets.attrs["rebalance_dates"] = [
        DATES[0].date().isoformat(),
        DATES[1].date().isoformat(),
    ]

    result = run_formal_backtest(targets, formal_config(tmp_path))

    assert observed["orders"] == [
        (DATES[0], "CU2007", 1),
        (DATES[0], "RB2010", 1),
        (DATES[1], "CU2007", 0),
        (DATES[1], "RB2010", 0),
    ]
    flattened = result["target_executions"].loc[
        result["target_executions"]["target_trading_date"].eq(DATES[1])
    ]
    assert set(flattened["order_book_id"]) == {"RB2010", "CU2007"}
    assert flattened["requested_target_quantity"].eq(0).all()
    assert flattened["implicit_zero"].all()
    assert result["metadata"]["empty_complete_snapshot_dates"] == [
        DATES[1].date().isoformat()
    ]


def test_date_without_rebalance_snapshot_does_not_flatten_positions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    observed = install_fake_rqalpha(monkeypatch)
    targets = target_frame(
        [
            (DATES[0], "RB2010", 1),
            (DATES[0], "CU2007", 1),
        ]
    )

    result = run_formal_backtest(
        targets,
        formal_config(tmp_path),
        rebalance_dates=[DATES[0]],
    )

    assert observed["orders"] == [
        (DATES[0], "CU2007", 1),
        (DATES[0], "RB2010", 1),
    ]
    assert set(result["target_executions"]["target_trading_date"]) == {DATES[0]}
    assert result["metadata"]["empty_complete_snapshot_dates"] == []


def test_formal_config_is_explicit_and_historical_parameters_are_required(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    observed = install_fake_rqalpha(monkeypatch)
    config = formal_config(
        tmp_path,
        matching_type="vwap",
        volume_percent=0.1,
        slippage_model="TickSizeSlippage",
        slippage_value=1,
    )
    result = run_formal_backtest(
        target_frame([(DATES[0], "AG2012", 1)]), config
    )

    rqalpha_config = observed["configs"][0]
    assert rqalpha_config["base"]["accounts"] == {"future": 1_000_000.0}
    assert rqalpha_config["base"]["futures_time_series_trading_parameters"] is True
    simulation = rqalpha_config["mod"]["sys_simulation"]
    assert simulation["matching_type"] == "vwap"
    assert simulation["volume_limit"] is True
    assert simulation["volume_percent"] == pytest.approx(0.1)
    assert simulation["price_limit"] is True
    assert simulation["inactive_limit"] is True
    assert simulation["slippage_model"] == "TickSizeSlippage"
    assert simulation["slippage"] == pytest.approx(1)
    assert result["metadata"]["formal_config"]["matching_type"] == "vwap"

    baseline = run_formal_backtest(
        target_frame([(DATES[0], "AG2012", 1)]),
        replace(
            config,
            matching_type="current_bar",
            slippage_model="PriceRatioSlippage",
            slippage_value=0,
        ),
    )
    assert result["metadata"]["run_fingerprint"] != baseline["metadata"][
        "run_fingerprint"
    ]
    assert baseline["metadata"]["formal_config"]["matching_type"] == "current_bar"

    disabled = replace(config, futures_time_series_trading_parameters=False)
    with pytest.raises(ValueError, match="historical trading parameters"):
        run_formal_backtest(
            target_frame([(DATES[0], "AG2012", 1)]), disabled
        )


def test_reject_and_unfilled_order_remain_observable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install_fake_rqalpha(monkeypatch, rejected=True)

    result = run_formal_backtest(
        target_frame([(DATES[0], "AG2012", 1)]), formal_config(tmp_path)
    )

    assert result["orders"].columns.tolist() == list(ORDER_COLUMNS)
    order = result["orders"].iloc[0]
    assert order["status"] == "REJECTED"
    assert order["filled_quantity"] == 0
    assert order["unfilled_quantity"] == 1
    assert order["message"] == "cash validation failed"


def test_result_loader_uses_native_nav_account_positions_and_costs(
    tmp_path: Path,
) -> None:
    dates = pd.date_range("2020-06-01", periods=2, freq="B")
    native = {
        "sys_analyser": {
            "summary": {"unit_net_value": 1.01},
            "portfolio": pd.DataFrame(
                {"unit_net_value": [1.0, 1.01]}, index=dates
            ),
            "future_account": pd.DataFrame(
                {"transaction_cost": [0.0, 2.5]}, index=dates
            ),
            "future_positions": pd.DataFrame(
                {"order_book_id": ["AG2012"], "LONG_quantity": [1]},
                index=[dates[-1]],
            ),
            "trades": pd.DataFrame(
                {"order_book_id": ["AG2012"], "transaction_cost": [2.5]}
            ),
        }
    }

    result = load_formal_result(native, metadata={"matching_type": "current_bar"})
    native_path = tmp_path / "rqalpha_result.pkl"
    with native_path.open("wb") as result_file:
        pickle.dump(native["sys_analyser"], result_file)
    from_file = load_formal_result(native_path)

    assert result["portfolio"].loc[dates[-1], "unit_net_value"] == pytest.approx(
        1.01
    )
    assert result["future_positions"].iloc[0]["LONG_quantity"] == 1
    assert result["transaction_costs"].iloc[-1]["transaction_cost"] == pytest.approx(
        2.5
    )
    assert result["metadata"]["nav_recomputed_by_loader"] is False
    assert result["metadata"]["account_recomputed_by_loader"] is False
    pd.testing.assert_frame_equal(from_file["portfolio"], result["portfolio"])


def test_same_targets_and_config_are_reproducible(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install_fake_rqalpha(monkeypatch)
    targets = target_frame(
        [(DATES[0], "AG2012", 1), (DATES[2], "AG2012", 0)]
    )
    config = formal_config(tmp_path)

    first = run_formal_backtest(targets, config)
    second = run_formal_backtest(targets, config)

    assert first["metadata"]["run_fingerprint"] == second["metadata"][
        "run_fingerprint"
    ]
    assert first["metadata"]["target_fingerprint"] == second["metadata"][
        "target_fingerprint"
    ]
    pd.testing.assert_frame_equal(
        first["target_executions"], second["target_executions"]
    )
    pd.testing.assert_frame_equal(first["portfolio"], second["portfolio"])


@pytest.mark.parametrize(
    "bad_targets, message",
    [
        (
            pd.DataFrame(
                {
                    "trading_date": [DATES[0]],
                    "order_book_id": ["AG88"],
                    "target_quantity": [1],
                    "source_tag": ["portfolio_v1"],
                }
            ),
            "real futures contracts",
        ),
        (
            pd.DataFrame(
                {
                    "trading_date": [DATES[0]],
                    "order_book_id": ["AG2012"],
                    "target_quantity": [1.5],
                    "source_tag": ["portfolio_v1"],
                }
            ),
            "integers",
        ),
    ],
)
def test_target_contract_requires_real_contract_and_integer_quantity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    bad_targets: pd.DataFrame,
    message: str,
) -> None:
    install_fake_rqalpha(monkeypatch)
    with pytest.raises(ValueError, match=message):
        run_formal_backtest(bad_targets, formal_config(tmp_path))
