"""Screen return seasonality across every commodity future, not the trading pool.

The first-stage screen measures calendar-month return seasonality only. It does
not yet classify volatility or delivery-month/curve seasonality.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd

from china_cta.research.seasonality import (
    calendar_return_diagnostics,
    held_contract_returns,
    monthly_return_panel,
)


REAL_CONTRACT = re.compile(r"^[A-Za-z]+[0-9]{3,4}$")


def load_live(start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    from china_cta.data.rqdata_adapter import RQDataAdapter

    adapter = RQDataAdapter()
    master = adapter.get_future_instruments()
    commodity = master.loc[
        master["product"].eq("Commodity")
        & master["order_book_id"].astype(str).str.fullmatch(REAL_CONTRACT.pattern)
        & pd.to_datetime(master["listed_date"], errors="coerce").le(pd.Timestamp(end))
        & pd.to_datetime(master["de_listed_date"], errors="coerce").ge(pd.Timestamp(start))
    ].copy()
    symbols = sorted(commodity["underlying_symbol"].dropna().astype(str).unique())
    maps, bars, errors = [], [], []
    for symbol in symbols:
        succeeded = False
        try:
            dominant = adapter.get_dominant_map(symbol, start, end)
            ids = sorted(dominant["dominant_order_book_id"].dropna().unique())
            if not ids:
                raise ValueError("no dominant real contracts")
            product_bars = []
            for offset in range(0, len(ids), 50):
                product_bars.append(adapter.get_bars(
                    ids[offset:offset + 50], start, end,
                    fields=("close",),
                ))
            maps.append(dominant)
            bars.append(pd.concat(product_bars, ignore_index=True))
            succeeded = True
        except Exception as exc:
            errors.append({"underlying_symbol": symbol, "error": str(exc)})
        print(f"{symbol}: {'ok' if succeeded else 'failed'}")
    if not maps:
        raise RuntimeError("No commodity product was downloaded successfully")
    return (pd.concat(maps, ignore_index=True), pd.concat(bars, ignore_index=True),
            pd.DataFrame(errors, columns=["underlying_symbol", "error"]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2010-01-01")
    parser.add_argument("--end", required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("results/commodity_seasonality_close"))
    parser.add_argument("--dominant-map-csv", type=Path)
    parser.add_argument("--bars-csv", type=Path)
    parser.add_argument("--min-coverage", type=float, default=0.8)
    parser.add_argument("--min-train-years", type=int, default=5)
    parser.add_argument("--min-test-years", type=int, default=3)
    args = parser.parse_args()
    if pd.Timestamp(args.start) >= pd.Timestamp(args.end):
        parser.error("--start must precede --end")
    if bool(args.dominant_map_csv) != bool(args.bars_csv):
        parser.error("provide both CSV inputs, or neither for live RQData")
    if args.dominant_map_csv:
        dominant = pd.read_csv(args.dominant_map_csv)
        bars = pd.read_csv(args.bars_csv)
        errors = pd.DataFrame(columns=["underlying_symbol", "error"])
    else:
        dominant, bars, errors = load_live(args.start, args.end)
    daily = held_contract_returns(dominant, bars)
    daily = daily.loc[daily["trading_date"].between(args.start, args.end)]
    monthly = monthly_return_panel(daily, min_coverage=args.min_coverage)
    # The boundary months may be partial; they cannot be compared with full months.
    complete_months = monthly["month"].between(
        pd.Timestamp(args.start).to_period("M") + 1,
        pd.Timestamp(args.end).to_period("M") - 1,
    )
    monthly = monthly.loc[complete_months].copy()
    diagnostics = calendar_return_diagnostics(
        monthly, min_train_years=args.min_train_years,
        min_test_years=args.min_test_years,
    ).sort_values("oos_seasonal_r2", ascending=False, na_position="last")
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    daily.to_csv(output / "daily_returns.csv", index=False, encoding="utf-8-sig")
    monthly.to_csv(output / "monthly_returns.csv", index=False, encoding="utf-8-sig")
    diagnostics.to_csv(output / "return_diagnostics.csv", index=False, encoding="utf-8-sig")
    errors.to_csv(output / "download_errors.csv", index=False, encoding="utf-8-sig")
    (output / "metadata.json").write_text(json.dumps({
        "scope": "all_commodity_futures_not_fixed_trading_pool",
        "start": args.start, "end": args.end,
        "return_definition": "previous-day dominant real contract, same-contract close log return",
        "first_stage_only": "calendar-month return seasonality",
        "min_train_years": args.min_train_years,
        "min_test_years": args.min_test_years,
        "min_month_coverage": args.min_coverage,
        "success_products": int(diagnostics["underlying_symbol"].nunique()),
        "download_failures": len(errors),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(diagnostics.to_string(index=False))
    print(f"Saved {len(diagnostics)} products to {output}; download failures: {len(errors)}")


if __name__ == "__main__":
    main()
