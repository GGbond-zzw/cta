"""Ten-year research diagnostic for the historical-skewness factor.

This script deliberately reuses the project's existing Phase 2 continuous
research prices, point-in-time universe, Phase 3 factor schema and Phase 4
fast research backtest. It does not add factor-specific data processing.
"""

from __future__ import annotations

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
from china_cta.factors.qualified.historical_skewness import (
    compute_historical_skewness_factor,
)
from china_cta.research.fast_backtest import (
    run_fast_research_backtest,
    save_research_run,
)


START = "2016-01-01"
END = "2026-01-01"
LOOKBACK = 252
SIGNAL_SCALE = 1.0
COST_RATE = 0.0001
RUN_NAME = "historical_skewness_252d_2016_2025_v1"


class CacheOnlyRQDataAdapter(RQDataAdapter):
    """Read verified project cache entries without contacting RQData."""

    def connect(self, *, lazy: bool = True, force: bool = False) -> None:
        raise RuntimeError(
            "Required RQData cache entry is missing; online credentials are needed"
        )


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

    print("[1/4] Loading project research continuous prices", flush=True)
    prices = get_signal_continuous_price(
        adapter,
        products,
        START,
        END,
        # Match the project's existing ten-year cache request exactly. The
        # factor itself consumes only ``close`` through its declared input.
        fields=["close", "volume", "open_interest"],
        adjust_type="pre",
        adjust_method="prev_close_ratio",
    )

    print("[2/4] Loading project point-in-time universe", flush=True)
    calendar = adapter.get_trading_calendar(START, END)
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
    universe = universe.loc[universe["instrument"].isin(products)].reset_index(drop=True)

    print("[3/4] Computing unchanged 252-return skewness definition", flush=True)
    factor = compute_historical_skewness_factor(
        prices,
        universe,
        lookback=LOOKBACK,
        signal_scale=SIGNAL_SCALE,
    )

    print("[4/4] Running the existing one-session-lag diagnostic", flush=True)
    result = run_fast_research_backtest(
        factor,
        prices,
        universe,
        execution_lag=1,
        cost_rate=COST_RATE,
    )
    print("Overall:")
    print(result["overall"].to_string(index=False))
    print("By year:")
    print(result["by_year"].to_string(index=False))
    print("By instrument:")
    print(result["by_instrument"].to_string(index=False))

    run_name = f"{RUN_NAME}_{fixed_pool.run_suffix}"
    factor_name = f"historical_skewness_{LOOKBACK}d"
    output_dir = result_root(factor_name) / run_name
    if output_dir.exists() and not args.overwrite:
        print(f"Existing result preserved: {output_dir}")
        return
    paths = save_research_run(
        result,
        run_name,
        overwrite=args.overwrite,
        output_root=result_root(factor_name),
        factor_parameters={
            "lookback": LOOKBACK,
            "definition": "-rolling_skewness(close_to_close_return, lookback)",
        },
        signal_normalization_parameters={"signal_scale": SIGNAL_SCALE},
        universe_settings={
            "products": products,
            "fixed_pool_source": str(fixed_pool.source_file),
            "fixed_pool_holding_month": fixed_pool.holding_month,
            "fixed_pool_applied_to_entire_backtest": True,
            "ex_post_selection_bias": True,
            "min_listing_history_days": 60,
            "min_volume": 1000,
            "min_open_interest": 1000,
            "requested_start": START,
            "requested_end": END,
            "cache_only": args.cache_only,
        },
    )
    print(f"Saved: {paths['config']}")


if __name__ == "__main__":
    main()
