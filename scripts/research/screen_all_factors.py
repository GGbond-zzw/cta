"""Backtest every buildable factor in the project with next-open execution.

Two factor families are covered:

* the 22-factor alpha catalog (``china_cta.factors.cta_catalog``), 18 of which
  are buildable from the cached panels and 4 of which have no data source;
* the eight hand-written factor modules in ``china_cta.factors.qualified`` and
  ``china_cta.factors.unqualified`` (the "current definitions" rerun by
  ``scripts/rerun_all_factors.py``).

Every factor is evaluated by ``run_fast_research_backtest`` with
``execution_price_field="open"``, one-session lag, a 1bp one-way turnover cost
and 252-period annualization, over 2016-01-04..2025-12-31, and both the whole
window and 2025 are reported.

Usage:
    python all_factors_open.py --processes 4
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))

from china_cta.factors import cta_catalog  # noqa: E402
from china_cta.factors.classification import classification  # noqa: E402
from china_cta.factors.qualified.fixed_maturity_carry import (  # noqa: E402
    compute_curve_carry_factor,
)
from china_cta.factors.qualified.historical_skewness_cs import (  # noqa: E402
    compute_historical_skewness_factor_cs_rank,
)
from china_cta.factors.qualified.oi_participation_trend import (  # noqa: E402
    compute_oi_participation_trend_factor,
)
from china_cta.factors.unqualified.aggregate_oi import (  # noqa: E402
    compute_aggregate_oi_growth_factor,
)
from china_cta.factors.unqualified.basis_momentum import (  # noqa: E402
    compute_basis_momentum_factor,
)
from china_cta.factors.unqualified.consistent_trend import (  # noqa: E402
    compute_consistent_trend_factor,
)
from china_cta.factors.unqualified.historical_skewness import (  # noqa: E402
    compute_historical_skewness_factor,
)
from china_cta.factors.unqualified.multi_horizon_trend import (  # noqa: E402
    compute_multi_horizon_trend_factor,
)
from china_cta.research import bayesian_tuning as bt  # noqa: E402
from china_cta.research import fast_backtest as fb  # noqa: E402

INPUT_DIR = PROJECT / "data" / "research_inputs" / "cta_alpha22"
OUT_DIR = PROJECT / "results" / "all_factors_open"

TEN_YEAR = ("2016-01-04", "2025-12-31")
Y2025 = ("2025-01-01", "2025-12-31")

MODULE_FACTORS: tuple[str, ...] = (
    "aggregate_oi_growth_20d",
    "basis_momentum_252d",
    "fixed_maturity_carry_90_180d",
    "historical_skewness_252d",
    "historical_skewness_252d_cs_rank",
    "multi_trend_20_60_120_252d",
    "oi_participation_trend_60d",
    "consistent_trend_63_126_252d_5r",
)

CATALOG_FACTORS: tuple[str, ...] = tuple(cta_catalog.AVAILABLE_FACTORS)
# Catalog entries whose data source is missing; the builders exist but raise
# ``FactorDataUnavailable``.  They are attempted so the report can state why.
CATALOG_UNAVAILABLE: tuple[str, ...] = tuple(cta_catalog.UNAVAILABLE_FACTORS)
CATALOG_AVAILABLE: tuple[str, ...] = tuple(
    name for name in CATALOG_FACTORS if name not in CATALOG_UNAVAILABLE
)
ALL_FACTORS: tuple[str, ...] = MODULE_FACTORS + CATALOG_FACTORS

_SPECS = {spec.name: spec for spec in cta_catalog.FACTOR_SPECS}
_INPUTS: dict[str, pd.DataFrame] | None = None


def _init_worker() -> None:
    global _INPUTS
    _INPUTS = bt.load_inputs(INPUT_DIR)


def _build_module_factor(name: str) -> pd.DataFrame:
    assert _INPUTS is not None
    prices = _INPUTS["continuous_prices"]
    snapshots = _INPUTS["contract_snapshots"]
    universe = _INPUTS["universe"]
    builders = {
        "aggregate_oi_growth_20d": lambda: compute_aggregate_oi_growth_factor(
            snapshots, universe, lookback=20, minimum_contracts=2, signal_scale=0.20
        ),
        "basis_momentum_252d": lambda: compute_basis_momentum_factor(
            snapshots, universe, lookback=252, min_days_to_maturity=60, signal_scale=0.20
        ),
        "fixed_maturity_carry_90_180d": lambda: compute_curve_carry_factor(
            snapshots, universe
        ),
        "historical_skewness_252d": lambda: compute_historical_skewness_factor(
            prices, universe, lookback=252, signal_scale=1.0
        ),
        "historical_skewness_252d_cs_rank": lambda: (
            compute_historical_skewness_factor_cs_rank(prices, universe, lookback=252)
        ),
        "multi_trend_20_60_120_252d": lambda: compute_multi_horizon_trend_factor(
            prices,
            universe,
            horizons=(20, 60, 120, 252),
            volatility_lookback=60,
            signal_scale=1.0,
        ),
        "oi_participation_trend_60d": lambda: compute_oi_participation_trend_factor(
            prices, snapshots, universe, signal_scale=0.50
        ),
        "consistent_trend_63_126_252d_5r": lambda: compute_consistent_trend_factor(
            prices, universe, signal_scale=0.50
        ),
    }
    return builders[name]()


def _run_factor(name: str) -> dict[str, object]:
    assert _INPUTS is not None
    if name in MODULE_FACTORS:
        factor = _build_module_factor(name)
        family = "module"
        scale = factor.attrs.get("signal_scale", 1.0)
        params = {
            key: value
            for key, value in factor.attrs.items()
            if key
            not in {
                "signal_scale",
                "information_date",
                "signal_available_at",
                "earliest_trade_at",
                "signal_is_position",
            }
        }
    else:
        builder = cta_catalog.BUILDERS[name]
        factor = builder(_INPUTS)
        spec = _SPECS[name]
        if name in CATALOG_UNAVAILABLE:
            raise RuntimeError(f"catalog marks {name} unavailable: {spec.reason}")
        family = spec.family
        scale = spec.signal_scale
        params = {
            "family": spec.family,
            "formula": spec.formula,
            "inputs": list(spec.inputs),
            "direction_prior": spec.direction,
            "proxy": spec.proxy,
            "signal_scale": spec.signal_scale,
        }

    result = fb.run_fast_research_backtest(
        factor,
        _INPUTS["continuous_prices"],
        _INPUTS["universe"],
        execution_lag=bt.EXECUTION_LAG,
        cost_rate=bt.COST_RATE,
        execution_price_field="open",
        include_breakdowns=True,
    )
    detail = result["detail"].loc[
        :,
        [
            "signal_date",
            "instrument",
            "realization_date",
            "net_signal_return",
            "gross_signal_return",
            "rough_cost",
            "turnover_proxy",
            "signal",
            "raw_factor",
            "research_forward_return",
        ],
    ].copy()
    detail["realization_date"] = pd.to_datetime(detail["realization_date"])
    return {
        "name": name,
        "family": family,
        "scale": float(scale),
        "params": params,
        "overall": result["overall"],
        "by_year": result["by_year"],
        "by_instrument": result["by_instrument"],
        "metadata": result["metadata"],
        "detail": detail,
    }


def _window_metrics(detail: pd.DataFrame, window: tuple[str, str]) -> dict[str, object]:
    start, end = (pd.Timestamp(value) for value in window)
    subset = detail.loc[detail["realization_date"].between(start, end)]
    if subset.empty:
        raise ValueError(f"no observations inside {window}")
    return fb._metric_row(subset.copy(), 252)


def _row(item: dict[str, object], label: str, metrics: dict[str, object]) -> dict[str, object]:
    return {
        "factor_name": item["name"],
        "family": item["family"],
        "classification": classification(item["name"]),
        "window": label,
        "signal_scale": item["scale"],
        "observations": int(metrics["observations"]),
        "periods": int(metrics["periods"]),
        "sharpe": float(metrics["sharpe"]),
        "annualized_net_signal_return": float(metrics["annualized_net_signal_return"]),
        "annualized_volatility": float(metrics["annualized_volatility"]),
        "max_drawdown": float(metrics["max_drawdown"]),
        "mean_turnover_proxy": float(metrics["mean_turnover_proxy"]),
        "cumulative_net_signal_return": float(metrics["cumulative_net_signal_return"]),
        "ic": float(metrics["ic"]),
        "rank_ic": float(metrics["rank_ic"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--processes", type=int, default=4)
    parser.add_argument("--only", default="")
    args = parser.parse_args()

    targets = ALL_FACTORS
    if args.only:
        requested = [part.strip() for part in args.only.split(",") if part.strip()]
        unknown = sorted(set(requested) - set(ALL_FACTORS))
        if unknown:
            raise ValueError(f"unknown factors: {unknown}")
        targets = tuple(requested)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"factors to run: {len(targets)}", flush=True)

    rows: list[dict[str, object]] = []
    failures: dict[str, str] = {}
    if args.only:
        ordered = targets
    else:
        ordered = MODULE_FACTORS + CATALOG_AVAILABLE + CATALOG_UNAVAILABLE
    with ProcessPoolExecutor(
        max_workers=args.processes, initializer=_init_worker
    ) as pool:
        from concurrent.futures import as_completed

        futures = {pool.submit(_run_factor, name): name for name in ordered}
        for future in as_completed(futures):
            name = futures[future]
            try:
                item = future.result()
            except Exception as error:  # noqa: BLE001
                failures[name] = f"{type(error).__name__}: {error}"
                print(f"FAILED {name}: {failures[name]}", flush=True)
                continue
            overall = item["overall"].iloc[0]
            print(
                f"done {name:<34} 10y sharpe={overall['sharpe']:.4f} "
                f"ann={overall['annualized_net_signal_return']:.4f} "
                f"vol={overall['annualized_volatility']:.4f}",
                flush=True,
            )
            ten = _window_metrics(item["detail"], TEN_YEAR)
            y25 = _window_metrics(item["detail"], Y2025)
            rows.append(_row(item, "10y", ten))
            rows.append(_row(item, "2025", y25))

            fb.save_research_run(
                {
                    "overall": item["overall"],
                    "by_year": item["by_year"],
                    "by_instrument": item["by_instrument"],
                    "metadata": item["metadata"],
                },
                f"{name}_open_v1",
                factor_parameters=item["params"],
                signal_normalization_parameters={"signal_scale": item["scale"]},
                universe_settings={
                    "input_dir": str(INPUT_DIR),
                    "universe": "point_in_time_eligible_from_research_inputs",
                    "execution_lag_sessions": bt.EXECUTION_LAG,
                    "execution_price_field": "open",
                    "signal_price_field": "close",
                    "cost_rate": bt.COST_RATE,
                    "annualization_factor": 252,
                    "window": {"start": TEN_YEAR[0], "end": TEN_YEAR[1]},
                },
                output_root=OUT_DIR,
                overwrite=True,
            )

    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.sort_values(["window", "sharpe"], ascending=[True, False])
        frame.to_csv(OUT_DIR / "all_factors_summary.csv", index=False, float_format="%.17g")

    unavailable = [
        {
            "factor_name": spec.name,
            "family": spec.family,
            "reason": spec.reason,
        }
        for spec in cta_catalog.FACTOR_SPECS
        if not spec.available
    ]
    manifest = {
        "run_type": "all_factors_open_execution",
        "factor_count": len(targets),
        "completed": sorted({item["factor_name"] for item in rows}) if rows else [],
        "failures": failures,
        "unavailable_catalog_factors": unavailable,
        "execution_price_field": "open",
        "signal_price_field": "close",
        "execution_lag": bt.EXECUTION_LAG,
        "cost_rate": bt.COST_RATE,
        "annualization_factor": 252,
        "window": {"start": TEN_YEAR[0], "end": TEN_YEAR[1]},
        "note": (
            "catalog factors use their catalog signal_scale; module factors use the "
            "definitions from scripts/rerun_all_factors.py; no leverage and no "
            "portfolio volatility targeting (signal clipped to [-1, 1] per instrument)"
        ),
    }
    (OUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if not frame.empty:
        ten = frame[frame["window"].eq("10y")].sort_values("sharpe", ascending=False)
        print("\n=== 10-year ranking (2016-2025, next-open fills) ===")
        print(
            ten[
                [
                    "factor_name",
                    "family",
                    "sharpe",
                    "annualized_net_signal_return",
                    "annualized_volatility",
                    "max_drawdown",
                ]
            ].to_string(index=False)
        )
        y25 = frame[frame["window"].eq("2025")].sort_values("sharpe", ascending=False)
        print("\n=== 2025 ranking ===")
        print(
            y25[["factor_name", "sharpe", "annualized_net_signal_return"]].to_string(
                index=False
            )
        )
    print(f"\nwrote {OUT_DIR / 'all_factors_summary.csv'}")
    return 0 if not failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
