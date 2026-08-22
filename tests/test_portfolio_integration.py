from __future__ import annotations

import os

import numpy as np
import pandas as pd
import pytest

from china_cta.data.contracts import (
    get_contract_snapshot,
    get_dominant_contract,
    get_research_universe,
    get_signal_continuous_price,
)
from china_cta.data.rqdata_adapter import RQDataAdapter, RQDataConfig
from china_cta.factors.carry import compute_carry_factor
from china_cta.factors.trend import compute_trend_factor
from china_cta.portfolio.allocation import (
    TARGET_POSITION_COLUMNS,
    PortfolioConfig,
    construct_target_positions,
    load_product_classification,
    prepare_portfolio_market_data,
)


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_RQDATA_INTEGRATION") != "1",
        reason="set RUN_RQDATA_INTEGRATION=1 for licensed RQData checks",
    ),
]

SIGNAL_DATE = pd.Timestamp("2020-06-12")
PRODUCTS = ("RB", "CU", "IF")
COMMODITIES = ("RB", "CU")


def licensed_adapter(tmp_path) -> RQDataAdapter:
    local = RQDataConfig.from_environment()
    adapter = RQDataAdapter(
        RQDataConfig(uri=local.uri, market=local.market, cache_dir=tmp_path)
    )
    adapter.connect(lazy=False)
    return adapter


def portfolio_config() -> PortfolioConfig:
    return PortfolioConfig(
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
        source_tag="portfolio_v1",
    )


def real_inputs(adapter: RQDataAdapter, end_date: str):
    universe = get_research_universe(adapter, SIGNAL_DATE)
    prices = get_signal_continuous_price(
        adapter,
        PRODUCTS,
        "2020-01-15",
        end_date,
        fields="close",
        adjust_type="pre",
        adjust_method="prev_close_ratio",
    )
    trend = compute_trend_factor(prices, universe, lookback=60)
    snapshots = pd.concat(
        [
            get_contract_snapshot(
                adapter,
                product,
                SIGNAL_DATE,
                price_field="settlement",
            )
            for product in COMMODITIES
        ],
        ignore_index=True,
    )
    carry = compute_carry_factor(snapshots, universe)
    signals = pd.concat([trend, carry], ignore_index=True)
    signals.attrs.update(
        {
            "information_date": "trading_date",
            "signal_available_at": "after_close_of_trading_date",
            "earliest_trade_at": "next_trading_session",
            "signal_is_position": False,
        }
    )
    return universe, prices, signals


def test_real_rb_cu_if_target_chain_is_manually_reconciled(tmp_path) -> None:
    adapter = licensed_adapter(tmp_path)
    config = portfolio_config()
    universe, prices, signals = real_inputs(adapter, "2020-06-12")
    market = prepare_portfolio_market_data(adapter, signals, config)
    result = construct_target_positions(
        signals,
        prices,
        universe,
        market,
        load_product_classification(),
        config,
    )
    diagnostics = result["diagnostics"]

    assert tuple(result["targets"].columns) == TARGET_POSITION_COLUMNS
    assert set(result["targets"]["trading_date"]) == set(
        market["target_effective_date"]
    )
    assert not result["targets"]["trading_date"].eq(SIGNAL_DATE).any()
    assert result["metadata"]["target_trading_date_definition"] == (
        "target_effective_date_earliest_execution_trading_date"
    )
    assert set(diagnostics["instrument"]) == set(PRODUCTS)
    assert diagnostics["availability_reason"].eq("available").all()
    assert set(result["targets"]["order_book_id"]) == set(
        market["order_book_id"]
    )
    assert diagnostics["target_quantity"].notna().all()

    for row in diagnostics.itertuples(index=False):
        product_prices = prices.loc[
            prices["underlying_symbol"].eq(row.instrument)
            & prices["trading_date"].le(SIGNAL_DATE)
        ].sort_values("trading_date")
        returns = product_prices["close"].pct_change(fill_method=None).iloc[-20:]
        expected_vol = returns.std(ddof=1) * np.sqrt(252)
        expected_vol = max(expected_vol, config.volatility_floor)
        expected_contract = get_dominant_contract(
            adapter,
            row.instrument,
            row.target_effective_date,
        )
        expected_pre_margin_quantity = row.target_notional / (
            row.trade_price * row.contract_multiplier
        )
        expected_quantity = int(
            np.trunc(expected_pre_margin_quantity * row.margin_scale)
        )

        assert row.vol_forecast == pytest.approx(expected_vol)
        assert row.order_book_id == expected_contract
        assert row.pre_margin_quantity_float == pytest.approx(
            expected_pre_margin_quantity
        )
        assert row.target_quantity == expected_quantity
        assert row.estimated_margin_post == pytest.approx(
            abs(expected_quantity)
            * row.trade_price
            * row.contract_multiplier
            * row.margin_ratio
        )
        if row.daily_volume > 0:
            assert row.quantity_to_volume == pytest.approx(
                abs(expected_quantity) / row.daily_volume
            )
        if row.open_interest > 0:
            assert row.quantity_to_open_interest == pytest.approx(
                abs(expected_quantity) / row.open_interest
            )


def test_real_future_extension_cannot_change_signal_date_targets(tmp_path) -> None:
    adapter = licensed_adapter(tmp_path)
    config = portfolio_config()
    universe, short_prices, short_signals = real_inputs(adapter, "2020-06-12")
    _, extended_prices, extended_signals = real_inputs(adapter, "2020-08-31")
    short_market = prepare_portfolio_market_data(adapter, short_signals, config)
    extended_market = prepare_portfolio_market_data(
        adapter, extended_signals, config
    )

    short = construct_target_positions(
        short_signals,
        short_prices,
        universe,
        short_market,
        load_product_classification(),
        config,
    )
    extended = construct_target_positions(
        extended_signals,
        extended_prices,
        universe,
        extended_market,
        load_product_classification(),
        config,
    )

    pd.testing.assert_frame_equal(short["targets"], extended["targets"])
    pd.testing.assert_frame_equal(
        short["diagnostics"], extended["diagnostics"]
    )
