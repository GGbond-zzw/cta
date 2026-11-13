"""Recompute the eight current factors on the screened fixed 30-product pool."""

from __future__ import annotations

import sys

import argparse
import json
from pathlib import Path

import pandas as pd

from china_cta.data.contracts import get_research_universe, get_signal_continuous_price
from china_cta.data.fixed_universe import DEFAULT_FIXED_POOL_FILE, load_fixed_product_pool
from china_cta.data.rqdata_adapter import RQDataAdapter, RQDataConfig
from china_cta.factors.classification import classification, result_root
from china_cta.factors.unqualified.aggregate_oi import compute_aggregate_oi_growth_factor
from china_cta.factors.unqualified.basis_momentum import compute_basis_momentum_factor
from china_cta.factors.unqualified.consistent_trend import compute_consistent_trend_factor
from china_cta.factors.qualified.fixed_maturity_carry import calculate_curve_carry, compute_curve_carry_factor
from china_cta.factors.qualified.historical_skewness import compute_historical_skewness_factor
from china_cta.factors.unqualified.historical_skewness_cs_rank import compute_historical_skewness_factor_cs_rank
from china_cta.factors.unqualified.multi_horizon_trend import compute_multi_horizon_trend_factor
from china_cta.factors.qualified.oi_participation_trend import compute_oi_participation_trend_factor
from china_cta.research.fast_backtest import run_fast_research_backtest, save_research_run
sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling research script
from basis_momentum_test import CacheOnlyRQDataAdapter, DEFAULT_START, DEFAULT_END, load_contract_history


# Original upstream walkthrough (6c91077): one-session lag, 1bp turnover
# sensitivity cost, with the engine's default 252-period annualization.
COST_RATE = 0.0001
EXECUTION_LAG = 1

# One canonical result per current definition, not a filesystem glob.
RUNS = (
    ("aggregate_oi_growth_20d_2016_2025_v1", "aggregate_oi"),
    ("basis_momentum_252d_2016_2025_v1", "basis_momentum"),
    ("fixed_maturity_carry_90_180d_2016_2025_v1", "fixed_carry"),
    ("historical_skewness_252d_2016_2025_v1", "skewness"),
    ("historical_skewness_252d_cs_rank_2016_2025_v1", "skewness_cs"),
    ("multi_trend_20_60_120_252d_2016_2025_v1", "multi_trend"),
    ("oi_participation_trend_60d_2016_2025_v2", "oi_trend"),
    ("slow_vote_trend_63_126_252d_5r_2016_2025_v1", "slow_vote"),
)

FACTOR_NAMES = {
    "aggregate_oi": "aggregate_oi_growth_20d",
    "basis_momentum": "basis_momentum_252d",
    "fixed_carry": "fixed_maturity_carry_90_180d",
    "skewness": "historical_skewness_252d",
    "skewness_cs": "historical_skewness_252d_cs_rank",
    "multi_trend": "multi_trend_20_60_120_252d",
    "oi_trend": "oi_participation_trend_60d",
    "slow_vote": "consistent_trend_63_126_252d_5r",
}


