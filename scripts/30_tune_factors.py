"""Tune the four qualified factors with Bayesian optimization.

Train period: 2016-01-04 to 2021-12-31.
Out-of-sample: 2022-01-04 to 2025-12-31 (never used by the search).
Objective: training-period net Sharpe of the project's fast research backtest,
subject to observation/drawdown/turnover constraints.

Outputs go to ``results/tuning/qualified4_300/<factor>/`` and never replace
``results/qualified`` (the legacy close-to-close research library).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from china_cta.research.bayesian_tuning import (
    SCALE_TUNED_SPECS,
    TUNING_SPECS,
    TUNING_INPUT_DIR,
    run_all,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--factors",
        default="",
        help="comma-separated factor names; default is all four qualified factors",
    )
    parser.add_argument("--trials", type=int, default=60)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--tune-scale",
        action="store_true",
        help="also search signal_scale inside its historical range; writes to a"
        " separate output directory instead of replacing the pinned-scale results",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="default: results/tuning/qualified4_300, or the _scale_tuned"
        " sibling with --tune-scale",
    )
    parser.add_argument("--input-dir", type=Path, default=TUNING_INPUT_DIR)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="allow writing into an existing tuning output directory",
    )
    args = parser.parse_args()

    specs = SCALE_TUNED_SPECS if args.tune_scale else TUNING_SPECS
    output_dir = args.output_dir or Path(
        "results/tuning/qualified4_300_scale_tuned"
        if args.tune_scale
        else "results/tuning/qualified4_300"
    )
    selected = (
        [name.strip() for name in args.factors.split(",") if name.strip()]
        if args.factors
        else list(specs)
    )
    if output_dir.exists() and any(output_dir.iterdir()) and not args.overwrite:
        parser.error(f"{output_dir} already exists; pass --overwrite to replace")
    if args.trials < 1:
        parser.error("--trials must be >= 1")
    if args.workers < 1:
        parser.error("--workers must be >= 1")

    summary = run_all(
        factors=selected,
        trials=args.trials,
        workers=args.workers,
        seed=args.seed,
        output_dir=output_dir,
        input_dir=args.input_dir,
        tune_scale=args.tune_scale,
    )
    print(summary.to_string(index=False))


if __name__ == "__main__":
    sys.exit(main())
