from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from china_cta.research.fast_backtest import (
    DETAIL_COLUMNS,
    METRIC_COLUMNS,
    run_fast_research_backtest,
    run_parameter_surface,
    save_research_run,
)


def research_prices(
    dates,
    values_by_instrument,
) -> pd.DataFrame:
    rows = [
        {
            "trading_date": date,
            "underlying_symbol": instrument,
            "close": value,
        }
        for instrument, values in values_by_instrument.items()
        for date, value in zip(pd.to_datetime(dates), values, strict=True)
    ]
    frame = pd.DataFrame(rows)
    frame.attrs.update(
        {
            "usage": "signal_research_only",
            "cash_pnl_allowed": False,
            "adjust_type": "pre",
            "adjust_method": "prev_close_ratio",
            "rule": 0,
            "rank": 1,
        }
    )
    return frame


def factors(
    dates,
    signals_by_instrument,
    *,
    factor_name="trend_60d",
) -> pd.DataFrame:
    rows = [
        {
            "trading_date": date,
            "instrument": instrument,
            "factor_name": factor_name,
            "raw_factor": signal,
            "signal": signal,
        }
        for instrument, signals in signals_by_instrument.items()
        for date, signal in zip(pd.to_datetime(dates), signals, strict=True)
    ]
    frame = pd.DataFrame(rows)
    frame.attrs.update(
        {
            "information_date": "trading_date",
            "signal_available_at": "after_close_of_trading_date",
            "earliest_trade_at": "next_trading_session",
            "signal_is_position": False,
            "signal_scale": 0.20,
        }
    )
    return frame


def universe(dates, instruments, *, ineligible=()) -> pd.DataFrame:
    ineligible_set = set(ineligible)
    return pd.DataFrame(
        [
            {
                "trading_date": date,
                "instrument": instrument,
                "eligible": instrument not in ineligible_set,
                "reason": (
                    "eligible"
                    if instrument not in ineligible_set
                    else "not_yet_listed"
                ),
            }
            for date in pd.to_datetime(dates)
            for instrument in instruments
        ]
    )


def test_signal_lag_forward_return_turnover_and_cost_are_manual() -> None:
    dates = pd.date_range("2020-01-02", periods=5, freq="B")
    price_data = research_prices(
        dates, {"RB": [100.0, 120.0, 126.0, 151.2, 166.32]}
    )
    factor_data = factors(dates[:3], {"RB": [0.5, -0.5, 1.0]})

    result = run_fast_research_backtest(
        factor_data,
        price_data,
        universe(dates[:3], ("RB",)),
        execution_lag=1,
        cost_rate=0.01,
    )
    detail = result["detail"]

    assert tuple(detail.columns) == DETAIL_COLUMNS
    assert detail.loc[0, "return_start"] == dates[1]
    assert detail.loc[0, "return_end"] == dates[2]
    assert detail.loc[0, "realization_date"] == dates[2]
    assert detail.loc[0, "research_forward_return"] == pytest.approx(0.05)
    assert detail.loc[0, "research_forward_return"] != pytest.approx(0.20)
    assert detail["gross_signal_return"].tolist() == pytest.approx(
        [0.025, -0.10, 0.10]
    )
    assert detail["turnover_proxy"].tolist() == pytest.approx([0.5, 1.0, 1.5])
    assert detail["rough_cost"].tolist() == pytest.approx([0.005, 0.01, 0.015])
    assert detail["net_signal_return"].tolist() == pytest.approx(
        [0.02, -0.11, 0.085]
    )
    assert detail.attrs["research_only"] is True
    assert detail.attrs["cash_pnl_allowed"] is False


def test_execution_lag_is_required_to_be_positive() -> None:
    dates = pd.date_range("2020-01-02", periods=3, freq="B")
    with pytest.raises(ValueError, match="execution_lag"):
        run_fast_research_backtest(
            factors(dates[:1], {"RB": [0.5]}),
            research_prices(dates, {"RB": [100.0, 101.0, 102.0]}),
            universe(dates[:1], ("RB",)),
            execution_lag=0,
        )


