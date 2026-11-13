"""Fetch and cache the extra inputs used by the 22-factor CTA alpha catalog.

Outputs (parquet + metadata) under ``data/research_inputs/cta_alpha22``:

- continuous_prices.parquet : RQData ratio-adjusted dominant open/close/high/low/volume/OI
- contract_snapshots.parquet: real-contract close and OI with maturity dates
- dominant_map.parquet      : official rule=0/rank=1 dominant contract per date
- warehouse_stocks.parquet  : registered warehouse receipts (on_warrant)
- member_rank.parquet       : top-member long/short positions
- universe.parquet          : point-in-time eligible universe

The script is idempotent: existing files are kept unless ``--refresh`` is given.
"""

from __future__ import annotations

import sys

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent / "research"))  # shared loaders
from basis_momentum_test import load_contract_history
from china_cta.data.contracts import (
    get_research_universe,
    get_signal_continuous_price,
)
from china_cta.data.fixed_universe import DEFAULT_FIXED_POOL_FILE, load_fixed_product_pool
from china_cta.data.rqdata_adapter import RQDataAdapter, RQDataConfig


DEFAULT_START = "2016-01-01"
# Rolling default: a refresh should reach the latest settled session, not a
# hard-coded date that silently truncates the cache.
DEFAULT_END = date.today().isoformat()
OUTPUT_DIR = Path("data/research_inputs/cta_alpha22")
FILES = {
    "continuous_prices": "continuous_prices.parquet",
    "contract_snapshots": "contract_snapshots.parquet",
    "dominant_map": "dominant_map.parquet",
    "warehouse_stocks": "warehouse_stocks.parquet",
    "member_rank": "member_rank.parquet",
    "universe": "universe.parquet",
}


def _exists(output_dir: Path) -> bool:
    return all((output_dir / name).is_file() for name in FILES.values())


def fetch_member_rank(
    products: list[str], start: str, end: str
) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    """Fetch member long/short rankings one product at a time."""

    import rqdatac

    frames: list[pd.DataFrame] = []
    failures: list[dict[str, str]] = []
    for product in products:
        for side in ("long", "short"):
            try:
                result = rqdatac.futures.get_member_rank(
                    product,
                    start_date=start,
                    end_date=end,
                    rank_by=side,
                )
            except Exception as exc:  # provider gaps are recorded, not hidden
                failures.append(
                    {"product": product, "side": side, "error": str(exc)}
                )
                continue
            if result is None or len(result) == 0:
                failures.append(
                    {"product": product, "side": side, "error": "empty result"}
                )
                continue
            frame = result.reset_index().rename(
                columns={"commodity_id": "underlying_symbol"}
            )
            if "trading_date" not in frame.columns:
                date_column = next(
                    (
                        column
                        for column in ("date", "index")
                        if column in frame.columns
                    ),
                    None,
                )
                if date_column is None:
                    failures.append(
                        {"product": product, "side": side, "error": "no date column"}
                    )
                    continue
                frame = frame.rename(columns={date_column: "trading_date"})
            frame["side"] = side
            frame["underlying_symbol"] = (
                frame["underlying_symbol"].astype("string").str.strip().str.upper()
            )
            keep = [
                column
                for column in (
                    "trading_date",
                    "underlying_symbol",
                    "side",
                    "rank",
                    "member_name",
                    "volume",
                )
                if column in frame.columns
            ]
            frames.append(frame.loc[:, keep])
    if not frames:
        raise RuntimeError("No member-rank data returned by RQData")
    combined = pd.concat(frames, ignore_index=True)
    combined["trading_date"] = pd.to_datetime(
        combined["trading_date"], errors="raise"
    ).dt.normalize()
    combined["rank"] = pd.to_numeric(combined["rank"], errors="coerce")
    combined["volume"] = pd.to_numeric(combined["volume"], errors="coerce")
    combined = combined.dropna(subset=["trading_date", "underlying_symbol", "rank"])
    combined = combined.drop_duplicates(
        ["trading_date", "underlying_symbol", "side", "rank"]
    ).reset_index(drop=True)
    return combined, failures


def fetch_warehouse_stocks(products: list[str], start: str, end: str) -> pd.DataFrame:
    import rqdatac

    result = rqdatac.futures.get_warehouse_stocks(products, start, end)
    if result is None or len(result) == 0:
        raise RuntimeError("No warehouse-stock data returned by RQData")
    frame = result.reset_index()
    if "date" in frame.columns:
        frame = frame.rename(columns={"date": "trading_date"})
    frame["trading_date"] = pd.to_datetime(
        frame["trading_date"], errors="raise"
    ).dt.normalize()
    frame["underlying_symbol"] = (
        frame["underlying_symbol"].astype("string").str.strip().str.upper()
    )
    frame["on_warrant"] = pd.to_numeric(frame["on_warrant"], errors="coerce")
    keep = ["trading_date", "underlying_symbol", "on_warrant"]
    if "effective_forecast" in frame.columns:
        frame["effective_forecast"] = pd.to_numeric(
            frame["effective_forecast"], errors="coerce"
        )
        keep.append("effective_forecast")
    frame = frame.loc[:, keep].drop_duplicates(
        ["trading_date", "underlying_symbol"]
    )
    return frame.sort_values(["underlying_symbol", "trading_date"]).reset_index(
        drop=True
    )


