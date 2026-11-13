"""Export yearly real-contract close curves for all commodity futures.

Requires a locally licensed RQData environment. The fixed 30-product trading
list is deliberately not consulted.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd


REAL_CONTRACT = re.compile(r"^[A-Za-z]+[0-9]{1,2}(?:0[1-9]|1[0-2])$")


def export_year(adapter, master: pd.DataFrame, year: int, output: Path, batch_size: int) -> dict:
    start = pd.Timestamp(year=year, month=1, day=1)
    end = pd.Timestamp(year=year, month=12, day=31)
    active = master.loc[
        master["product"].eq("Commodity")
        & master["order_book_id"].astype(str).str.fullmatch(REAL_CONTRACT.pattern)
        & pd.to_datetime(master["listed_date"], errors="coerce").le(end)
        & pd.to_datetime(master["de_listed_date"], errors="coerce").ge(start)
    ].copy()
    ids = active["order_book_id"].astype(str).tolist()
    frames, failures = [], []
    for offset in range(0, len(ids), batch_size):
        batch = ids[offset:offset + batch_size]
        try:
            frames.append(adapter.get_bars(
                batch, start, end, fields=("close", "volume", "open_interest")
            ))
        except Exception as batch_exc:
            # Some historical contracts have no bars in their listed interval;
            # salvage the batch while recording every failed contract.
            for contract in batch:
                try:
                    frames.append(adapter.get_bars(
                        contract, start, end,
                        fields=("close", "volume", "open_interest"),
                    ))
                except Exception as exc:
                    failures.append({
                        "year": year, "order_book_id": contract,
                        "error": str(exc), "batch_error": str(batch_exc),
                    })
        print(f"{year}: {min(offset + batch_size, len(ids))}/{len(ids)} contracts requested")
    if not frames:
        raise RuntimeError(f"No real commodity contract bars found for {year}")
    bars = pd.concat(frames, ignore_index=True)
    if bars.duplicated(["trading_date", "order_book_id"]).any():
        raise ValueError(f"Duplicate contract-date bars in {year}")
    returned_ids = set(bars["order_book_id"].astype(str))
    already_failed = {row["order_book_id"] for row in failures}
    for contract in sorted(set(ids) - returned_ids - already_failed):
        failures.append({
            "year": year, "order_book_id": contract,
            "error": "no bars returned in annual batch", "batch_error": "",
        })
    detail = active[["order_book_id", "underlying_symbol", "maturity_date"]].copy()
    snapshots = bars.merge(detail, on="order_book_id", how="left", validate="many_to_one")
    snapshots["trading_date"] = pd.to_datetime(snapshots["trading_date"]).dt.normalize()
    snapshots["maturity_date"] = pd.to_datetime(snapshots["maturity_date"])
    snapshots["days_to_maturity"] = (
        snapshots["maturity_date"] - snapshots["trading_date"]
    ).dt.days
    snapshots = snapshots.rename(columns={"close": "price"})
    snapshots["price_field"] = "close"
    snapshots = snapshots[[
        "trading_date", "underlying_symbol", "order_book_id",
        "maturity_date", "days_to_maturity", "price", "price_field",
        "volume", "open_interest",
    ]].sort_values(["trading_date", "underlying_symbol", "days_to_maturity"])
    output.mkdir(parents=True, exist_ok=True)
    snapshots.to_parquet(output / f"snapshots_{year}.parquet", index=False)
    pd.DataFrame(failures, columns=["year", "order_book_id", "error", "batch_error"]).to_csv(
        output / f"errors_{year}.csv", index=False, encoding="utf-8-sig",
    )
    return {
        "year": year, "master_commodity_products": int(active["underlying_symbol"].nunique()),
        "master_contracts": len(ids),
        "bar_contracts": int(snapshots["order_book_id"].nunique()),
        "bar_rows": len(snapshots), "failed_contracts": len(failures),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, default=2010)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--output-dir", type=Path, default=Path("results/all_commodity_curves_close"))
    args = parser.parse_args()
    if args.start_year > args.end_year or args.batch_size < 1:
        parser.error("start-year must not exceed end-year; batch-size must be positive")
    from china_cta.data.rqdata_adapter import RQDataAdapter

    adapter = RQDataAdapter()
    master = adapter.get_future_instruments()
    summaries = []
    for year in range(args.start_year, args.end_year + 1):
        summaries.append(export_year(adapter, master, year, args.output_dir, args.batch_size))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(summaries).to_csv(
        args.output_dir / "export_coverage.csv", index=False, encoding="utf-8-sig"
    )
    (args.output_dir / "metadata.json").write_text(json.dumps({
        "scope": "all historic real commodity contracts, no fixed trading pool",
        "start_year": args.start_year, "end_year": args.end_year,
        "price_field": "unadjusted daily close",
        "batch_size": args.batch_size,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(pd.DataFrame(summaries).to_string(index=False))


if __name__ == "__main__":
    main()
