"""Audit top delivery-month curve signals for tenor and curve-fit artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from china_cta.research.curve_seasonality import (
    annual_delivery_month_panel,
    daily_curve_residuals,
)
from china_cta.research.seasonality_robustness import calendar_return_robustness


SPECS = (
    ("linear_30_540_5c", 1, 30, 540, 5, 0),
    ("quadratic_30_540_5c", 2, 30, 540, 5, 0),
    ("linear_60_365_4c", 1, 60, 365, 4, 0),
    ("linear_liquid_0p1pct_5c", 1, 30, 540, 5, 0.001),
    ("quadratic_liquid_0p1pct_5c", 2, 30, 540, 5, 0.001),
    ("liquid_0p1pct_30_540_4c", 1, 30, 540, 4, 0.001),
    ("liquid_0p5pct_30_540_4c", 1, 30, 540, 4, 0.005),
    ("liquid_1pct_30_540_4c", 1, 30, 540, 4, 0.01),
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--products", nargs="+", default=["JD", "RU", "M", "RB"])
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--permutations", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20260930)
    args = parser.parse_args()
    files = sorted(args.snapshot_dir.glob("snapshots_*.parquet"))
    if not files:
        parser.error("no snapshots_YYYY.parquet files in snapshot-dir")
    products = {name.strip().upper() for name in args.products}
    snapshots_by_file = []
    for path in files:
        frame = pd.read_parquet(path)
        frame = frame.loc[frame["underlying_symbol"].isin(products)].copy()
        if not frame.empty:
            frame["trading_date"] = pd.to_datetime(frame["trading_date"]).dt.normalize()
            snapshots_by_file.append(frame)
    if not snapshots_by_file:
        raise RuntimeError("requested products have no snapshot records")
    snapshots = pd.concat(snapshots_by_file, ignore_index=True)
    summary_rows, profile_frames = [], []
    for label, degree, min_days, max_days, min_contracts, liquidity_share in SPECS:
        residual_frames = [daily_curve_residuals(
            frame, min_days_to_maturity=min_days,
            max_days_to_maturity=max_days,
            min_contracts=min_contracts,
            curve_degree=degree,
            min_volume_share=liquidity_share,
            min_open_interest_share=liquidity_share,
        ) for frame in snapshots_by_file]
        residuals = pd.concat(
            [frame for frame in residual_frames if not frame.empty], ignore_index=True
        ) if any(not frame.empty for frame in residual_frames) else pd.DataFrame()
        if residuals.empty:
            continue
        panel = annual_delivery_month_panel(residuals, min_distinct_days=20)
        result, _ = calendar_return_robustness(
            panel.rename(columns={
                "delivery_month": "calendar_month",
                "mean_curve_residual": "log_return",
            }), permutations=args.permutations, seed=args.seed,
        )
        by_product = result.set_index("underlying_symbol")
        curve_dates = residuals.groupby("underlying_symbol")["trading_date"].nunique()
        for product in sorted(products):
            row = by_product.loc[product] if product in by_product.index else None
            summary_rows.append({
                "spec": label, "underlying_symbol": product,
                "curve_dates": int(curve_dates.get(product, 0)),
                "tested_years": int(row["tested_years"]) if row is not None else 0,
                "tested_months": int(row["tested_months"]) if row is not None else 0,
                "oos_seasonal_r2": row["oos_seasonal_r2"] if row is not None else float("nan"),
                "positive_gain_years": int(row["positive_gain_years"]) if row is not None else 0,
                "permutation_p": row["permutation_p"] if row is not None else float("nan"),
            })
        profiles = residuals.merge(
            snapshots[["trading_date", "underlying_symbol", "order_book_id", "volume", "open_interest"]],
            on=["trading_date", "underlying_symbol", "order_book_id"],
            how="left", validate="many_to_one",
        ).groupby(["underlying_symbol", "delivery_month"]).agg(
            contract_observations=("curve_residual", "size"),
            mean_residual=("curve_residual", "mean"),
            median_tenor_days=("days_to_maturity", "median"),
            median_volume=("volume", "median"),
            median_open_interest=("open_interest", "median"),
        ).reset_index()
        profiles.insert(0, "spec", label)
        profile_frames.append(profiles)
        print(f"{label}: {len(residuals)} contract-day residuals")
    output = args.output_dir or args.snapshot_dir / "curve_seasonality_audit"
    output.mkdir(parents=True, exist_ok=True)
    summary = pd.DataFrame(summary_rows)
    profiles = pd.concat(profile_frames, ignore_index=True)
    summary.to_csv(output / "sensitivity.csv", index=False, encoding="utf-8-sig")
    profiles.to_csv(output / "delivery_month_profiles.csv", index=False, encoding="utf-8-sig")
    print(summary.to_string(index=False))
    print(f"Saved to {output}")


if __name__ == "__main__":
    main()
