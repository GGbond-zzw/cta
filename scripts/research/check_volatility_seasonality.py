"""Test all-commodity calendar-month volatility seasonality from daily returns."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from china_cta.research.seasonality_robustness import (
    calendar_return_robustness,
    monthly_volatility_panel,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--min-coverage", type=float, default=0.8)
    parser.add_argument("--min-valid-days", type=int, default=10)
    parser.add_argument("--permutations", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20260930)
    args = parser.parse_args()
    source = args.input_dir / "daily_returns.csv"
    metadata_file = args.input_dir / "metadata.json"
    if not source.is_file() or not metadata_file.is_file():
        parser.error("input-dir must contain daily_returns.csv and metadata.json")
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    daily = pd.read_csv(source)
    monthly = monthly_volatility_panel(
        daily, min_coverage=args.min_coverage,
        min_valid_days=args.min_valid_days,
    )
    monthly = monthly.loc[monthly["month"].between(
        pd.Timestamp(metadata["start"]).to_period("M") + 1,
        pd.Timestamp(metadata["end"]).to_period("M") - 1,
    )].copy()
    renamed = monthly.rename(columns={"log_daily_rms_volatility": "log_return"})
    summary, years = calendar_return_robustness(
        renamed,
        min_train_years=int(metadata["min_train_years"]),
        min_test_years=int(metadata["min_test_years"]),
        permutations=args.permutations, seed=args.seed,
    )
    output = args.output_dir or (args.input_dir / "volatility_seasonality")
    output.mkdir(parents=True, exist_ok=True)
    monthly.to_csv(output / "monthly_volatility.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(output / "volatility_by_product.csv", index=False, encoding="utf-8-sig")
    years.to_csv(output / "volatility_by_year.csv", index=False, encoding="utf-8-sig")
    (output / "metadata.json").write_text(json.dumps({
        "source": str(source),
        "metric": "log(sqrt(mean(daily log_return squared)))",
        "min_coverage": args.min_coverage,
        "min_valid_days": args.min_valid_days,
        "min_train_years": metadata["min_train_years"],
        "min_test_years": metadata["min_test_years"],
        "permutations": args.permutations,
        "seed": args.seed,
        "null": "shuffle observed monthly volatility values within each year",
        "multiple_testing": "Benjamini-Hochberg FDR across testable products",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(summary.head(15).to_string(index=False))
    print(f"Saved {len(summary)} products to {output}")


if __name__ == "__main__":
    main()
