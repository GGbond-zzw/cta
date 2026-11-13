"""Add the adjusted ``open`` column that the next-open execution engine needs.

RQData's daily futures bars only expose the traded ``close`` chain, so the
research inputs are fetched without an ``open`` column.  The local RQAlpha
bundle does store a raw ``open`` per contract; this stage joins it on the
dominant contract of each day and rescales it with the same factor that maps
the raw close onto the cached, ratio-adjusted close:

    factor    = cached_close / raw_close
    adj_open  = raw_open * factor

That keeps open and close on the same price level, which is all the
open-to-open return needs.

Usage::

    python scripts/12_add_open_from_bundle.py \
        --input-dir data/research_inputs/cta_alpha22 \
        --bundle C:/Users/ct/Desktop/python/CTA/Mikuang_data/.rqalpha/bundle

The command is idempotent: if ``open`` is already present it exits after
checking the column.  By default every row must be covered by the bundle; pass
``--fill-missing-with-close`` to fall back to ``close`` for dates the bundle
does not reach yet (recorded in the table metadata as ``open_source``).
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = PROJECT / "data" / "research_inputs" / "cta_alpha22"
PRICE_COLUMNS = (
    "trading_date",
    "underlying_symbol",
    "close",
    "open",
    "high",
    "low",
    "volume",
    "open_interest",
)


def read_bars(handle: h5py.File, contract: str) -> pd.DataFrame:
    raw = np.asarray(handle[contract])
    return pd.DataFrame(
        {
            "trading_date": pd.to_datetime(
                raw["datetime"].astype("int64"), format="%Y%m%d%H%M%S"
            ).normalize(),
            "raw_open": raw["open"].astype(float),
            "raw_close": raw["close"].astype(float),
        }
    )


def build(prices: pd.DataFrame, dominant: pd.DataFrame, bundle: Path) -> pd.DataFrame:
    contracts = sorted(dominant["dominant_order_book_id"].dropna().unique())
    frames: list[pd.DataFrame] = []
    with h5py.File(bundle / "futures.h5", "r") as handle:
        available = [c for c in contracts if c in handle.keys()]
        missing = sorted(set(contracts) - set(available))
        if missing:
            print(f"contracts absent from the bundle: {len(missing)} (e.g. {missing[:3]})")
        for contract in available:
            frame = read_bars(handle, contract)
            frame["dominant_order_book_id"] = contract
            frames.append(frame)
    raw = pd.concat(frames, ignore_index=True)

    merged = dominant.merge(raw, on=["trading_date", "dominant_order_book_id"], how="left")
    merged = merged.merge(
        prices[["trading_date", "underlying_symbol", "close"]].rename(
            columns={"close": "cached_close"}
        ),
        on=["trading_date", "underlying_symbol"],
        how="left",
        validate="one_to_one",
    )
    resolvable = merged["raw_close"].notna() & merged["cached_close"].notna()
    print(f"rows {len(merged)}, resolvable from bundle {int(resolvable.sum())}")
    if not resolvable.any():
        raise SystemExit("the bundle covers none of the requested dates")

    factor = merged.loc[resolvable, "cached_close"] / merged.loc[resolvable, "raw_close"]
    merged.loc[resolvable, "adj_open"] = merged.loc[resolvable, "raw_open"] * factor
    ratio = merged.loc[resolvable, "adj_open"] / merged.loc[resolvable, "cached_close"]
    print(
        "open/close quantiles p01=%.4f p50=%.4f p99=%.4f"
        % tuple(np.nanquantile(ratio, [0.01, 0.5, 0.99]))
    )
    bad = merged.loc[resolvable, "adj_open"]
    if not np.isfinite(bad).all() or (bad <= 0).any():
        raise SystemExit("non-positive or non-finite adjusted open prices")
    if ((ratio < 0.5) | (ratio > 2.0)).any():
        raise SystemExit("open/close ratio outside [0.5, 2.0]")

    aligned = merged[["trading_date", "underlying_symbol", "adj_open"]].rename(
        columns={"adj_open": "open"}
    )
    return prices.merge(
        aligned, on=["trading_date", "underlying_symbol"], how="left", validate="one_to_one"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument(
        "--bundle",
        type=Path,
        default=Path(
            os.environ.get(
                "CTA_RQALPHA_BUNDLE_PATH",
                r"C:\Users\ct\Desktop\python\CTA\Mikuang_data\.rqalpha\bundle",
            )
        ),
        help="RQAlpha bundle directory containing futures.h5",
    )
    parser.add_argument(
        "--fill-missing-with-close",
        action="store_true",
        help="use close for dates the bundle does not reach (logged in the metadata)",
    )
    args = parser.parse_args()

    prices_path = args.input_dir / "continuous_prices.parquet"
    prices = pd.read_parquet(prices_path)
    print(f"cached {prices.shape} {list(prices.columns)}")
    if "open" in prices.columns:
        print("open column already present; nothing to do")
        return 0

    dominant = pd.read_parquet(args.input_dir / "dominant_map.parquet")
    dominant["trading_date"] = pd.to_datetime(dominant["trading_date"])
    prices["trading_date"] = pd.to_datetime(prices["trading_date"])
    if "dominant_order_book_id" not in dominant.columns:
        raise SystemExit("dominant_map.parquet has no dominant_order_book_id column")

    result = build(prices, dominant, args.bundle)
    filled = int(result["open"].isna().sum())
    if filled:
        if not args.fill_missing_with_close:
            raise SystemExit(
                f"{filled} rows are not covered by the bundle; refresh the bundle or"
                " pass --fill-missing-with-close"
            )
        last_covered = result.loc[result["open"].notna(), "trading_date"].max()
        print(
            f"{filled} rows after {last_covered.date()} fall back to close"
            " (recorded as open_source=close_fallback)"
        )
        result["open"] = result["open"].fillna(result["close"])

    result = result[list(PRICE_COLUMNS)].sort_values(
        ["trading_date", "underlying_symbol"], ignore_index=True
    )
    result.attrs = dict(prices.attrs)
    result.attrs["columns_added"] = "open (bundle raw open * cached_close/raw_close)"
    result.attrs["open_source"] = f"bundle={len(result) - filled};close_fallback={filled}"

    backup = prices_path.with_suffix(".parquet.bak")
    if not backup.exists():
        shutil.copy2(prices_path, backup)
        print(f"backup written {backup}")

    tmp = prices_path.with_suffix(".parquet.tmp")
    result.to_parquet(tmp, index=False)
    tmp.replace(prices_path)

    reloaded = pd.read_parquet(prices_path)
    print(f"wrote {reloaded.shape} {list(reloaded.columns)}")
    print(
        f"date range {reloaded['trading_date'].min().date()}..{reloaded['trading_date'].max().date()}"
    )
    print(f"metadata {dict(reloaded.attrs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
