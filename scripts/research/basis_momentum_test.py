"""Run a real-data basis-momentum research diagnostic.

The first run downloads and caches unadjusted real-contract close data.
Basis-momentum is then passed through the existing Phase 3 factor schema and
Phase 4 one-session-lag fast backtest.
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
from china_cta.factors.unqualified.basis_momentum import compute_basis_momentum_factor
from china_cta.research.fast_backtest import (
    run_fast_research_backtest,
    save_research_run,
)


DEFAULT_START = "2016-01-01"
DEFAULT_END = "2026-01-01"
DEFAULT_LOOKBACK = 252
DEFAULT_MIN_DAYS_TO_MATURITY = 60
DEFAULT_SIGNAL_SCALE = 0.20
DEFAULT_COST_RATE = 0.0001
BAR_QUERY_CHUNK_SIZE = 50


class CacheOnlyRQDataAdapter(RQDataAdapter):
    """Read verified project cache entries without contacting RQData."""

    def connect(self, *, lazy: bool = True, force: bool = False) -> None:
        raise RuntimeError(
            "Required RQData cache entry is missing; rerun without --cache-only"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--products-file", type=Path, default=DEFAULT_FIXED_POOL_FILE)
    parser.add_argument("--lookback", type=int, default=DEFAULT_LOOKBACK)
    parser.add_argument(
        "--min-days-to-maturity",
        type=int,
        default=DEFAULT_MIN_DAYS_TO_MATURITY,
    )
    parser.add_argument("--signal-scale", type=float, default=DEFAULT_SIGNAL_SCALE)
    parser.add_argument("--cost-rate", type=float, default=DEFAULT_COST_RATE)
    parser.add_argument("--cache-only", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    fixed_pool = load_fixed_product_pool(args.products_file)
    products = list(fixed_pool.products)
    adapter_type = CacheOnlyRQDataAdapter if args.cache_only else RQDataAdapter
    adapter = adapter_type(RQDataConfig.from_environment())
    if not args.cache_only:
        adapter.connect()

    print("[1/5] Loading trading calendar and real-contract closes", flush=True)
    calendar = adapter.get_trading_calendar(args.start, args.end)
    snapshots = load_contract_history(
        adapter,
        products,
        calendar,
        args.start,
        args.end,
    )

    print("[2/5] Loading point-in-time eligible universe", flush=True)
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

    print("[3/5] Computing first-minus-second nearby momentum", flush=True)
    factor = compute_basis_momentum_factor(
        snapshots,
        universe,
        lookback=args.lookback,
        min_days_to_maturity=args.min_days_to_maturity,
        signal_scale=args.signal_scale,
    )
    valid_count = int(factor["raw_factor"].notna().sum())
    print(f"Valid factor observations: {valid_count:,}", flush=True)
    if valid_count == 0:
        raise RuntimeError(
            "No valid factor observations. Use a longer date range, reduce the "
            "lookback/expiry buffer, or inspect close coverage."
        )

    print("[4/5] Loading research prices and running one-session-lag backtest", flush=True)
    prices = get_signal_continuous_price(
        adapter,
        products,
        args.start,
        args.end,
        fields=["close", "volume", "open_interest"],
        adjust_type="pre",
        adjust_method="prev_close_ratio",
    )
    result = run_fast_research_backtest(
        factor,
        prices,
        universe,
        execution_lag=1,
        cost_rate=args.cost_rate,
    )
    print("Overall:")
    print(result["overall"].to_string(index=False))
    print("By year:")
    print(result["by_year"].to_string(index=False))
    print("By instrument:")
    print(result["by_instrument"].to_string(index=False))

    print("[5/5] Saving reproducible research output", flush=True)
    # END follows the existing research scripts' half-open reporting
    # convention: 2026-01-01 means the completed 2016-2025 sample.
    sample_end_year = (pd.Timestamp(args.end) - pd.Timedelta(days=1)).year
    run_name = (
        f"basis_momentum_{args.lookback}d_"
        f"{pd.Timestamp(args.start).year}_{sample_end_year}_"
        f"{fixed_pool.run_suffix}_close"
    )
    output_dir = result_root(f"basis_momentum_{args.lookback}d") / run_name
    if output_dir.exists() and not args.overwrite:
        print(f"Existing result preserved: {output_dir}")
        return
    paths = save_research_run(
        result,
        run_name,
        overwrite=args.overwrite,
        output_root=result_root(f"basis_momentum_{args.lookback}d"),
        factor_parameters={
            "lookback": args.lookback,
            "min_days_to_maturity": args.min_days_to_maturity,
            "definition": (
                "compound_return(first_nearby_strategy, lookback) - "
                "compound_return(second_nearby_strategy, lookback)"
            ),
            "price_field": "close",
            "return_construction": (
                "previous_close_selection_priced_on_same_contract_next_observation"
            ),
        },
        signal_normalization_parameters={"signal_scale": args.signal_scale},
        universe_settings={
            "products": products,
            "fixed_pool_source": str(fixed_pool.source_file),
            "fixed_pool_holding_month": fixed_pool.holding_month,
            "fixed_pool_applied_to_entire_backtest": True,
            "ex_post_selection_bias": True,
            "min_listing_history_days": 60,
            "min_volume": 1000,
            "min_open_interest": 1000,
            "requested_start": args.start,
            "requested_end": args.end,
            "cache_only": args.cache_only,
        },
    )
    print(f"Saved: {paths['config']}")


def load_contract_history(
    adapter: RQDataAdapter,
    products: list[str],
    calendar: pd.DatetimeIndex,
    start_date: str,
    end_date: str,
    *,
    include_open_interest: bool = False,
) -> pd.DataFrame:
    """Build complete point-in-time curves without skipping missing prices."""

    master = adapter.get_future_instruments().copy()
    master = master.loc[
        master["underlying_symbol"].isin(products)
        & master["listed_date"].notna()
        & master["maturity_date"].notna()
        & master["listed_date"].le(pd.Timestamp(end_date))
        & master["maturity_date"].ge(pd.Timestamp(start_date)),
        [
            "order_book_id",
            "underlying_symbol",
            "listed_date",
            "de_listed_date",
            "maturity_date",
        ],
    ].copy()
    if master.empty:
        raise RuntimeError("No matching real futures contracts were returned by RQData")

    bars: list[pd.DataFrame] = []
    open_interest_bars: list[pd.DataFrame] = []
    contract_ids = master["order_book_id"].astype(str).tolist()
    for offset in range(0, len(contract_ids), BAR_QUERY_CHUNK_SIZE):
        chunk = contract_ids[offset : offset + BAR_QUERY_CHUNK_SIZE]
        bars.append(
            adapter.get_bars(
                chunk,
                start_date,
                end_date,
                fields=("close",),
            )
        )
        if include_open_interest:
            open_interest_bars.append(
                adapter.get_bars(
                    chunk,
                    start_date,
                    end_date,
                    fields=("open_interest",),
                )
            )
    closes = pd.concat(bars, ignore_index=True).rename(
        columns={"close": "price"}
    )
    if include_open_interest:
        open_interest = pd.concat(open_interest_bars, ignore_index=True)
        closes = closes.merge(
            open_interest,
            on=["trading_date", "order_book_id"],
            how="outer",
            validate="one_to_one",
        )

    dates = pd.DataFrame({"trading_date": calendar})
    dates["_join_key"] = 1
    master["_join_key"] = 1
    active = dates.merge(master, on="_join_key", how="inner").drop(
        columns="_join_key"
    )
    active = active.loc[
        active["listed_date"].le(active["trading_date"])
        & active["maturity_date"].ge(active["trading_date"])
        & (
            active["de_listed_date"].isna()
            | active["de_listed_date"].ge(active["trading_date"])
        )
    ].copy()
    active = active.merge(
        closes,
        on=["trading_date", "order_book_id"],
        how="left",
        validate="one_to_one",
    )
    active["days_to_maturity"] = (
        active["maturity_date"] - active["trading_date"]
    ).dt.days.astype("Int64")
    active["price_field"] = "close"
    output_columns = [
        "trading_date",
        "underlying_symbol",
        "order_book_id",
        "maturity_date",
        "days_to_maturity",
        "price",
        "price_field",
    ]
    if include_open_interest:
        output_columns.append("open_interest")
    return active.loc[:, output_columns].sort_values(
        ["underlying_symbol", "trading_date", "maturity_date", "order_book_id"]
    ).reset_index(drop=True)


if __name__ == "__main__":
    main()
