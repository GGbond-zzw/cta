from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from china_cta.portfolio.allocation import (
    CONTRIBUTION_COLUMNS,
    DIAGNOSTIC_COLUMNS,
    TARGET_POSITION_COLUMNS,
    PortfolioConfig,
    construct_target_positions,
    load_product_classification,
    prepare_portfolio_market_data,
)
from china_cta.portfolio.volatility import (
    VOLATILITY_COLUMNS,
    compute_rolling_volatility,
)


DATES = pd.date_range("2020-01-02", periods=6, freq="B")
SIGNAL_DATE = DATES[4]
TARGET_DATE = DATES[5]
PRICES = {
    "RB": [100.0, 102.0, 101.0, 103.0, 104.0, 105.0],
    "CU": [200.0, 198.0, 202.0, 201.0, 205.0, 206.0],
    "IF": [4000.0, 4020.0, 4010.0, 4050.0, 4070.0, 4090.0],
}


def research_prices(values_by_instrument=PRICES) -> pd.DataFrame:
    rows = [
        {
            "trading_date": date,
            "underlying_symbol": instrument,
            "close": value,
        }
        for instrument, values in values_by_instrument.items()
        for date, value in zip(DATES, values, strict=True)
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


def factors(*, include_si: bool = False, rb_signal: float = 0.6) -> pd.DataFrame:
    rows = [
        {
            "trading_date": SIGNAL_DATE,
            "instrument": "RB",
            "factor_name": "trend_3d",
            "raw_factor": rb_signal,
            "signal": rb_signal,
        },
        {
            "trading_date": SIGNAL_DATE,
            "instrument": "RB",
            "factor_name": "carry_near_main",
            "raw_factor": 0.2,
            "signal": 0.2,
        },
        {
            "trading_date": SIGNAL_DATE,
            "instrument": "CU",
            "factor_name": "trend_3d",
            "raw_factor": -0.4,
            "signal": -0.4,
        },
        {
            "trading_date": SIGNAL_DATE,
            "instrument": "CU",
            "factor_name": "carry_near_main",
            "raw_factor": -0.2,
            "signal": -0.2,
        },
        {
            "trading_date": SIGNAL_DATE,
            "instrument": "IF",
            "factor_name": "trend_3d",
            "raw_factor": 0.5,
            "signal": 0.5,
        },
    ]
    if include_si:
        rows.append(
            {
                "trading_date": SIGNAL_DATE,
                "instrument": "SI",
                "factor_name": "trend_3d",
                "raw_factor": 1.0,
                "signal": 1.0,
            }
        )
    frame = pd.DataFrame(rows)
    frame.attrs.update(
        {
            "information_date": "trading_date",
            "signal_available_at": "after_close_of_trading_date",
            "earliest_trade_at": "next_trading_session",
            "signal_is_position": False,
        }
    )
    return frame


def universe(*, include_si: bool = False) -> pd.DataFrame:
    instruments = ["RB", "CU", "IF"] + (["SI"] if include_si else [])
    return pd.DataFrame(
        {
            "trading_date": [SIGNAL_DATE] * len(instruments),
            "instrument": instruments,
            "eligible": [instrument != "SI" for instrument in instruments],
        }
    )


def market_data() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "signal_date": SIGNAL_DATE,
                "target_effective_date": TARGET_DATE,
                "instrument": "RB",
                "order_book_id": "RB2005",
                "trade_contract_rule": 0,
                "trade_contract_rank": 1,
                "trade_price": 3500.0,
                "price_field": "settlement",
                "contract_multiplier": 10.0,
                "long_margin_ratio": 0.10,
                "short_margin_ratio": 0.11,
                "daily_volume": 1_000_000.0,
                "open_interest": 2_000_000.0,
                "market_data_reason": "available",
            },
            {
                "signal_date": SIGNAL_DATE,
                "target_effective_date": TARGET_DATE,
                "instrument": "CU",
                "order_book_id": "CU2002",
                "trade_contract_rule": 0,
                "trade_contract_rank": 1,
                "trade_price": 49_000.0,
                "price_field": "settlement",
                "contract_multiplier": 5.0,
                "long_margin_ratio": 0.12,
                "short_margin_ratio": 0.13,
                "daily_volume": 200_000.0,
                "open_interest": 300_000.0,
                "market_data_reason": "available",
            },
            {
                "signal_date": SIGNAL_DATE,
                "target_effective_date": TARGET_DATE,
                "instrument": "IF",
                "order_book_id": "IF2001",
                "trade_contract_rule": 0,
                "trade_contract_rank": 1,
                "trade_price": 4100.0,
                "price_field": "settlement",
                "contract_multiplier": 300.0,
                "long_margin_ratio": 0.12,
                "short_margin_ratio": 0.12,
                "daily_volume": 100_000.0,
                "open_interest": 150_000.0,
                "market_data_reason": "available",
            },
        ]
    )


