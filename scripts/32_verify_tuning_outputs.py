"""Verify the re-run tuning outputs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from china_cta.research import bayesian_tuning as bt  # noqa: E402

_parser = argparse.ArgumentParser(description="verify the tuning outputs of a study")
_parser.add_argument(
    "--tuned-dir",
    default=str(PROJECT / "results" / "tuning" / "qualified4_300"),
)
RESULTS = Path(_parser.parse_args().tuned_dir)
BASELINE_CARRY_TRAIN = 0.8818130914970075

summary = pd.read_csv(RESULTS / "summary.csv")
manifest = json.loads((RESULTS / "manifest.json").read_text(encoding="utf-8"))
print(f"dirs: {sorted(p.name for p in RESULTS.iterdir())}")
print(f"summary rows: {len(summary)}")
print(manifest["scale_policy"])
print("manifest fixed:", manifest["fixed_params"])
print("manifest failed:", manifest.get("failed_factors", "none"))

rows = []
for name, spec in bt.TUNING_SPECS.items():
    factor_dir = RESULTS / name
    payload = json.loads((factor_dir / "best_params.json").read_text(encoding="utf-8"))
    trials = pd.read_csv(factor_dir / "trials.csv")
    baseline_scale = spec.fixed["signal_scale"]

    checks = {
        "trials": len(trials),
        "complete": int((trials["state"] == "COMPLETE").sum()),
        "has_param_scale": "param_signal_scale" in trials.columns,
        "fixed_scale_col": (
            sorted(trials["fixed_signal_scale"].unique().tolist())
            if "fixed_signal_scale" in trials.columns
            else None
        ),
        "payload_fixed": payload["fixed_params"],
        "best_scale": payload["best_params"]["signal_scale"],
        "baseline_scale": payload["baseline_params"]["signal_scale"],
        "tuned": payload["tuned_params"],
        "trial0_value": float(trials.loc[trials["number"] == 0, "value"].iloc[0]),
        "baseline_train_sharpe": payload["baseline_train"]["sharpe"],
        "best_train_sharpe": payload["best_train"]["sharpe"],
        "best_oos_sharpe": payload["best_oos"]["sharpe"],
        "best_scale_ok": payload["best_params"]["signal_scale"] == baseline_scale,
        "scale_column_absent": "param_signal_scale" not in trials.columns,
        "fixed_all_baseline": bool(
            "fixed_signal_scale" in trials.columns
            and trials["fixed_signal_scale"].nunique() == 1
            and float(trials["fixed_signal_scale"].iloc[0]) == baseline_scale
        ),
        "trial0_is_baseline": abs(
            float(trials.loc[trials["number"] == 0, "value"].iloc[0])
            - payload["baseline_train"]["sharpe"]
        )
        < 1e-12,
        "best_factor_parquet": (factor_dir / "best_factor.parquet").is_file(),
    }
    rows.append({"factor": name, **checks})

frame = pd.DataFrame(rows)
pd.set_option("display.width", 250)
print(
    frame[
        [
            "factor",
            "trials",
            "complete",
            "best_scale_ok",
            "scale_column_absent",
            "fixed_all_baseline",
            "trial0_is_baseline",
            "baseline_train_sharpe",
            "best_train_sharpe",
            "best_oos_sharpe",
        ]
    ].to_string(index=False)
)
print("tuned params per factor:")
for row in rows:
    print(f"  {row['factor']:32s} {row['tuned']}")

carry = [row for row in rows if row["factor"] == "carry_ann"][0]
print(
    "carry_ann baseline reproduces old pipeline:",
    abs(carry["baseline_train_sharpe"] - BASELINE_CARRY_TRAIN) < 1e-12,
    carry["baseline_train_sharpe"],
)

summary_map = dict(zip(summary["factor_name"], summary["best_train_sharpe"]))
mismatch = [
    row["factor"]
    for row in rows
    if abs(summary_map.get(row["factor"], -99) - row["best_train_sharpe"]) > 1e-12
]
print("summary/best_params mismatches:", mismatch or "none")

problems = [
    row["factor"]
    for row in rows
    if not (
        row["complete"] == 60
        and row["best_scale_ok"]
        and row["scale_column_absent"]
        and row["fixed_all_baseline"]
        and row["trial0_is_baseline"]
        and row["best_factor_parquet"]
    )
]
print("VERIFY", "OK" if not problems and not mismatch else f"FAILED {problems}")
