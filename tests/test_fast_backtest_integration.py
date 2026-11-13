from __future__ import annotations

import os

import pandas as pd
import pytest

from china_cta.data.contracts import (
    get_contract_snapshot,
    get_research_universe,
    get_signal_continuous_price,
)
from china_cta.data.rqdata_adapter import RQDataAdapter, RQDataConfig
from china_cta.factors.unqualified.carry import compute_carry_factor
from china_cta.factors.unqualified.trend import compute_trend_factor
from china_cta.research.fast_backtest import (
    DETAIL_COLUMNS,
    run_fast_research_backtest,
    run_parameter_surface,
)


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_RQDATA_INTEGRATION") != "1",
        reason="set RUN_RQDATA_INTEGRATION=1 for licensed RQData checks",
    ),
]

PRODUCTS = ("RB", "CU", "IF")
COMMODITIES = ("RB", "CU")
SIGNAL_DATES = pd.to_datetime(["2020-06-10", "2020-06-11", "2020-06-12"])


def licensed_adapter(tmp_path) -> RQDataAdapter:
    local = RQDataConfig.from_environment()
    adapter = RQDataAdapter(
        RQDataConfig(uri=local.uri, market=local.market, cache_dir=tmp_path)
    )
    adapter.connect(lazy=False)
    return adapter


def pit_universe(adapter: RQDataAdapter) -> pd.DataFrame:
    return pd.concat(
        [get_research_universe(adapter, date) for date in SIGNAL_DATES],
        ignore_index=True,
    )


def test_continuous_trend_value_is_stable_when_end_date_extends(tmp_path) -> None:
    adapter = licensed_adapter(tmp_path)
    research_date = "2020-06-15"
    universe = pd.DataFrame(
        {
            "trading_date": [research_date] * len(PRODUCTS),
            "instrument": PRODUCTS,
            "eligible": [True] * len(PRODUCTS),
        }
    )
    end_at_t = get_signal_continuous_price(
        adapter,
        PRODUCTS,
        "2020-02-01",
        research_date,
        fields="close",
        adjust_type="pre",
        adjust_method="prev_close_ratio",
    )
    extended = get_signal_continuous_price(
        adapter,
        PRODUCTS,
        "2020-02-01",
        "2020-08-31",
        fields="close",
        adjust_type="pre",
        adjust_method="prev_close_ratio",
    )

    short_factor = compute_trend_factor(
        end_at_t, universe, lookback=60
    ).sort_values("instrument")
    extended_factor = compute_trend_factor(
        extended, universe, lookback=60
    ).sort_values("instrument")

    pd.testing.assert_series_equal(
        short_factor.set_index("instrument")["raw_factor"],
        extended_factor.set_index("instrument")["raw_factor"],
        check_names=False,
        rtol=0,
        atol=0,
    )


def test_trend_carry_and_parameter_surface_share_one_backtest(tmp_path) -> None:
    adapter = licensed_adapter(tmp_path)
    universe = pit_universe(adapter)
    assert "SI" not in set(universe["instrument"])
    prices = get_signal_continuous_price(
        adapter,
        PRODUCTS,
        "2020-01-15",
        "2020-06-17",
        fields="close",
        adjust_type="pre",
        adjust_method="prev_close_ratio",
    )
    trend = compute_trend_factor(prices, universe, lookback=60)
    snapshots = pd.concat(
        [
            get_contract_snapshot(
                adapter, product, date, price_field="close"
            )
            for date in SIGNAL_DATES
            for product in COMMODITIES
        ],
        ignore_index=True,
    )
    carry = compute_carry_factor(snapshots, universe)

    trend_result = run_fast_research_backtest(
        trend, prices, universe, execution_lag=1
    )
    carry_result = run_fast_research_backtest(
        carry, prices, universe, execution_lag=1
    )

    assert tuple(trend_result["detail"].columns) == DETAIL_COLUMNS
    assert tuple(carry_result["detail"].columns) == DETAIL_COLUMNS
    assert set(trend_result["detail"]["instrument"]) == set(PRODUCTS)
    assert set(carry_result["detail"]["instrument"]) == set(COMMODITIES)
    for result in (trend_result, carry_result):
        valid = result["detail"].dropna(subset=["research_forward_return"])
        assert not valid.empty
        for row in valid.itertuples(index=False):
            product_prices = prices.loc[
                prices["underlying_symbol"].eq(row.instrument)
            ].set_index("trading_date")["close"]
            expected = (
                product_prices.loc[row.return_end]
                / product_prices.loc[row.return_start]
                - 1.0
            )
            assert row.research_forward_return == pytest.approx(expected)
            assert row.gross_signal_return == pytest.approx(row.signal * expected)

    surface = run_parameter_surface(
        {"lookback": [40, 60, 80]},
        lambda parameter: compute_trend_factor(
            prices, universe, lookback=parameter["lookback"]
        ),
        prices,
        universe,
        execution_lag=1,
    )
    assert surface["overall"]["lookback"].tolist() == [40, 60, 80]
    assert set(surface["by_instrument"]["instrument"]) == set(PRODUCTS)