def fetch_universe(
    adapter: RQDataAdapter,
    products: list[str],
    calendar: pd.DatetimeIndex,
) -> pd.DataFrame:
    frames = []
    for index, day in enumerate(calendar, start=1):
        frames.append(
            get_research_universe(
                adapter,
                day,
                min_listing_history_days=60,
                min_volume=1000,
                min_open_interest=1000,
            )
        )
        if index % 250 == 0 or index == len(calendar):
            print(f"Eligibility {index}/{len(calendar)} trading days", flush=True)
    universe = pd.concat(frames, ignore_index=True)
    return universe.loc[universe["instrument"].isin(products)].reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--products-file", type=Path, default=DEFAULT_FIXED_POOL_FILE)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    pool = load_fixed_product_pool(args.products_file)
    products = list(pool.products)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if _exists(output_dir) and not args.refresh:
        print(f"Inputs already exist in {output_dir}; use --refresh to overwrite")
        for key, name in FILES.items():
            frame = pd.read_parquet(output_dir / name)
            print(f"  {key}: {frame.shape}")
        return

    adapter = RQDataAdapter(RQDataConfig.from_environment())
    adapter.connect()
    print(f"Pool: {pool.holding_month}, {len(products)} products", flush=True)

    calendar = adapter.get_trading_calendar(args.start, args.end)
    print("Loading continuous open/close/high/low/volume/OI", flush=True)
    continuous = get_signal_continuous_price(
        adapter,
        products,
        args.start,
        args.end,
        fields=["open", "close", "high", "low", "volume", "open_interest"],
        adjust_type="pre",
        adjust_method="prev_close_ratio",
    )
    ordered = [
        "trading_date",
        "underlying_symbol",
        "close",
        "open",
        "high",
        "low",
        "volume",
        "open_interest",
    ]
    continuous = continuous[[c for c in ordered if c in continuous.columns]]
    if "open" not in continuous.columns:
        print(
            "WARNING: RQData returned no open column; run"
            " scripts/12_add_open_from_bundle.py before backtesting",
            flush=True,
        )
    continuous.to_parquet(output_dir / FILES["continuous_prices"], index=False)

    print("Loading real-contract snapshots", flush=True)
    snapshots = load_contract_history(
        adapter,
        products,
        calendar,
        args.start,
        args.end,
        include_open_interest=True,
    )
    snapshots.to_parquet(output_dir / FILES["contract_snapshots"], index=False)

    print("Loading dominant map", flush=True)
    dominant = adapter.get_dominant_map(
        products, args.start, args.end, rule=0, rank=1
    )
    dominant.to_parquet(output_dir / FILES["dominant_map"], index=False)

    print("Loading warehouse receipts", flush=True)
    warehouse = fetch_warehouse_stocks(products, args.start, args.end)
    warehouse.to_parquet(output_dir / FILES["warehouse_stocks"], index=False)

    print("Loading member rankings (long/short)", flush=True)
    member, member_failures = fetch_member_rank(products, args.start, args.end)
    member.to_parquet(output_dir / FILES["member_rank"], index=False)

    print("Loading point-in-time universe", flush=True)
    universe = fetch_universe(adapter, products, calendar)
    universe.to_parquet(output_dir / FILES["universe"], index=False)

    metadata = {
        "source_repository": "https://github.com/quantskills/skill-futures-cta-alpha",
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "start": args.start,
        "end": args.end,
        "products": products,
        "fixed_pool_holding_month": pool.holding_month,
        "provider": "rqdatac 3.6.3 / RQData futures",
        "shapes": {
            "continuous_prices": list(continuous.shape),
            "contract_snapshots": list(snapshots.shape),
            "dominant_map": list(dominant.shape),
            "warehouse_stocks": list(warehouse.shape),
            "member_rank": list(member.shape),
            "universe": list(universe.shape),
        },
        "member_rank_failures": member_failures,
        "notes": [
            "continuous prices are ratio-adjusted dominant prices for signal research only",
            "contract snapshots use unadjusted real-contract close prices",
            "warehouse_stocks.on_warrant is the registered warehouse receipt series",
            "member_rank volume is the exchange-reported long or short position",
        ],
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(metadata["shapes"], ensure_ascii=False, indent=2))
    print(f"Saved inputs to {output_dir}")


if __name__ == "__main__":
    sys.exit(main())
