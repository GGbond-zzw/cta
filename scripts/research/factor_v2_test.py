"""Run the redesigned three-factor research suite on the 2016-2025 sample."""

from __future__ import annotations

import sys

import argparse
from pathlib import Path

import pandas as pd

from china_cta.data.contracts import (
    get_research_universe,
    get_signal_continuous_price,
)
from china_cta.data.rqdata_adapter import RQDataAdapter, RQDataConfig
from china_cta.data.fixed_universe import DEFAULT_FIXED_POOL_FILE, load_fixed_product_pool
from china_cta.factors.classification import result_root
from china_cta.factors.unqualified.aggregate_oi import compute_aggregate_oi_growth_factor
from china_cta.factors.qualified.fixed_maturity_carry import compute_curve_carry_factor
from china_cta.factors.unqualified.multi_horizon_trend import (
    compute_multi_horizon_trend_factor,
)
from china_cta.research.fast_backtest import (
    run_fast_research_backtest,
    save_research_run,
)
sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling research script
from basis_momentum_test import (
    CacheOnlyRQDataAdapter,
    DEFAULT_END,
    DEFAULT_START,
    load_contract_history,
)


COST_RATE = 0.0001

FACTOR_NAMES = {
    "multi_trend_20_60_120_252d_2016_2025_v1": "multi_trend_20_60_120_252d",
    "fixed_maturity_carry_90_180d_2016_2025_v1": "fixed_maturity_carry_90_180d",
    "aggregate_oi_growth_20d_2016_2025_v1": "aggregate_oi_growth_20d",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-only", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--products-file", type=Path, default=DEFAULT_FIXED_POOL_FILE)
    args = parser.parse_args()
    fixed_pool = load_fixed_product_pool(args.products_file)
    products = list(fixed_pool.products)
    adapter_type = CacheOnlyRQDataAdapter if args.cache_only else RQDataAdapter
    adapter = adapter_type(RQDataConfig.from_environment())
    if not args.cache_only:
        adapter.connect()

    print("[1/5] Loading shared 2016-2025 data", flush=True)
    calendar = adapter.get_trading_calendar(DEFAULT_START, DEFAULT_END)
    prices = get_signal_continuous_price(
        adapter,
        products,
        DEFAULT_START,
        DEFAULT_END,
        fields=["close", "volume", "open_interest"],
        adjust_type="pre",
        adjust_method="prev_close_ratio",
    )
    snapshots = load_contract_history(
        adapter,
        products,
        calendar,
        DEFAULT_START,
        DEFAULT_END,
        include_open_interest=True,
    )
    universe = pd.concat(
        [
            get_research_universe(
                adapter,
                day,
                min_listing_history_days=60,
                min_volume=1000,
                min_open_interest=1000,
            )
            for day in calendar
        ],
        ignore_index=True,
    )
    universe = universe.loc[
        universe["instrument"].isin(products)
    ].reset_index(drop=True)

    print("[2/5] Building robust multi-horizon Trend", flush=True)
    trend = compute_multi_horizon_trend_factor(
        prices,
        universe,
        horizons=(20, 60, 120, 252),
        volatility_lookback=60,
        signal_scale=1.0,
    )
    print("[3/5] Building fixed-maturity 90/180-day Carry", flush=True)
    carry = compute_curve_carry_factor(
        snapshots,
        universe,
        min_days_to_maturity=30,
        near_days=90,
        far_days=180,
        max_gap_days=120,
        signal_scale=0.20,
    )
    print("[4/5] Building aggregate 20-day OI Growth", flush=True)
    oi_growth = compute_aggregate_oi_growth_factor(
        snapshots,
        universe,
        lookback=20,
        minimum_contracts=2,
        signal_scale=0.20,
    )

    print("[5/5] Running the unchanged one-session-lag backtest", flush=True)
    specifications = (
        (
            "multi_trend_20_60_120_252d_2016_2025_v1",
            trend,
            {
                "horizons": [20, 60, 120, 252],
                "volatility_lookback": 60,
                "component_clip": 3.0,
                "definition": "mean_horizon_return_divided_by_horizon_volatility",
            },
            {"signal_scale": 1.0},
        ),
        (
            "fixed_maturity_carry_90_180d_2016_2025_v1",
            carry,
            {
                "min_days_to_maturity": 30,
                "near_days": 90,
                "far_days": 180,
                "max_gap_days": 120,
                "interpolation": "linear_price",
                "maturity_reference": "maturity_date",
                "definition": (
                    "annualized_log_near_fixed_price_minus_log_far_fixed_price"
                ),
            },
            {"signal_scale": 0.20},
        ),
        (
            "aggregate_oi_growth_20d_2016_2025_v1",
            oi_growth,
            {
                "lookback": 20,
                "minimum_contracts": 2,
                "definition": (
                    "total_curve_open_interest_t_over_t_minus_lookback_minus_1"
                ),
            },
            {"signal_scale": 0.20},
        ),
    )
    for run_name, factor, factor_parameters, normalization in specifications:
        factor_name = FACTOR_NAMES[run_name]
        price_suffix = "_close" if run_name.startswith("fixed_maturity_carry_") else ""
        run_name = f"{run_name}_{fixed_pool.run_suffix}{price_suffix}"
        result = run_fast_research_backtest(
            factor,
            prices,
            universe,
            execution_lag=1,
            cost_rate=COST_RATE,
        )
        print(f"\n=== {run_name} ===")
        print(result["overall"].to_string(index=False))
        output_dir = result_root(factor_name) / run_name
        if output_dir.exists() and not args.overwrite:
            print(f"Existing result preserved: {output_dir}")
            continue
        save_research_run(
            result,
            run_name,
            overwrite=args.overwrite,
            factor_parameters=factor_parameters,
            signal_normalization_parameters=normalization,
            output_root=result_root(factor_name),
            universe_settings={
                "products": products,
                "fixed_pool_source": str(fixed_pool.source_file),
                "fixed_pool_holding_month": fixed_pool.holding_month,
                "fixed_pool_applied_to_entire_backtest": True,
                "ex_post_selection_bias": True,
                "min_listing_history_days": 60,
                "min_volume": 1000,
                "min_open_interest": 1000,
                "requested_start": DEFAULT_START,
                "requested_end": DEFAULT_END,
                "cache_only": args.cache_only,
            },
        )
        print(f"Saved: {output_dir}")


if __name__ == "__main__":
    main()