def classifications(*, common_metals_group: bool = False) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "instrument": ["RB", "CU", "IF"],
            "sector": (
                ["metals", "metals", "equity_index"]
                if common_metals_group
                else ["ferrous_metals", "nonferrous_metals", "equity_index"]
            ),
            "industrial_chain": (
                ["metals", "metals", "equity_index"]
                if common_metals_group
                else ["steel", "base_metals", "equity_index"]
            ),
        }
    )
    frame.attrs["version"] = "test_v1"
    return frame


def config(**changes) -> PortfolioConfig:
    base = PortfolioConfig(
        initial_capital=10_000_000.0,
        portfolio_vol_target=0.10,
        volatility_method="rolling_close_to_close_simple_return",
        volatility_lookback=3,
        minimum_volatility_observations=3,
        annualization_factor=252,
        volatility_floor=0.01,
        strategy_weights={"trend_3d": 0.6, "carry_near_main": 0.4},
        instrument_cap=None,
        sector_gross_cap=None,
        chain_gross_cap=None,
        risk_estimator="diagonal",
        max_margin_fraction=1.0,
        target_lag_sessions=1,
        trade_contract_rule=0,
        trade_contract_rank=1,
        trade_price_field="settlement",
        rounding_rule="toward_zero",
        source_tag="portfolio_v1",
    )
    return replace(base, **changes)


def run_portfolio(**config_changes):
    return construct_target_positions(
        factors(),
        research_prices(),
        universe(),
        market_data(),
        classifications(),
        config(**config_changes),
    )


def test_rolling_volatility_matches_manual_sample_standard_deviation() -> None:
    result = compute_rolling_volatility(
        research_prices(),
        lookback=3,
        minimum_observations=3,
        annualization_factor=252,
        volatility_floor=0.01,
    )
    rb = result.loc[
        result["instrument"].eq("RB")
        & result["trading_date"].eq(SIGNAL_DATE)
    ].iloc[0]
    expected_returns = np.array(
        [101.0 / 102.0 - 1.0, 103.0 / 101.0 - 1.0, 104.0 / 103.0 - 1.0]
    )
    expected = expected_returns.std(ddof=1) * np.sqrt(252)

    assert tuple(result.columns) == VOLATILITY_COLUMNS
    assert rb["raw_volatility"] == pytest.approx(expected)
    assert rb["vol_forecast"] == pytest.approx(max(expected, 0.01))
    assert not bool(rb["vol_floor_applied"])
    assert result.attrs["missing_price_rule"] == "no_fill"


def test_zero_volatility_is_unavailable_instead_of_using_the_floor() -> None:
    constant = research_prices({"RB": [100.0] * len(DATES)})

    result = compute_rolling_volatility(
        constant,
        lookback=3,
        minimum_observations=3,
        annualization_factor=252,
        volatility_floor=0.01,
    )

    assert result["raw_volatility"].isna().all()
    assert result["vol_forecast"].isna().all()
    assert not result["vol_floor_applied"].any()


