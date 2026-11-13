"""Backtest the redesigned trend and OI-conditioned trend on 2016-2025."""

from __future__ import annotations

import sys

import argparse
from pathlib import Path

import pandas as pd

from china_cta.data.contracts import get_research_universe, get_signal_continuous_price
from china_cta.data.rqdata_adapter import RQDataAdapter, RQDataConfig
from china_cta.data.fixed_universe import DEFAULT_FIXED_POOL_FILE, load_fixed_product_pool
from china_cta.factors.classification import result_root
from china_cta.factors.unqualified.consistent_trend import compute_consistent_trend_factor
from china_cta.factors.qualified.oi_participation_trend import (
    compute_oi_participation_trend_factor,
)
from china_cta.research.fast_backtest import run_fast_research_backtest, save_research_run
sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling research script
from basis_momentum_test import (
    CacheOnlyRQDataAdapter,
    DEFAULT_END,
    DEFAULT_START,
    load_contract_history,
)


COST_RATE = 0.0001

FACTOR_NAMES = {
    "slow_vote_trend_63_126_252d_5r_2016_2025_v1": "consistent_trend_63_126_252d_5r",
    "oi_participation_trend_60d_2016_2025_v2": "oi_participation_trend_60d",
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

    print("[1/4] Loading shared 2016-2025 data", flush=True)
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
    universe = universe.loc[universe["instrument"].isin(products)].reset_index(
        drop=True
    )

    print("[2/4] Building slow direction-voting Trend", flush=True)
    trend = compute_consistent_trend_factor(
        prices,
        universe,
        horizons=(63, 126, 252),
        smoothing_span=10,
        deadband=0.05,
        rebalance_every=5,
        volatility_halflife=20,
        target_annualized_volatility=0.15,
        signal_scale=0.50,
    )
    print("[3/4] Building OI-participation Trend", flush=True)
    oi_trend = compute_oi_participation_trend_factor(
        prices,
        snapshots,
        universe,
        trend_horizons=(63, 126, 252),
        trend_smoothing_span=10,
        trend_deadband=0.05,
        trend_volatility_halflife=20,
        trend_target_annualized_volatility=0.15,
        oi_growth_lookback=60,
        oi_smoothing_span=10,
        oi_normalization_lookback=252,
        minimum_oi_observations=126,
        minimum_contracts=2,
        rebalance_every=5,
        signal_scale=0.50,
    )

    print("[4/4] Running the unchanged one-session-lag backtest", flush=True)
    specifications = (
        (
            "slow_vote_trend_63_126_252d_5r_2016_2025_v1",
            trend,
            {
                "horizons": [63, 126, 252],
                "smoothing_span": 10,
                "deadband": 0.05,
                "rebalance_every": 5,
                "volatility_halflife": 20,
                "target_annualized_volatility": 0.15,
                "definition": "mean_horizon_sign_with_downside_only_vol_scaling",
            },
        ),
        (
            "oi_participation_trend_60d_2016_2025_v2",
            oi_trend,
            {
                "trend_horizons": [63, 126, 252],
                "trend_smoothing_span": 10,
                "trend_deadband": 0.05,
                "trend_volatility_halflife": 20,
                "trend_target_annualized_volatility": 0.15,
                "oi_growth_lookback": 60,
                "oi_smoothing_span": 10,
                "oi_normalization_lookback": 252,
                "minimum_oi_observations": 126,
                "minimum_contracts": 2,
                "rebalance_every": 5,
                "definition": "consistent_trend_times_bounded_oi_participation",
            },
        ),
    )
    for run_name, factor, factor_parameters in specifications:
        factor_name = FACTOR_NAMES[run_name]
        run_name = f"{run_name}_{fixed_pool.run_suffix}"
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
            signal_normalization_parameters={"signal_scale": 0.50},
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
