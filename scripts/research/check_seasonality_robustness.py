"""Recheck a completed all-commodity return seasonality run without RQData."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from china_cta.research.seasonality_robustness import calendar_return_robustness


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--permutations", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20260930)
    args = parser.parse_args()
    source = args.input_dir / "monthly_returns.csv"
    metadata_file = args.input_dir / "metadata.json"
    if not source.is_file() or not metadata_file.is_file():
        parser.error("input-dir must contain monthly_returns.csv and metadata.json")
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    monthly = pd.read_csv(source)
    summary, years = calendar_return_robustness(
        monthly,
        min_train_years=int(metadata["min_train_years"]),
        min_test_years=int(metadata["min_test_years"]),
        permutations=args.permutations, seed=args.seed,
    )
    output = args.output_dir or (args.input_dir / "robustness")
    output.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output / "robustness_by_product.csv", index=False, encoding="utf-8-sig")
    years.to_csv(output / "robustness_by_year.csv", index=False, encoding="utf-8-sig")
    (output / "metadata.json").write_text(json.dumps({
        "source": str(source), "permutations": args.permutations,
        "seed": args.seed, "min_train_years": metadata["min_train_years"],
        "min_test_years": metadata["min_test_years"],
        "null": "shuffle observed monthly returns within each calendar year",
        "multiple_testing": "Benjamini-Hochberg FDR across all testable products",
        "diagnostic_threshold": "positive OOS R2, FDR q < 0.05, positive gain in at least half of test years",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(summary.loc[:, ["underlying_symbol", "tested_years", "oos_seasonal_r2",
                          "positive_gain_years", "permutation_p", "fdr_q", "robust_evidence"]]
          .head(15).to_string(index=False))
    print(f"Saved {len(summary)} products to {output}")


if __name__ == "__main__":
    main()