def test_missing_signal_is_not_forward_filled() -> None:
    dates = pd.date_range("2020-01-02", periods=5, freq="B")
    result = run_fast_research_backtest(
        factors(dates[:3], {"RB": [0.5, np.nan, 0.25]}),
        research_prices(dates, {"RB": [100, 101, 102, 103, 104]}),
        universe(dates[:3], ("RB",)),
        execution_lag=1,
    )
    detail = result["detail"]

    assert pd.isna(detail.loc[1, "research_exposure"])
    assert pd.isna(detail.loc[1, "gross_signal_return"])
    assert pd.isna(detail.loc[1, "turnover_proxy"])
    assert detail.loc[2, "turnover_proxy"] == pytest.approx(0.25)


def test_unavailable_future_return_remains_missing() -> None:
    dates = pd.date_range("2020-01-02", periods=3, freq="B")
    result = run_fast_research_backtest(
        factors(dates[-1:], {"RB": [0.5]}),
        research_prices(dates, {"RB": [100, 101, 102]}),
        universe(dates[-1:], ("RB",)),
        execution_lag=1,
    )

    row = result["detail"].iloc[0]
    assert pd.isna(row["return_start"])
    assert pd.isna(row["research_forward_return"])
    assert pd.isna(row["gross_signal_return"])


def test_pit_universe_excludes_future_product() -> None:
    dates = pd.date_range("2020-01-02", periods=4, freq="B")
    result = run_fast_research_backtest(
        factors(dates[:2], {"RB": [0.5, 0.5], "SI": [1.0, 1.0]}),
        research_prices(
            dates,
            {
                "RB": [100, 101, 102, 103],
                "SI": [200, 202, 204, 206],
            },
        ),
        universe(dates[:2], ("RB", "SI"), ineligible=("SI",)),
        execution_lag=1,
    )

    assert set(result["detail"]["instrument"]) == {"RB"}


def test_future_price_perturbation_cannot_change_earlier_results() -> None:
    dates = pd.date_range("2020-01-02", periods=5, freq="B")
    factor_data = factors(dates[:3], {"RB": [0.5, 0.5, 0.5]})
    universe_data = universe(dates[:3], ("RB",))
    original_prices = research_prices(dates, {"RB": [100, 101, 102, 103, 104]})
    changed_prices = original_prices.copy()
    changed_prices.attrs = original_prices.attrs.copy()
    changed_prices.loc[
        changed_prices["trading_date"].eq(dates[-1]), "close"
    ] = 1_000.0

    original = run_fast_research_backtest(
        factor_data,
        original_prices,
        universe_data,
        execution_lag=1,
    )["detail"]
    changed = run_fast_research_backtest(
        factor_data,
        changed_prices,
        universe_data,
        execution_lag=1,
    )["detail"]

    stable = original["realization_date"].lt(dates[-1])
    pd.testing.assert_frame_equal(
        original.loc[stable].reset_index(drop=True),
        changed.loc[stable].reset_index(drop=True),
    )
    assert original.loc[2, "research_forward_return"] != changed.loc[
        2, "research_forward_return"
    ]


def multi_year_inputs():
    dates = pd.to_datetime(
        [
            "2019-12-27",
            "2019-12-30",
            "2019-12-31",
            "2020-01-02",
            "2020-01-03",
            "2020-01-06",
        ]
    )
    price_data = research_prices(
        dates,
        {
            "RB": [100, 101, 103, 102, 106, 108],
            "CU": [200, 198, 197, 201, 199, 202],
        },
    )
    factor_data = factors(
        dates[:4],
        {
            "RB": [0.5, 0.7, -0.4, 0.3],
            "CU": [-0.5, -0.2, 0.6, -0.7],
        },
    )
    return dates, factor_data, price_data, universe(dates[:4], ("RB", "CU"))


def test_metrics_and_breakdowns_are_small_and_explicit() -> None:
    _, factor_data, price_data, universe_data = multi_year_inputs()
    result = run_fast_research_backtest(
        factor_data,
        price_data,
        universe_data,
        execution_lag=1,
    )

    assert tuple(result["overall"].columns) == METRIC_COLUMNS
    assert set(result["by_year"]["year"]) == {2019, 2020}
    assert set(result["by_instrument"]["instrument"]) == {"RB", "CU"}
    assert result["overall"].loc[0, "observations"] == 8
    assert pd.notna(result["overall"].loc[0, "mean_long_short_return"])
    assert result["detail"]["rough_cost"].dropna().eq(0.0).all()
    assert not any("nav" in column.lower() for column in result["detail"].columns)
    assert result["metadata"]["sector_breakdown"] == "deferred"


