"""Ten-year diagnostic for eligible cross-sectional skewness ranks.

The script changes only the Phase 3 signal transformation. It reuses the
same Phase 2 research prices, point-in-time universe and Phase 4 research
backtest as the absolute historical-skewness baseline.
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
from china_cta.factors.unqualified.historical_skewness_cs_rank import (
    compute_historical_skewness_factor_cs_rank,
)
from china_cta.research.fast_backtest import (
    run_fast_research_backtest,
    save_research_run,
)


START = "2016-01-01"
END = "2026-01-01"
LOOKBACK = 252
COST_RATE = 0.0001
RUN_NAME = "historical_skewness_252d_cs_rank_2016_2025_v1"


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

    print("[1/4] Loading unchanged project research prices", flush=True)
    prices = get_signal_continuous_price(
        adapter,
        products,
        START,
        END,
        fields=["close", "volume", "open_interest"],
        adjust_type="pre",
        adjust_method="prev_close_ratio",
    )

    print("[2/4] Loading unchanged project point-in-time universe", flush=True)
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

    print("[3/4] Ranking -252-day skewness within eligible daily peers", flush=True)
    factor = compute_historical_skewness_factor_cs_rank(
        prices,
        universe,
        lookback=LOOKBACK,
    )

    print("[4/4] Running unchanged one-session-lag diagnostic", flush=True)
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
    factor_name = f"historical_skewness_{LOOKBACK}d_cs_rank"
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
            "definition": (
                "per_date_eligible_cross_sectional_rank_of("
                "-rolling_skewness(close_to_close_return, lookback))"
            ),
            "rank_tie_method": "average",
            "minimum_valid_peers": 2,
        },
        signal_normalization_parameters={
            "signal_scale": 1.0,
            "mapping": "eligible_cross_sectional_rank_to_minus1_plus1",
        },
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
