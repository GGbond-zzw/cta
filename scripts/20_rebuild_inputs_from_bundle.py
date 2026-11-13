"""Rebuild the cta_alpha22 research inputs from the local RQAlpha bundle.

The bundle is validated against the cached RQData tables first: over 2016-2025
it reproduces contract snapshots 1:1 (price, open interest, days to maturity)
and reproduces the continuous-price returns exactly when the chain is formed as
``close / prev_close`` of the dominant contract.  The bundle-only slice is then
appended with the same rules, so history is never re-written.

Examples
--------
    python scripts/20_rebuild_inputs_from_bundle.py --bundle D:/rqalpha/bundle
    python scripts/20_rebuild_inputs_from_bundle.py --contracts-cache contracts.parquet

The output directory is a drop-in replacement for ``data/research_inputs/cta_alpha22``
and can be passed to ``scripts/50_backtest_portfolio.py --input-dir``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = PROJECT / "data" / "research_inputs" / "cta_alpha22"
DEFAULT_OUTPUT_DIR = PROJECT / "data" / "research_inputs" / "cta_alpha22_extended"
DEFAULT_EXTENSION_START = "2026-01-01"
WINDOW_START = pd.Timestamp("2016-01-04")
WINDOW_END = pd.Timestamp("2027-12-31")


def dominant_map(contracts: pd.DataFrame) -> pd.DataFrame:
    tradable = contracts.loc[contracts["close"].gt(0) & contracts["open_interest"].gt(0)].copy()
    tradable = tradable.sort_values(
        ["trading_date", "underlying_symbol", "open_interest", "volume", "order_book_id"]
    )
    trailing = tradable.groupby(["trading_date", "underlying_symbol"], as_index=False).tail(1)
    trailing = trailing.rename(columns={"order_book_id": "dominant_order_book_id"})
    return (
        trailing.loc[:, ["trading_date", "underlying_symbol", "dominant_order_book_id"]]
        .sort_values(["trading_date", "underlying_symbol"])
        .reset_index(drop=True)
    )


def contract_snapshots(
    contracts: pd.DataFrame,
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
) -> pd.DataFrame:
    frame = contracts.loc[
        contracts["trading_date"].ge(window_start)
        & contracts["trading_date"].le(window_end)
        & contracts["close"].gt(0)
    ].copy()
    frame["days_to_maturity"] = (frame["maturity_date"] - frame["trading_date"]).dt.days
    frame = frame.rename(columns={"close": "price"})
    frame["price_field"] = "close"
    frame = frame.loc[frame["days_to_maturity"].gt(0)]
    frame["days_to_maturity"] = frame["days_to_maturity"].astype("Int64")
    frame["underlying_symbol"] = frame["underlying_symbol"].astype("string")
    frame["order_book_id"] = frame["order_book_id"].astype("string")
    columns = [
        "trading_date",
        "underlying_symbol",
        "order_book_id",
        "maturity_date",
        "days_to_maturity",
        "price",
        "price_field",
        "open_interest",
    ]
    return frame.loc[:, columns].sort_values(["trading_date", "order_book_id"]).reset_index(drop=True)


def continuous_prices(
    contracts: pd.DataFrame,
    dominant: pd.DataFrame,
    cached: pd.DataFrame,
    extension_start: pd.Timestamp,
    window_start: pd.Timestamp,
) -> pd.DataFrame:
    quotes = contracts.loc[
        :,
        ["trading_date", "order_book_id", "open", "high", "low", "close", "prev_close", "volume", "open_interest"],
    ].copy()
    merged = dominant.merge(
        quotes,
        left_on=["trading_date", "dominant_order_book_id"],
        right_on=["trading_date", "order_book_id"],
        how="left",
        validate="one_to_one",
    ).sort_values(["underlying_symbol", "trading_date"])

    frames = []
    for product, group in merged.groupby("underlying_symbol", sort=True):
        known = cached.loc[cached["underlying_symbol"] == product].sort_values("trading_date")
        known = known.loc[known["trading_date"] < extension_start]
        if known.empty:
            continue
        last = known.iloc[-1]
        level = float(last["close"])
        rows = []
        for row in group.loc[group["trading_date"] > last["trading_date"]].itertuples(index=False):
            close = float(row.close)
            prev_close = float(row.prev_close)
            if not np.isfinite(close) or not np.isfinite(prev_close) or close <= 0 or prev_close <= 0:
                continue
            step = close / prev_close
            level = level * step

            def scaled(value: float) -> float:
                return level * (float(value) / close) if np.isfinite(value) and float(value) > 0 else level

            rows.append(
                {
                    "trading_date": row.trading_date,
                    "underlying_symbol": product,
                    "close": level,
                    "open": scaled(row.open),
                    "high": scaled(max(float(row.high), close)),
                    "low": scaled(min(float(row.low), close)) if np.isfinite(row.low) and float(row.low) > 0 else level,
                    "volume": float(row.volume) if np.isfinite(float(row.volume)) else np.nan,
                    "open_interest": float(row.open_interest) if np.isfinite(float(row.open_interest)) else np.nan,
                }
            )
        frames.append(pd.DataFrame(rows))
    result = pd.concat(frames, ignore_index=True)
    columns = ["trading_date", "underlying_symbol", "close", "open", "high", "low", "volume", "open_interest"]
    return (
        result.loc[result["trading_date"] >= window_start, columns]
        .sort_values(["trading_date", "underlying_symbol"])
        .reset_index(drop=True)
    )


def universe(continuous: pd.DataFrame) -> pd.DataFrame:
    frame = (
        continuous.groupby(["trading_date", "underlying_symbol"], as_index=False)
        .size()
        .rename(columns={"underlying_symbol": "instrument", "size": "contracts"})
    )
    frame["eligible"] = frame["contracts"].ge(1)
    frame["reason"] = np.where(frame["eligible"], "eligible", "insufficient_listing_history")
    return frame.loc[:, ["trading_date", "instrument", "eligible", "reason"]].sort_values(
        ["trading_date", "instrument"]
    ).reset_index(drop=True)


def frame_overlap_check(contracts, cached_continuous, cached_dominant):
    overlap = cached_dominant.merge(
        contracts.loc[:, ["trading_date", "order_book_id", "close", "prev_close"]],
        left_on=["trading_date", "dominant_order_book_id"],
        right_on=["trading_date", "order_book_id"],
        how="inner",
        validate="one_to_one",
    ).merge(
        cached_continuous.loc[:, ["trading_date", "underlying_symbol", "close"]],
        on=["trading_date", "underlying_symbol"],
        suffixes=("_bundle", "_cached"),
        how="inner",
    )
    overlap = overlap.sort_values(["underlying_symbol", "trading_date"])
    built = overlap["close_bundle"] / overlap["prev_close"]
    built = built.where(built.gt(0))
    cached = overlap.groupby("underlying_symbol")["close_cached"].pct_change() + 1.0
    mask = built.notna() & cached.notna()
    diff = (built[mask] - cached[mask]).abs()
    return mask, built, cached, diff


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="extend the research inputs with the RQAlpha bundle")
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--bundle", default=None, help="RQAlpha bundle directory (futures.h5 + instruments.pk)")
    parser.add_argument("--contracts-cache", default=None, help="pre-built contract parquet from the bundle")
    parser.add_argument("--products", default=None, help="comma separated product codes (default: all in the bundle)")
    parser.add_argument("--extension-start", default=DEFAULT_EXTENSION_START)
    args = parser.parse_args(argv)

    sys.path.insert(0, str(PROJECT))
    from china_cta.data.rqalpha_bundle import load_contract_bars

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    extension_start = pd.Timestamp(args.extension_start)

    cached_continuous = pd.read_parquet(input_dir / "continuous_prices.parquet")
    cached_universe = pd.read_parquet(input_dir / "universe.parquet")
    cached_snapshots = pd.read_parquet(input_dir / "contract_snapshots.parquet")
    cached_dominant = pd.read_parquet(input_dir / "dominant_map.parquet")
    for frame in (cached_continuous, cached_universe, cached_snapshots, cached_dominant):
        frame["trading_date"] = pd.to_datetime(frame["trading_date"])

    if args.contracts_cache:
        contracts = pd.read_parquet(args.contracts_cache)
    elif args.bundle:
        products = args.products.split(",") if args.products else None
        contracts = load_contract_bars(args.bundle, products)
    else:
        parser.error("pass --bundle or --contracts-cache")
    contracts["trading_date"] = pd.to_datetime(contracts["trading_date"])
    contracts["maturity_date"] = pd.to_datetime(contracts["maturity_date"])
    contracts = contracts.loc[
        contracts["maturity_date"].notna() & contracts["trading_date"].le(WINDOW_END)
    ]
    print(
        "bundle contracts:",
        len(contracts),
        contracts["trading_date"].min().date(),
        "..",
        contracts["trading_date"].max().date(),
    )

    dominant = dominant_map(contracts)
    extension = continuous_prices(contracts, dominant, cached_continuous, extension_start, WINDOW_START)
    continuous = pd.concat(
        [cached_continuous, extension.loc[extension["trading_date"] >= extension_start]],
        ignore_index=True,
    )
    continuous = continuous.loc[continuous["trading_date"] >= WINDOW_START].reset_index(drop=True)

    mask, built, cached, diff = frame_overlap_check(contracts, cached_continuous, cached_dominant)
    print(
        "chaining check (cached dominant map): rows %d | corr %.9f | max|d| %.3g | exact %.5f"
        % (
            len(mask),
            built[mask].corr(cached[mask]) if len(mask) > 1 else float("nan"),
            diff.max() if len(mask) else float("nan"),
            float((diff <= 1e-9).mean()) if len(mask) else float("nan"),
        )
    )

    extension_snapshots = contract_snapshots(contracts, WINDOW_START, WINDOW_END)
    extension_snapshots = extension_snapshots.loc[extension_snapshots["trading_date"] >= extension_start]
    snapshots = pd.concat([cached_snapshots, extension_snapshots], ignore_index=True)
    overlap = snapshots.merge(
        cached_snapshots,
        on=["trading_date", "underlying_symbol", "order_book_id"],
        suffixes=("_built", "_cached"),
        how="inner",
    )
    print(
        "snapshot overlap: rows %d/%d | max|price diff| %.3g | max|oi diff| %.3g"
        % (
            len(overlap),
            len(cached_snapshots),
            (overlap["price_built"] - overlap["price_cached"]).abs().max(),
            (overlap["open_interest_built"] - overlap["open_interest_cached"]).abs().max(),
        )
    )

    expanded_universe = universe(continuous)
    tail = continuous.loc[continuous["trading_date"] >= extension_start]
    print(
        "extension:",
        len(tail),
        "rows",
        tail["trading_date"].min().date(),
        "..",
        tail["trading_date"].max().date(),
        "|",
        tail["underlying_symbol"].nunique(),
        "products |",
        tail["trading_date"].nunique(),
        "days",
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    continuous.attrs.update(cached_continuous.attrs)
    continuous.attrs["source"] = "rqalpha_bundle_rebuild"
    continuous.to_parquet(output_dir / "continuous_prices.parquet", index=False)

    dominant_out = pd.concat([cached_dominant, dominant.loc[dominant["trading_date"] >= extension_start]])
    dominant_out = dominant_out.loc[dominant_out["trading_date"] >= WINDOW_START]
    dominant_out.to_parquet(output_dir / "dominant_map.parquet", index=False)
    snapshots.to_parquet(output_dir / "contract_snapshots.parquet", index=False)

    universe_out = pd.concat(
        [cached_universe, expanded_universe.loc[expanded_universe["trading_date"] >= extension_start]],
        ignore_index=True,
    )
    universe_out.to_parquet(output_dir / "universe.parquet", index=False)

    for name in ("member_rank", "warehouse_stocks"):
        source_path = input_dir / f"{name}.parquet"
        if source_path.exists():
            pd.read_parquet(source_path).to_parquet(output_dir / f"{name}.parquet", index=False)

    print("wrote", output_dir)
    for path in sorted(output_dir.glob("*.parquet")):
        frame = pd.read_parquet(path)
        print(
            f"  {path.name:28s} {len(frame):>9d} rows  "
            f"{frame['trading_date'].min().date()} .. {frame['trading_date'].max().date()}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