def test_phase3_signal_is_consumed_directly_and_fixed_weights_are_traceable() -> None:
    result = run_portfolio()
    contributions = result["contributions"]
    diagnostics = result["diagnostics"].set_index("instrument")
    rb = diagnostics.loc["RB"]
    if_row = diagnostics.loc["IF"]

    expected_rb_signal = 0.6 * 0.6 + 0.4 * 0.2
    expected_if_signal = 0.6 * 0.5
    assert tuple(contributions.columns) == CONTRIBUTION_COLUMNS
    assert rb["aggregated_signal"] == pytest.approx(expected_rb_signal)
    assert rb["aggregated_risk"] == pytest.approx(
        expected_rb_signal / rb["vol_forecast"]
    )
    assert if_row["aggregated_signal"] == pytest.approx(expected_if_signal)
    assert result["metadata"]["signal_handling"].endswith(
        "no_renormalization"
    )
    assert result["metadata"]["config"]["strategy_weights"] == {
        "carry_near_main": 0.4,
        "trend_3d": 0.6,
    }


def test_instrument_sector_chain_caps_and_diagonal_scale_are_manual() -> None:
    cfg = config(
        instrument_cap=1.0,
        sector_gross_cap=1.5,
        chain_gross_cap=1.2,
    )
    result = construct_target_positions(
        factors(),
        research_prices(),
        universe(),
        market_data(),
        classifications(common_metals_group=True),
        cfg,
    )
    diagnostics = result["diagnostics"]
    metals = diagnostics.loc[diagnostics["sector"].eq("metals")]

    assert diagnostics["pre_instrument_cap"].abs().max() > 1.0
    assert diagnostics["post_instrument_cap"].abs().max() <= 1.0
    assert metals["sector_gross_pre_cap"].iloc[0] == pytest.approx(2.0)
    assert metals["sector_scale"].iloc[0] == pytest.approx(1.5 / 2.0)
    assert metals["chain_gross_pre_cap"].iloc[0] == pytest.approx(1.5)
    assert metals["chain_scale"].iloc[0] == pytest.approx(1.2 / 1.5)

    expected_risk = np.sqrt(
        np.square(
            diagnostics["post_chain_cap"] * diagnostics["vol_forecast"]
        ).sum()
    )
    expected_scale = cfg.portfolio_vol_target / expected_risk
    assert diagnostics["estimated_portfolio_risk_pre"].iloc[0] == pytest.approx(
        expected_risk
    )
    assert diagnostics["portfolio_scale_factor"].iloc[0] == pytest.approx(
        expected_scale
    )
    assert diagnostics["estimated_portfolio_risk_post"].iloc[0] == pytest.approx(
        cfg.portfolio_vol_target
    )


def test_target_quantity_unit_chain_and_capacity_are_manual() -> None:
    result = run_portfolio()
    targets = result["targets"]
    diagnostics = result["diagnostics"].set_index("instrument")
    rb = diagnostics.loc["RB"]

    expected_notional = (
        config().initial_capital * rb["post_scale_exposure"]
    )
    expected_float = expected_notional / (3500.0 * 10.0)
    expected_quantity = int(np.trunc(expected_float))
    assert tuple(targets.columns) == TARGET_POSITION_COLUMNS
    assert targets["trading_date"].eq(TARGET_DATE).all()
    assert not targets["trading_date"].eq(SIGNAL_DATE).any()
    assert targets.attrs["trading_date_role"] == (
        "target_effective_date_earliest_execution_trading_date"
    )
    assert rb["target_notional"] == pytest.approx(expected_notional)
    assert rb["pre_margin_quantity_float"] == pytest.approx(expected_float)
    assert rb["target_quantity"] == expected_quantity
    assert rb["quantity_to_volume"] == pytest.approx(
        abs(expected_quantity) / 1_000_000.0
    )
    assert rb["quantity_to_open_interest"] == pytest.approx(
        abs(expected_quantity) / 2_000_000.0
    )
    assert result["metadata"]["capacity_changes_target_quantity"] is False


