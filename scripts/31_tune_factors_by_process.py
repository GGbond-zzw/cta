"""Multi-process Bayesian tuning for the four qualified sleeves.

Each factor runs in its own process with its own sqlite-backed Optuna study, so
an interrupted run resumes instead of losing its trials.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from china_cta.research import bayesian_tuning as bt  # noqa: E402

INPUT_DIR = PROJECT / "data" / "research_inputs" / "cta_alpha22"
FACTORS = (
    "fixed_maturity_carry_90_180d",
    "xsmom_252_21",
    "oi_participation_trend_60d",
    "historical_skewness_252d",
)
MINED_FACTORS = (
    "crowded_trend_reversal_60d",
    "volume_oi_coflow_10d",
    "volume_burst_vol_reversal_60d",
)

_INPUTS: dict | None = None


def _init_worker() -> None:
    global _INPUTS
    _INPUTS = bt.load_inputs(INPUT_DIR)


def _run_one(args: tuple[str, int, int, int, bool, str]) -> dict:
    name, trials, workers, seed, tune_scale, output_dir = args
    assert _INPUTS is not None
    started = time.perf_counter()
    factor_dir = Path(output_dir) / name
    payload = bt.run_factor_study(
        name,
        _INPUTS,
        trials=trials,
        workers=workers,
        seed=seed,
        output_dir=Path(output_dir),
        tune_scale=tune_scale,
        storage=factor_dir / "study.sqlite3",
    )
    seconds = time.perf_counter() - started
    best = payload["best_train"]
    oos = payload["best_oos"]
    base = payload["baseline_train"]
    print(
        f"{name}: {seconds / 60:.1f} min  train {best['sharpe']:.3f}"
        f" / oos {oos['sharpe']:.3f}  (baseline train {base['sharpe']:.3f})",
        flush=True,
    )
    return {
        "factor_name": name,
        "best_train_sharpe": best["sharpe"],
        "best_train_net": best["annualized_net"],
        "best_train_vol": best["annualized_vol"],
        "best_train_mdd": best["max_drawdown"],
        "best_oos_sharpe": oos["sharpe"],
        "best_oos_net": oos["annualized_net"],
        "best_oos_mdd": oos["max_drawdown"],
        "baseline_train_sharpe": base["sharpe"],
        "baseline_oos_sharpe": payload["baseline_oos"]["sharpe"],
        "best_params": json.dumps(payload["best_params"], ensure_ascii=False, sort_keys=True),
        "best_signal_scale": payload["best_params"].get("signal_scale"),
        "tuned_params": ",".join(payload["tuned_params"]),
        "backtest_seconds": seconds,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=300)
    parser.add_argument("--processes", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT / "results" / "tuning" / "qualified4_300",
    )
    parser.add_argument("--no-scale-tune", action="store_true")
    parser.add_argument("--factors", default=",".join(FACTORS))
    args = parser.parse_args()

    selected = [name.strip() for name in args.factors.split(",") if name.strip()]
    unknown = sorted(set(selected) - set(bt.TUNING_SPECS))
    if unknown:
        raise SystemExit(f"unknown tuning factors: {unknown}")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    jobs = [
        (name, args.trials, 1, args.seed, not args.no_scale_tune, str(args.output_dir))
        for name in selected
    ]
    with ProcessPoolExecutor(max_workers=args.processes, initializer=_init_worker) as pool:
        rows = list(pool.map(_run_one, jobs))
    total = time.perf_counter() - started

    import pandas as pd

    summary = pd.DataFrame(rows).sort_values("best_train_sharpe", ascending=False)
    summary.to_csv(
        args.output_dir / "summary.csv",
        index=False,
        float_format="%.17g",
    )
    manifest = {
        "trial_count_per_factor": args.trials,
        "factor_processes": args.processes,
        "workers_per_study": 1,
        "seed": args.seed,
        "tune_scale": not args.no_scale_tune,
        "scale_policy": (
            "signal_scale is tuned inside its historical range"
            if not args.no_scale_tune
            else "signal_scale is pinned to each factor's baseline value"
        ),
        "scale_ranges": {
            name: list(bt.SCALE_RANGES[name]) if not args.no_scale_tune else []
            for name in selected
        },
        "split": {
            "train": [bt.TRAIN_START, bt.TRAIN_END],
            "oos": [bt.OOS_START, bt.OOS_END],
        },
        "constraints": {
            "min_observations": bt.MIN_OBSERVATIONS,
            "max_drawdown": bt.MAX_DRAWDOWN,
            "max_turnover": bt.MAX_TURNOVER,
        },
        "backtest": {
            "execution_lag": bt.EXECUTION_LAG,
            "cost_rate": bt.COST_RATE,
            "execution_price_field": "open",
            "annualization_factor": 252,
        },
        "input_dir": str(INPUT_DIR),
        "factors": selected,
        "sampler": "TPESampler(multivariate=True, group=True, n_startup_trials=10)",
        "storage": "per-factor sqlite study (<factor>/study.sqlite3), resumable",
        "seconds_per_factor": {row["factor_name"]: row["backtest_seconds"] for row in rows},
        "total_seconds": total,
        "notes": (
            "New qualified set after the execution fix: fills happen at the next"
            " open, not at the next close."
        ),
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    display = summary[
        [
            "factor_name",
            "best_train_sharpe",
            "best_oos_sharpe",
            "baseline_train_sharpe",
            "best_signal_scale",
            "backtest_seconds",
        ]
    ]
    print(display.to_string(index=False, float_format=lambda value: f"{value:.4f}"))
    print(f"total {total / 3600:.2f} h -> {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
