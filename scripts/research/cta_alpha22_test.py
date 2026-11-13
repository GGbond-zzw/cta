"""Backtest the 22-factor CTA alpha catalog on the fixed 30-product pool.

Inputs are the cached panels produced by ``fetch_cta_alpha_inputs.py``. Every
available factor is passed through the project's Phase 4 fast research
backtest with one-session execution lag and a 1 bp turnover-cost proxy.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from china_cta.data.fixed_universe import DEFAULT_FIXED_POOL_FILE, load_fixed_product_pool
from china_cta.factors.classification import classification, result_root
from china_cta.factors.cta_catalog import (
    AVAILABLE_FACTORS,
    FACTOR_SPECS,
    UNAVAILABLE_FACTORS,
    build_all,
    spec_table,
)
from china_cta.research.fast_backtest import (
    run_fast_research_backtest,
    save_research_run,
)


INPUT_DIR = Path("data/research_inputs/cta_alpha22")
DEFAULT_START = "2016-01-01"
DEFAULT_END = "2026-01-01"
COST_RATE = 0.0001
EXECUTION_LAG = 1


def load_inputs(input_dir: Path) -> dict[str, pd.DataFrame]:
    paths = {
        "continuous_prices": input_dir / "continuous_prices.parquet",
        "contract_snapshots": input_dir / "contract_snapshots.parquet",
        "dominant_map": input_dir / "dominant_map.parquet",
        "warehouse_stocks": input_dir / "warehouse_stocks.parquet",
        "member_rank": input_dir / "member_rank.parquet",
        "universe": input_dir / "universe.parquet",
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Missing cached inputs: "
            + ", ".join(missing)
            + ". Run scripts/fetch_cta_alpha_inputs.py first."
        )
    inputs = {key: pd.read_parquet(path) for key, path in paths.items()}
    inputs["continuous_prices"].attrs.update(
        {
            "usage": "signal_research_only",
            "cash_pnl_allowed": False,
            "adjust_type": "pre",
            "adjust_method": "prev_close_ratio",
        }
    )
    return inputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=INPUT_DIR)
    parser.add_argument("--products-file", type=Path, default=DEFAULT_FIXED_POOL_FILE)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--only",
        default="",
        help="comma-separated factor names; default is every available factor",
    )
    args = parser.parse_args()

    pool = load_fixed_product_pool(args.products_file)
    products = list(pool.products)
    inputs = load_inputs(args.input_dir)
    prices = inputs["continuous_prices"]
    universe = inputs["universe"]
    if not set(prices["underlying_symbol"]) <= set(products):
        raise RuntimeError("continuous prices contain products outside the fixed pool")
    if not set(universe["instrument"]) <= set(products):
        raise RuntimeError("universe contains products outside the fixed pool")

    print("Building 18 available factors", flush=True)
    factors, unavailable = build_all(
        continuous_prices=prices,
        contract_snapshots=inputs["contract_snapshots"],
        dominant_map=inputs["dominant_map"],
        warehouse_stocks=inputs["warehouse_stocks"],
        member_rank=inputs["member_rank"],
        universe=universe,
    )
    selected = set(AVAILABLE_FACTORS)
    if args.only:
        requested = {name.strip() for name in args.only.split(",") if name.strip()}
        unknown = requested - set(AVAILABLE_FACTORS)
        if unknown:
            raise ValueError(f"unknown or unavailable factors: {sorted(unknown)}")
        selected &= requested
    print(f"Selected {len(selected)} factors: {','.join(sorted(selected))}", flush=True)

    if not args.overwrite:
        existing = [
            name
            for name in selected
            if (result_root(name) / f"{name}_2016_2025_v1").exists()
        ]
        if existing:
            raise FileExistsError(
                "Existing results require --overwrite: " + ", ".join(sorted(existing))
            )

    specs = {spec.name: spec for spec in FACTOR_SPECS}
    metadata = json.loads((args.input_dir / "metadata.json").read_text(encoding="utf-8"))
    universe_settings = {
        "products": products,
        "fixed_pool_source": str(pool.source_file),
        "fixed_pool_holding_month": pool.holding_month,
        "fixed_pool_applied_to_entire_backtest": True,
        "ex_post_selection_bias": True,
        "min_listing_history_days": 60,
        "min_volume": 1000,
        "min_open_interest": 1000,
        "requested_start": DEFAULT_START,
        "requested_end": DEFAULT_END,
        "input_dir": str(args.input_dir),
        "source_repository": metadata.get("source_repository"),
    }

    summary_rows: list[dict[str, object]] = []
    completed: list[str] = []
    for name in [spec.name for spec in FACTOR_SPECS if spec.name in selected]:
        factor = factors[name]
        spec = specs[name]
        print(f"Backtesting {name}", flush=True)
        result = run_fast_research_backtest(
            factor,
            prices,
            universe,
            execution_lag=EXECUTION_LAG,
            cost_rate=COST_RATE,
        )
        run_name = f"{name}_2016_2025_v1"
        factor_parameters = {
            "family": spec.family,
            "formula": spec.formula,
            "inputs": list(spec.inputs),
            "direction_prior": spec.direction,
            "signal_scale": spec.signal_scale,
            "proxy": spec.proxy,
            "source_repository": metadata.get("source_repository"),
        }
        for key in (
            "definition",
            "lookback_trading_periods",
            "skip_trading_periods",
            "volatility_window",
            "min_days_to_maturity",
            "roll_window",
            "top_n",
            "reference_deviation",
            "proxy_note",
            "source",
        ):
            if key in factor.attrs:
                factor_parameters[key] = factor.attrs[key]
        save_research_run(
            result,
            run_name,
            overwrite=args.overwrite,
            factor_parameters=factor_parameters,
            signal_normalization_parameters={"signal_scale": spec.signal_scale},
            universe_settings=universe_settings,
            output_root=result_root(name),
        )
        row = {
            "run": run_name,
            "factor_name": name,
            "classification": classification(name),
            "available": True,
            "status": "completed",
            **result["overall"].iloc[0].to_dict(),
        }
        summary_rows.append(row)
        completed.append(run_name)
        print(
            f"Saved {run_name}: net={row['annualized_net_signal_return']:.4f} "
            f"sharpe={row['sharpe']:.3f}",
            flush=True,
        )

    for spec in FACTOR_SPECS:
        if spec.name in selected:
            continue
        summary_rows.append(
            {
                "run": f"{spec.name}_"
                + ("unavailable" if not spec.available else "not_selected"),
                "factor_name": spec.name,
                "classification": classification(spec.name),
                "available": spec.available,
                "status": "unavailable" if not spec.available else "not_selected",
                "reason": spec.reason if not spec.available else None,
            }
        )

    summary = pd.DataFrame(summary_rows)
    summary["available"] = summary["available"].astype(bool)
    summary["result_path"] = [
        str(result_root(row.factor_name) / row.run)
        if row.status == "completed"
        else None
        for row in summary.itertuples()
    ]
    summary.to_csv("results/cta_alpha22_summary.csv", index=False)
    specs_frame = spec_table()
    specs_frame["classification"] = specs_frame["factor_name"].map(classification)
    specs_frame.to_csv("results/cta_alpha22_specs.csv", index=False)
    manifest = {
        "source_repository": metadata.get("source_repository"),
        "fetched_at_utc": metadata.get("fetched_at_utc"),
        "universe": universe_settings,
        "result_layout": {
            "qualified": "results/qualified",
            "unqualified": "results/unqualified",
        },
        "backtest_standard": {
            "cost_rate": COST_RATE,
            "execution_lag": EXECUTION_LAG,
            "annualization_factor": 252,
            "return_definition": (
                "ratio_adjusted_dominant_next_open_to_next_open_after_close_signal"
            ),
        },
        "factor_count": len(FACTOR_SPECS),
        "available_count": len(AVAILABLE_FACTORS),
        "completed": completed,
        "unavailable": unavailable,
        "classification": {
            spec.name: classification(spec.name) for spec in FACTOR_SPECS
        },
        "specs": specs_frame.to_dict(orient="records"),
        "input_shapes": metadata.get("shapes"),
        "member_rank_failures": metadata.get("member_rank_failures"),
    }
    Path("results/cta_alpha22_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Completed {len(completed)} factors", flush=True)
    print(summary.loc[summary["available"].eq(True), ["factor_name", "sharpe", "max_drawdown"]].to_string(index=False))


if __name__ == "__main__":
    main()
