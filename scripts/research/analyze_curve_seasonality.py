"""All-commodity delivery-month curve-curvature diagnostic from real contracts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from china_cta.research.curve_seasonality import (
    annual_delivery_month_panel,
    daily_curve_residuals,
)
from china_cta.research.seasonality_robustness import calendar_return_robustness


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--min-days-to-maturity", type=int, default=30)
    parser.add_argument("--max-days-to-maturity", type=int, default=540)
    parser.add_argument("--min-contracts", type=int, default=4)
    parser.add_argument("--min-volume", type=float, default=1)
    parser.add_argument("--min-open-interest", type=float, default=1)
    parser.add_argument("--min-distinct-days", type=int, default=20)
    parser.add_argument("--min-train-years", type=int, default=5)
    parser.add_argument("--min-test-years", type=int, default=3)
    parser.add_argument("--permutations", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20260930)
    args = parser.parse_args()
    files = sorted(args.snapshot_dir.glob("snapshots_*.parquet"))
    if not files:
        parser.error("snapshot-dir contains no snapshots_YYYY.parquet files")
    annual_frames = []
    coverage_rows = []
    product_coverage_rows = []
    for file in files:
        snapshots = pd.read_parquet(file)
        residuals = daily_curve_residuals(
            snapshots,
            min_days_to_maturity=args.min_days_to_maturity,
            max_days_to_maturity=args.max_days_to_maturity,
            min_contracts=args.min_contracts,
            min_volume=args.min_volume,
            min_open_interest=args.min_open_interest,
        )
        annual_frames.append(annual_delivery_month_panel(
            residuals, min_distinct_days=args.min_distinct_days,
        ))
        coverage_rows.append({
            "file": file.name,
            "snapshot_products": int(snapshots["underlying_symbol"].nunique()),
            "curve_products": int(residuals["underlying_symbol"].nunique()),
            "curve_dates": int(residuals[["trading_date", "underlying_symbol"]]
                               .drop_duplicates().shape[0]),
        })
        snapshot_counts = snapshots.groupby("underlying_symbol")["trading_date"].nunique()
        curve_counts = residuals.groupby("underlying_symbol")["trading_date"].nunique()
        for symbol, count in snapshot_counts.items():
            product_coverage_rows.append({
                "file": file.name, "underlying_symbol": symbol,
                "snapshot_dates": int(count),
                "eligible_curve_dates": int(curve_counts.get(symbol, 0)),
            })
        print(f"{file.name}: {coverage_rows[-1]['curve_products']} curve products")
    annual = pd.concat(annual_frames, ignore_index=True)
    if annual.empty or annual["mean_curve_residual"].notna().sum() == 0:
        raise RuntimeError("No product has enough eligible delivery-month curve observations")
    if annual.duplicated(["underlying_symbol", "year", "delivery_month"]).any():
        raise ValueError("snapshot files overlap a calendar year; use non-overlapping yearly partitions")
    model_input = annual.rename(columns={
        "delivery_month": "calendar_month", "mean_curve_residual": "log_return"
    })
    summary, year_errors = calendar_return_robustness(
        model_input,
        min_train_years=args.min_train_years,
        min_test_years=args.min_test_years,
        permutations=args.permutations, seed=args.seed,
    )
    output = args.output_dir or (args.snapshot_dir / "curve_seasonality")
    output.mkdir(parents=True, exist_ok=True)
    annual.to_csv(output / "delivery_month_panel.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(output / "curve_by_product.csv", index=False, encoding="utf-8-sig")
    year_errors.to_csv(output / "curve_by_year.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(coverage_rows).to_csv(output / "coverage_by_file.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(product_coverage_rows).to_csv(
        output / "coverage_by_product_year.csv", index=False, encoding="utf-8-sig"
    )
    (output / "metadata.json").write_text(json.dumps({
        "scope": "all available real commodity contracts, independent of fixed trading pool",
        "metric": "delivery-month mean residual after same-day OLS log close ~ years to maturity",
        "identification": "curve curvature only; not level or linear slope seasonality",
        "min_days_to_maturity": args.min_days_to_maturity,
        "max_days_to_maturity": args.max_days_to_maturity,
        "min_contracts": args.min_contracts,
        "min_volume": args.min_volume,
        "min_open_interest": args.min_open_interest,
        "min_distinct_days": args.min_distinct_days,
        "min_train_years": args.min_train_years,
        "min_test_years": args.min_test_years,
        "permutations": args.permutations,
        "seed": args.seed,
        "multiple_testing": "Benjamini-Hochberg FDR across testable products",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(summary.head(15).to_string(index=False))
    print(f"Saved {len(summary)} products to {output}")


if __name__ == "__main__":
    main()