def build_factors(prices, snapshots, universe):
    """Build the eight current definitions."""
    builders = {
        "aggregate_oi": lambda: compute_aggregate_oi_growth_factor(
            snapshots, universe, lookback=20, minimum_contracts=2, signal_scale=.20),
        "basis_momentum": lambda: compute_basis_momentum_factor(
            snapshots, universe, lookback=252, min_days_to_maturity=60, signal_scale=.20),
        "slow_vote": lambda: compute_consistent_trend_factor(prices, universe, signal_scale=.50),
        "fixed_carry": lambda: compute_curve_carry_factor(snapshots, universe),
        "skewness": lambda: compute_historical_skewness_factor(
            prices, universe, lookback=252, signal_scale=1.0),
        "skewness_cs": lambda: compute_historical_skewness_factor_cs_rank(
            prices, universe, lookback=252),
        "multi_trend": lambda: compute_multi_horizon_trend_factor(
            prices, universe, horizons=(20, 60, 120, 252), volatility_lookback=60, signal_scale=1.0),
        "oi_trend": lambda: compute_oi_participation_trend_factor(prices, snapshots, universe, signal_scale=.50),
    }
    for key, builder in builders.items():
        print(f"Building {key}", flush=True)
        yield key, builder()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--products-file", type=Path, default=DEFAULT_FIXED_POOL_FILE)
    parser.add_argument("--cache-only", action="store_true")
    parser.add_argument("--overwrite", action="store_true", help="Replace the eight current factor results")
    args = parser.parse_args()
    pool = load_fixed_product_pool(args.products_file)
    products = list(pool.products)
    if not args.overwrite and any(
        (result_root(FACTOR_NAMES[key]) / name).exists() for name, key in RUNS
    ):
        parser.error("Existing results require --overwrite")
    adapter_type = CacheOnlyRQDataAdapter if args.cache_only else RQDataAdapter
    adapter = adapter_type(RQDataConfig.from_environment())
    print(f"Pool: {pool.holding_month}, {len(products)} products: {','.join(products)}", flush=True)
    print("Loading shared continuous closes", flush=True)
    prices = get_signal_continuous_price(
        adapter, products, DEFAULT_START, DEFAULT_END, fields=["close", "volume", "open_interest"],
        adjust_type="pre", adjust_method="prev_close_ratio")
    calendar = adapter.get_trading_calendar(DEFAULT_START, DEFAULT_END)
    print("Loading real contract closes and OI", flush=True)
    snapshots = load_contract_history(adapter, products, calendar, DEFAULT_START, DEFAULT_END,
                                      include_open_interest=True)
    print("Loading daily point-in-time eligibility", flush=True)
    universe_frames = []
    for index, day in enumerate(calendar, start=1):
        universe_frames.append(get_research_universe(
            adapter, day, min_listing_history_days=60, min_volume=1000, min_open_interest=1000))
        if index % 250 == 0 or index == len(calendar):
            print(f"Eligibility {index}/{len(calendar)} trading days", flush=True)
    universe = pd.concat(universe_frames, ignore_index=True)
    universe = universe.loc[universe["instrument"].isin(products)].reset_index(drop=True)
    if not set(prices["underlying_symbol"]) <= set(products):
        raise RuntimeError("Research prices contain products outside the fixed pool")
    diagnostics = calculate_curve_carry(snapshots)
    factors = dict(build_factors(prices, snapshots, universe))
    if any(not factor["raw_factor"].notna().any() for factor in factors.values()):
        raise RuntimeError("At least one factor has zero valid observations; no results replaced")
    settings = {
        "products": products, "fixed_pool_source": str(pool.source_file),
        "fixed_pool_holding_month": pool.holding_month, "fixed_pool_applied_to_entire_backtest": True,
        "ex_post_selection_bias": True, "min_listing_history_days": 60,
        "min_volume": 1000, "min_open_interest": 1000,
        "requested_start": DEFAULT_START, "requested_end": DEFAULT_END, "cache_only": args.cache_only,
    }
    results = {}
    for key, factor in factors.items():
        print(f"Backtesting {key}", flush=True)
        results[key] = run_fast_research_backtest(
            factor, prices, universe, execution_lag=EXECUTION_LAG, cost_rate=COST_RATE)
    # No legacy result is changed until all factors have completed successfully.
    summary = []
    for name, key in RUNS:
        factor, result = factors[key], results[key]
        parameters = {key: value for key, value in factor.attrs.items()
                      if key not in {"signal_scale", "information_date", "signal_available_at",
                                     "earliest_trade_at", "signal_is_position"}}
        parameters["result_directory"] = name
        save_research_run(result, name, factor_parameters=parameters,
                          signal_normalization_parameters={"signal_scale": factor.attrs.get("signal_scale", 1.0)},
                          universe_settings=settings, overwrite=args.overwrite,
                          output_root=result_root(FACTOR_NAMES[key]))
        output = result_root(FACTOR_NAMES[key]) / name
        if key == "fixed_carry":
            diagnostics.to_csv(output / "fixed_maturity_diagnostics.csv", index=False)
            coverage = diagnostics.groupby("instrument").agg(
                curve_days=("raw_factor", "size"), valid_days=("raw_factor", "count"))
            coverage["coverage"] = coverage["valid_days"] / coverage["curve_days"]
            coverage.to_csv(output / "fixed_maturity_coverage.csv")
        row = {"run": name, "factor_name": result["metadata"]["factor_name"],
               "classification": classification(FACTOR_NAMES[key]),
               "status": "completed",
               "result_path": f"results/{classification(FACTOR_NAMES[key])}/{name}",
               **result["overall"].iloc[0].to_dict()}
        summary.append(row)
        print(f"Replaced {name}: Sharpe={row['sharpe']:.3f}", flush=True)
    pd.DataFrame(summary).to_csv("results/all_factors_fixed30_summary.csv", index=False)
    Path("results/all_factors_fixed30_manifest.json").write_text(json.dumps({
        "universe": settings, "runs": [name for name, _ in RUNS],
        "result_layout": {
            "qualified": "results/qualified",
            "unqualified": "results/unqualified",
        },
        "classification": {
            name: classification(FACTOR_NAMES[key]) for name, key in RUNS
        },
        "unique_factor_definitions": len(factors), "all_completed": True,
        "backtest_standard": {
            "upstream_commit": "6c9107741d54ba0126b97e4a06370b10b7686b60",
            "source": "scripts/walkthrough_three_factor_pipeline.py",
            "cost_rate": COST_RATE, "execution_lag": EXECUTION_LAG,
            "annualization_factor": 252,
            "engine_calculation": "unchanged_from_upstream",
        },
        "note": "One canonical result directory per current factor definition.",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("All eight results replaced successfully.", flush=True)


if __name__ == "__main__":
    main()