def test_margin_sanity_scales_the_whole_portfolio_and_stays_below_limit() -> None:
    result = run_portfolio(max_margin_fraction=0.01)
    diagnostics = result["diagnostics"]
    scales = diagnostics["margin_scale"].unique()

    assert len(scales) == 1
    assert 0 < scales[0] < 1
    expected_scale = diagnostics["margin_limit"].iloc[0] / diagnostics[
        "estimated_margin_pre"
    ].sum()
    assert scales[0] == pytest.approx(expected_scale)
    assert diagnostics["estimated_margin_post"].sum() <= (
        diagnostics["margin_limit"].iloc[0] + 1e-9
    )
    assert diagnostics["margin_reason"].eq("scaled_to_margin_limit").all()
    assert result["metadata"]["margin_sanity_only"] is True
    assert result["metadata"]["formal_margin_accounting"] is False


def test_capacity_inputs_do_not_change_target_quantity() -> None:
    original = run_portfolio()
    changed_market = market_data()
    changed_market[["daily_volume", "open_interest"]] *= 10.0
    changed = construct_target_positions(
        factors(),
        research_prices(),
        universe(),
        changed_market,
        classifications(),
        config(),
    )

    pd.testing.assert_frame_equal(original["targets"], changed["targets"])
    assert not original["diagnostics"]["quantity_to_volume"].equals(
        changed["diagnostics"]["quantity_to_volume"]
    )


def test_pit_universe_excludes_future_product_and_missing_mapping_is_explicit() -> None:
    result = construct_target_positions(
        factors(include_si=True),
        research_prices(),
        universe(include_si=True),
        market_data(),
        classifications(),
        config(),
    )
    assert "SI" not in set(result["diagnostics"]["instrument"])

    incomplete = classifications().loc[
        lambda frame: frame["instrument"].ne("RB")
    ]
    with pytest.raises(ValueError, match="classification"):
        construct_target_positions(
            factors(),
            research_prices(),
            universe(),
            market_data(),
            incomplete,
            config(sector_gross_cap=2.0),
        )


def test_missing_signal_and_non_baseline_trade_contract_are_unavailable() -> None:
    missing_signal = factors()
    missing_signal.loc[missing_signal["instrument"].eq("RB"), "signal"] = np.nan
    first = construct_target_positions(
        missing_signal,
        research_prices(),
        universe(),
        market_data(),
        classifications(),
        config(),
    )
    rb = first["diagnostics"].set_index("instrument").loc["RB"]
    assert rb["availability_reason"] == "signal_unavailable"
    assert "RB2005" not in set(first["targets"]["order_book_id"])

    wrong_rule = market_data()
    wrong_rule.loc[wrong_rule["instrument"].eq("RB"), "trade_contract_rule"] = 1
    second = construct_target_positions(
        factors(),
        research_prices(),
        universe(),
        wrong_rule,
        classifications(),
        config(),
    )
    rb = second["diagnostics"].set_index("instrument").loc["RB"]
    assert rb["availability_reason"] == "trade_contract_rule_mismatch"
    assert "RB2005" not in set(second["targets"]["order_book_id"])


def test_future_price_change_cannot_change_an_earlier_target() -> None:
    original_prices = research_prices()
    changed_prices = original_prices.copy()
    changed_prices.attrs = original_prices.attrs.copy()
    changed_prices.loc[
        changed_prices["trading_date"].eq(TARGET_DATE), "close"
    ] *= 10.0
    original = construct_target_positions(
        factors(),
        original_prices,
        universe(),
        market_data(),
        classifications(),
        config(),
    )
    changed = construct_target_positions(
        factors(),
        changed_prices,
        universe(),
        market_data(),
        classifications(),
        config(),
    )

    pd.testing.assert_frame_equal(original["targets"], changed["targets"])
    pd.testing.assert_frame_equal(
        original["diagnostics"], changed["diagnostics"]
    )


