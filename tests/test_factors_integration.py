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
from china_cta.factors.carry import (
    calculate_near_main_carry,
    compute_carry_factor,
)
from china_cta.factors.schema import FACTOR_COLUMNS
from china_cta.factors.trend import compute_trend_factor


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_RQDATA_INTEGRATION") != "1",
        reason="set RUN_RQDATA_INTEGRATION=1 for licensed RQData checks",
    ),
]

TREND_DATE = "2020-06-15"
CARRY_DATE = "2020-06-12"


def licensed_adapter(tmp_path) -> RQDataAdapter:
    local = RQDataConfig.from_environment()
    adapter = RQDataAdapter(
        RQDataConfig(uri=local.uri, market=local.market, cache_dir=tmp_path)
    )
    adapter.connect(lazy=False)
    return adapter


def test_rb_cu_if_trend_matches_manual_60_period_return(tmp_path) -> None:
    adapter = licensed_adapter(tmp_path)
    products = ("RB", "CU", "IF")
    prices = get_signal_continuous_price(
        adapter,
        products,
        "2020-02-01",
        TREND_DATE,
        fields="close",
        adjust_type="pre",
        adjust_method="prev_close_ratio",
    )
    universe = get_research_universe(adapter, TREND_DATE)
    result = compute_trend_factor(prices, universe, lookback=60)

    assert tuple(result.columns) == FACTOR_COLUMNS
    assert set(result["instrument"]) == set(products)
    for product in products:
        product_prices = prices.loc[
            prices["underlying_symbol"].eq(product)
        ].sort_values("trading_date")
        expected = (
            product_prices.iloc[-1]["close"]
            / product_prices.iloc[-61]["close"]
            - 1.0
        )
        actual = result.set_index("instrument").loc[product, "raw_factor"]
        assert actual == pytest.approx(expected)


def test_rb_cu_carry_matches_manual_and_rqdata_benchmark(tmp_path) -> None:
    adapter = licensed_adapter(tmp_path)
    products = ("RB", "CU")
    snapshots = pd.concat(
        [
            get_contract_snapshot(
                adapter, product, CARRY_DATE, price_field="settlement"
            )
            for product in products
        ],
        ignore_index=True,
    )
    universe = get_research_universe(adapter, CARRY_DATE)
    diagnostics = calculate_near_main_carry(snapshots)
    factors = compute_carry_factor(snapshots, universe)
    benchmark = adapter.get_roll_yield(
        products,
        CARRY_DATE,
        CARRY_DATE,
        roll_type="near_main",
        rule=0,
    )

    assert tuple(factors.columns) == FACTOR_COLUMNS
    assert set(factors["instrument"]) == set(products)
    for product in products:
        own = diagnostics.set_index("instrument").loc[product]
        official = benchmark.set_index("underlying_symbol").loc[product]
        assert own["near_contract"] == official["from_contract"]
        assert own["far_contract"] == official["to_contract"]
        expected = (
            (own["near_price"] / own["far_price"] - 1.0)
            * 365.0
            / own["maturity_gap_days"]
        )
        assert own["raw_factor"] == pytest.approx(expected)
        assert own["raw_factor"] == pytest.approx(official["annualized_yield"])
