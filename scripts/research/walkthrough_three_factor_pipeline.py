"""Run a small, real-data walkthrough of the three-factor CTA pipeline.

This teaching script composes existing public functions.  It does not contain
alternative research, portfolio, execution, or accounting logic.  The formal
section holds the single 2020-05-08 target snapshot through 2020-06-08; it is
an account-path demonstration, not a dynamic one-month Alpha backtest.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from china_cta.data.contracts import (
    get_contract_snapshot,
    get_research_universe,
    get_roll_map,
    get_signal_continuous_price,
)
from china_cta.data.rqdata_adapter import RQDataAdapter
from china_cta.factors.unqualified.carry import (
    calculate_near_main_carry,
    compute_carry_factor,
)
from china_cta.factors.unqualified.oi_confirmed_trend import (
    calculate_oi_confirmed_trend,
    compute_oi_confirmed_trend_factor,
)
from china_cta.factors.unqualified.trend import compute_trend_factor
from china_cta.formal_backtest import FormalBacktestConfig, run_formal_backtest
from china_cta.portfolio import (
    PortfolioConfig,
    construct_target_positions,
    load_product_classification,
    prepare_portfolio_market_data,
)
from china_cta.research import run_fast_research_backtest
from china_cta.runtime_paths import get_rqalpha_bundle_path


BUNDLE_PATH = get_rqalpha_bundle_path()
PRODUCTS = ("RB", "CU", "IF")
COMMODITIES = ("RB", "CU")
SIGNAL_START = pd.Timestamp("2020-04-27")
SIGNAL_END = pd.Timestamp("2020-05-07")
PRICE_START = pd.Timestamp("2020-01-15")
PRICE_END = pd.Timestamp("2020-05-11")
FORMAL_END = pd.Timestamp("2020-06-08")
STRATEGY_WEIGHTS = {
    "trend_60d": 0.50,
    "carry_near_main": 0.30,
    "oi_confirmed_trend_20d": 0.20,
}


def main() -> int:
    adapter = RQDataAdapter()
    adapter.connect(lazy=False)

    signal_dates = adapter.get_trading_calendar(SIGNAL_START, SIGNAL_END)
    universe = pd.concat(
        [get_research_universe(adapter, date) for date in signal_dates],
        ignore_index=True,
    )
    research_prices = get_signal_continuous_price(
        adapter,
        PRODUCTS,
        PRICE_START,
        PRICE_END,
        fields=("close", "open_interest"),
        adjust_type="pre",
        adjust_method="prev_close_ratio",
    )
    dominant_map = pd.concat(
        [
            get_roll_map(adapter, product, PRICE_START, SIGNAL_END)
            for product in PRODUCTS
        ],
        ignore_index=True,
    )

    trend = compute_trend_factor(
        research_prices,
        universe,
        lookback=60,
        signal_scale=0.20,
    )
    oi_diagnostics = calculate_oi_confirmed_trend(
        research_prices,
        dominant_map,
        lookback=20,
    )
    oi_trend = compute_oi_confirmed_trend_factor(
        research_prices,
        dominant_map,
        universe,
        lookback=20,
        signal_scale=0.02,
    )

    curve_rows: list[pd.DataFrame] = []
    for date in signal_dates:
        for product in COMMODITIES:
            curve_rows.append(
                get_contract_snapshot(
                    adapter,
                    product,
                    date,
                    price_field="close",
                )
            )
    curves = pd.concat(curve_rows, ignore_index=True)
    carry_diagnostics = calculate_near_main_carry(curves)
    carry = compute_carry_factor(curves, universe, signal_scale=0.20)

    _print_data_and_factor_steps(
        universe,
        research_prices,
        dominant_map,
        trend,
        carry,
        carry_diagnostics,
        oi_trend,
        oi_diagnostics,
    )
    _print_fast_research(trend, carry, oi_trend, research_prices, universe)

    signal_date = SIGNAL_END
    combined_signals = pd.concat(
        [
            trend.loc[trend["trading_date"].eq(signal_date)],
            carry.loc[carry["trading_date"].eq(signal_date)],
            oi_trend.loc[oi_trend["trading_date"].eq(signal_date)],
        ],
        ignore_index=True,
    )
    combined_signals.attrs.update(
        {
            "information_date": "trading_date",
            "signal_available_at": "after_close_of_trading_date",
            "earliest_trade_at": "next_trading_session",
            "signal_is_position": False,
        }
    )
    config = _portfolio_config()
    market = prepare_portfolio_market_data(adapter, combined_signals, config)
    portfolio_result = construct_target_positions(
        combined_signals,
        research_prices,
        universe.loc[universe["trading_date"].eq(signal_date)],
        market,
        load_product_classification(),
        config,
    )
    _print_portfolio_steps(combined_signals, portfolio_result)
    _run_and_print_formal(portfolio_result, config)
    return 0


def _portfolio_config() -> PortfolioConfig:
    return PortfolioConfig(
        initial_capital=10_000_000.0,
        portfolio_vol_target=0.10,
        volatility_method="rolling_close_to_close_simple_return",
        volatility_lookback=20,
        minimum_volatility_observations=20,
        annualization_factor=252,
        volatility_floor=0.05,
        strategy_weights=STRATEGY_WEIGHTS,
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
        source_tag="three_factor_demo",
    )


def _print_data_and_factor_steps(
    universe: pd.DataFrame,
    research_prices: pd.DataFrame,
    dominant_map: pd.DataFrame,
    trend: pd.DataFrame,
    carry: pd.DataFrame,
    carry_diagnostics: pd.DataFrame,
    oi_trend: pd.DataFrame,
    oi_diagnostics: pd.DataFrame,
) -> None:
    date = SIGNAL_END
    print("\n=== STEP 1: PIT universe and signal data ===")
    _show(
        universe.loc[
            universe["trading_date"].eq(date)
            & universe["instrument"].isin(PRODUCTS),
            ["trading_date", "instrument", "eligible", "reason"],
        ]
    )
    _show(
        dominant_map.loc[
            dominant_map["trading_date"].eq(date),
            ["trading_date", "underlying_symbol", "dominant_order_book_id"],
        ]
    )
    print("Continuous price usage:", research_prices.attrs.get("usage"))
    print("Continuous price cash P&L allowed:", research_prices.attrs.get("cash_pnl_allowed"))

    print(f"\n=== STEP 2: three standard factor tables on {date.date()} ===")
    _show(
        pd.concat(
            [
                trend.loc[trend["trading_date"].eq(date)],
                carry.loc[carry["trading_date"].eq(date)],
                oi_trend.loc[oi_trend["trading_date"].eq(date)],
            ],
            ignore_index=True,
        )
    )

    print("\nCarry real-contract inputs:")
    _show(
        carry_diagnostics.loc[
            carry_diagnostics["trading_date"].eq(date),
            [
                "instrument",
                "near_contract",
                "far_contract",
                "near_maturity",
                "far_maturity",
                "near_price",
                "far_price",
                "maturity_gap_days",
                "raw_factor",
            ],
        ]
    )
    print("\nOI-confirmed Trend inputs:")
    _show(
        oi_diagnostics.loc[
            oi_diagnostics["trading_date"].eq(date),
            [
                "instrument",
                "dominant_order_book_id",
                "price_return",
                "open_interest_change",
                "oi_confirmation",
                "roll_in_window",
                "raw_factor",
            ],
        ]
    )


def _print_fast_research(
    trend: pd.DataFrame,
    carry: pd.DataFrame,
    oi_trend: pd.DataFrame,
    research_prices: pd.DataFrame,
    universe: pd.DataFrame,
) -> None:
    print("\n=== STEP 3: Fast Research screens factors separately ===")
    for factors in (trend, carry, oi_trend):
        result = run_fast_research_backtest(
            factors,
            research_prices,
            universe,
            execution_lag=1,
            cost_rate=0.0001,
        )
        print(f"\nFactor: {factors['factor_name'].dropna().iloc[0]}")
        _show(result["overall"])
        _show(
            result["by_instrument"].loc[
                :,
                [
                    "instrument",
                    "observations",
                    "cumulative_net_signal_return",
                    "sharpe",
                    "mean_turnover_proxy",
                ],
            ]
        )


def _print_portfolio_steps(
    combined_signals: pd.DataFrame,
    portfolio_result: dict[str, object],
) -> None:
    print("\n=== STEP 4: Candidate signals and explicit weights ===")
    print("Strategy weights:", STRATEGY_WEIGHTS)
    _show(combined_signals)

    contributions = portfolio_result["contributions"]
    diagnostics = portfolio_result["diagnostics"]
    targets = portfolio_result["targets"]
    print("\n=== STEP 5: per-factor inverse-vol contributions ===")
    _show(
        contributions.loc[
            :,
            [
                "signal_date",
                "instrument",
                "factor_name",
                "signal",
                "strategy_weight",
                "weighted_signal_contribution",
                "vol_forecast",
                "inverse_vol_risk",
                "strategy_risk_contribution",
            ],
        ]
    )

    print("\nRB manual aggregation check:")
    rb = contributions.loc[contributions["instrument"].eq("RB")]
    weighted_signal = rb["weighted_signal_contribution"].sum()
    weighted_risk = rb["strategy_risk_contribution"].sum()
    print(
        f"aggregated_signal = sum(weight * signal) = {weighted_signal:.8f}"
    )
    print(
        "aggregated_risk = sum(weight * signal / vol) "
        f"= {weighted_risk:.8f}"
    )

    print("\n=== STEP 6: constraints, sizing and target quantity ===")
    _show(
        diagnostics.loc[
            :,
            [
                "signal_date",
                "target_effective_date",
                "instrument",
                "aggregated_signal",
                "vol_forecast",
                "aggregated_risk",
                "post_instrument_cap",
                "post_sector_cap",
                "post_chain_cap",
                "portfolio_scale_factor",
                "post_scale_exposure",
                "order_book_id",
                "trade_price",
                "contract_multiplier",
                "pre_margin_quantity_float",
                "margin_scale",
                "target_quantity",
            ],
        ]
    )
    print("\nTarget Position interface:")
    _show(targets)


def _run_and_print_formal(
    portfolio_result: dict[str, object],
    portfolio_config: PortfolioConfig,
) -> None:
    if not BUNDLE_PATH.is_dir():
        raise FileNotFoundError(f"RQAlpha sample bundle not found: {BUNDLE_PATH}")

    targets = portfolio_result["targets"]
    target_dates = pd.DatetimeIndex(targets["trading_date"].unique()).sort_values()
    start_date = target_dates.min()
    end_date = FORMAL_END
    print("\n=== STEP 7: RQAlpha Plus formal bridge ===")
    with tempfile.TemporaryDirectory(prefix="cta_three_factor_demo_") as temp_root:
        formal = run_formal_backtest(
            targets,
            FormalBacktestConfig(
                start_date=start_date.date().isoformat(),
                end_date=end_date.date().isoformat(),
                initial_capital=portfolio_config.initial_capital,
                data_bundle_path=BUNDLE_PATH,
                output_root=Path(temp_root),
                frequency="1d",
                matching_type="current_bar",
                volume_limit=True,
                volume_percent=0.25,
                price_limit=True,
                inactive_limit=True,
                slippage_model="PriceRatioSlippage",
                slippage_value=0.0,
                futures_time_series_trading_parameters=True,
                futures_settlement_price_type="close",
                strategy_name="three_factor_teaching_demo",
            ),
            rebalance_dates=portfolio_result["rebalance_dates"],
        )
        print("Target executions:")
        _show(formal["target_executions"])
        print("Orders:")
        _show(formal["orders"])
        print("Trades:")
        _show(formal["trades"])
        print("Final portfolio row:")
        _show(formal["portfolio"].tail(1))
        print("Final futures positions:")
        _show(formal["future_positions"].tail(10))
        print("Formal result source:", formal["metadata"]["formal_result_source_of_truth"])
        print("Formal run fingerprint:", formal["metadata"]["run_fingerprint"])


def _show(frame: pd.DataFrame) -> None:
    if frame.empty:
        print("<empty>")
        return
    with pd.option_context(
        "display.max_columns",
        None,
        "display.width",
        220,
        "display.max_colwidth",
        40,
    ):
        print(frame.to_string(index=False))


if __name__ == "__main__":
    raise SystemExit(main())