def test_same_inputs_and_config_are_reproducible() -> None:
    _, factor_data, price_data, universe_data = multi_year_inputs()
    first = run_fast_research_backtest(
        factor_data,
        price_data,
        universe_data,
        execution_lag=1,
        cost_rate=0.001,
    )
    second = run_fast_research_backtest(
        factor_data,
        price_data,
        universe_data,
        execution_lag=1,
        cost_rate=0.001,
    )

    for name in ("detail", "overall", "by_year", "by_instrument"):
        pd.testing.assert_frame_equal(first[name], second[name])
    assert first["metadata"] == second["metadata"]


def test_explicit_parameter_surface_does_not_select_a_winner() -> None:
    dates, _, price_data, universe_data = multi_year_inputs()

    def build(parameter):
        strength = parameter["lookback"] / 100.0
        return factors(
            dates[:4],
            {"RB": [strength] * 4, "CU": [-strength] * 4},
            factor_name=f"trend_{parameter['lookback']}d",
        )

    surface = run_parameter_surface(
        {"lookback": [40, 60, 80]},
        build,
        price_data,
        universe_data,
        execution_lag=1,
    )

    assert surface["overall"]["lookback"].tolist() == [40, 60, 80]
    assert set(surface["by_year"]["year"]) == {2019, 2020}
    assert set(surface["by_instrument"]["instrument"]) == {"RB", "CU"}
    assert not any(
        "best" in column.lower() or "rank" == column.lower()
        for column in surface["overall"].columns
    )


def test_research_run_persists_config_and_small_summaries(tmp_path) -> None:
    dates, factor_data, price_data, universe_data = multi_year_inputs()
    result = run_fast_research_backtest(
        factor_data,
        price_data,
        universe_data,
        execution_lag=1,
        cost_rate=0.001,
    )
    surface = run_parameter_surface(
        {"lookback": [40, 60]},
        lambda parameter: factors(
            dates[:4],
            {
                "RB": [parameter["lookback"] / 100.0] * 4,
                "CU": [-parameter["lookback"] / 100.0] * 4,
            },
            factor_name=f"trend_{parameter['lookback']}d",
        ),
        price_data,
        universe_data,
        execution_lag=1,
        cost_rate=0.001,
    )

    paths = save_research_run(
        result,
        "phase4-test",
        factor_parameters={"lookback": 60},
        signal_normalization_parameters={"signal_scale": 0.20},
        universe_settings={"min_listing_history_days": 0},
        parameter_grid={"lookback": [40, 60]},
        parameter_surface=surface,
        output_root=tmp_path / "results",
    )
    config = json.loads(paths["config"].read_text(encoding="utf-8"))

    assert config["execution_lag"] == 1
    assert config["research_only"] is True
    assert config["cash_pnl_allowed"] is False
    assert config["factor_parameters"] == {"lookback": 60}
    assert config["parameter_grid"] == {"lookback": [40, 60]}
    assert set(config["input_fingerprints"]) == {
        "factor",
        "research_prices",
        "universe",
    }
    assert paths["overall"].is_file()
    assert paths["by_year"].is_file()
    assert paths["by_instrument"].is_file()
    assert paths["parameter_surface_overall"].is_file()
    assert not (paths["config"].parent / "detail.csv").exists()


def test_cash_pnl_or_non_ratio_prices_are_rejected() -> None:
    dates = pd.date_range("2020-01-02", periods=3, freq="B")
    price_data = research_prices(dates, {"RB": [100, 101, 102]})
    price_data.attrs["cash_pnl_allowed"] = True

    with pytest.raises(ValueError, match="cash P&L"):
        run_fast_research_backtest(
            factors(dates[:1], {"RB": [0.5]}),
            price_data,
            universe(dates[:1], ("RB",)),
            execution_lag=1,
        )