def test_same_inputs_and_config_are_fully_reproducible() -> None:
    first = run_portfolio()
    second = run_portfolio()

    for name in ("targets", "diagnostics", "contributions"):
        pd.testing.assert_frame_equal(first[name], second[name])
    assert first["metadata"] == second["metadata"]


class StubAdapter:
    def __init__(self) -> None:
        self.dominant_dates: list[pd.Timestamp] = []
        self.bar_dates: list[pd.Timestamp] = []
        self.parameter_dates: list[pd.Timestamp] = []

    def get_trading_calendar(self, start_date, end_date):
        return pd.DatetimeIndex(["2020-01-07", "2020-01-08", "2020-01-09"])

    def get_dominant_map(self, product, start, end, *, rule, rank):
        date = pd.Timestamp(start)
        self.dominant_dates.append(date)
        assert rule == 0 and rank == 1 and date == pd.Timestamp("2020-01-08")
        return pd.DataFrame(
            {
                "trading_date": [date],
                "underlying_symbol": [product],
                "dominant_order_book_id": ["RB2005"],
            }
        )

    def get_bars(self, contract, start, end, *, fields):
        date = pd.Timestamp(start)
        self.bar_dates.append(date)
        return pd.DataFrame(
            {
                "trading_date": [date],
                "order_book_id": [contract],
                "settlement": [3500.0],
                "volume": [100_000.0],
                "open_interest": [200_000.0],
            }
        )

    def get_instrument_details(self, contract):
        return pd.DataFrame(
            {"order_book_id": [contract], "contract_multiplier": [10.0]}
        )

    def get_trading_parameters(self, contract, start, end):
        date = pd.Timestamp(start)
        self.parameter_dates.append(date)
        return pd.DataFrame(
            {
                "trading_date": [date],
                "order_book_id": [contract],
                "long_margin_ratio": [0.10],
                "short_margin_ratio": [0.11],
            }
        )


def test_market_input_uses_next_session_contract_and_no_future_price() -> None:
    adapter = StubAdapter()
    one_factor = factors().loc[
        lambda frame: frame["instrument"].eq("RB")
        & frame["factor_name"].eq("trend_3d")
    ].copy()
    one_factor["trading_date"] = pd.Timestamp("2020-01-07")

    result = prepare_portfolio_market_data(adapter, one_factor, config())

    assert result.loc[0, "signal_date"] == pd.Timestamp("2020-01-07")
    assert result.loc[0, "target_effective_date"] == pd.Timestamp("2020-01-08")
    assert result.loc[0, "order_book_id"] == "RB2005"
    assert adapter.dominant_dates == [pd.Timestamp("2020-01-08")]
    assert adapter.bar_dates == [pd.Timestamp("2020-01-07")]
    assert adapter.parameter_dates == [pd.Timestamp("2020-01-08")]


def test_versioned_product_classification_is_deliberately_small() -> None:
    result = load_product_classification()

    assert set(result["instrument"]) == {"RB", "CU", "IF"}
    assert result.attrs["version"] == "product_classification_v1"
    assert result.set_index("instrument").loc["RB", "industrial_chain"] == "steel"


def test_v1_rejects_unapproved_price_or_risk_model_variants() -> None:
    with pytest.raises(ValueError, match="settlement"):
        construct_target_positions(
            factors(),
            research_prices(),
            universe(),
            market_data(),
            classifications(),
            config(trade_price_field="close"),
        )
    with pytest.raises(ValueError, match="diagonal"):
        construct_target_positions(
            factors(),
            research_prices(),
            universe(),
            market_data(),
            classifications(),
            config(risk_estimator="covariance"),
        )
