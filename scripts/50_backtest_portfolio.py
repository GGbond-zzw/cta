"""Formal multi-factor backtest plus equal-weight (or weighted) combinations.

Every sleeve is rebuilt from its tuning optimum with the project's own
``bayesian_tuning.build_factor`` and evaluated by the canonical
``fast_backtest.run_fast_research_backtest`` engine (next-open fills, 1bp
one-way turnover cost, 252-period annualization), so the numbers sit on the same
footing as ``results/qualified/*_2016_2025_v1``.

The combination is a capital-weighted sleeve portfolio: each factor gets its
weight of capital, every sleeve keeps its own positions and its own turnover
cost, and the portfolio return on a date is the weighted sum of the sleeve
returns.

Usage (single combination, keeps the original four-factor default):

    python final_backtest_4f.py --processes 3

    python final_backtest_4f.py \
        --factors historical_skewness_252d_cs_rank,fixed_maturity_carry_90_180d \
        --weights 0.5,0.5 --run-name half_half --out-dir results/final_2f

Usage (several combinations sharing one factor build pass):

    python final_backtest_4f.py --processes 5 --out-dir results/final_4f_swap \
        --specs-file swap_specs.json

where ``swap_specs.json`` is a list of
``{"run_name": ..., "factors": [...], "weights": [...]}`` objects.

Volatility targeting (extra run next to the unlevered one):

    python final_backtest_4f.py --processes 5 --specs-file vol_specs.json \
        --out-dir results/final_4f_vol20 --vol-target 0.20 --vol-window 60

The leverage applied on a date is ``vol_target / trailing 60-day annualized
vol`` of the unlevered portfolio return as of the previous day (no look-ahead),
capped by ``--vol-max-leverage``; positions, turnover and cost are scaled by the
same factor, and financing cost is not modelled.  Both the ten-year window
(2016-01-04 .. 2025-12-31) and the 2025 window are reported for every sleeve and
every combination.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from china_cta.research import bayesian_tuning as bt  # noqa: E402
from china_cta.research import fast_backtest as fb  # noqa: E402

INPUT_DIR = PROJECT / "data" / "research_inputs" / "cta_alpha22"
DEFAULT_TUNED_DIR = PROJECT / "results" / "tuning" / "qualified4_300"
DEFAULT_OUT_DIR = PROJECT / "results" / "final_4f"

DEFAULT_FACTORS: tuple[str, ...] = (
    "historical_skewness_252d_cs_rank",
    "fixed_maturity_carry_90_180d",
    "xsmom_252_21",
    "oi_participation_trend_60d",
)
DEFAULT_RUN_NAME = "equal_weight_4f"

TRAIN_START, TRAIN_END = "2016-01-04", "2021-12-31"
TEN_YEAR = ("2016-01-04", "2025-12-31")
Y2025 = ("2025-01-01", "2025-12-31")

SLIM_COLUMNS = (
    "signal_date",
    "instrument",
    "realization_date",
    "research_forward_return",
    "raw_factor",
    "signal",
    "gross_signal_return",
    "net_signal_return",
    "rough_cost",
    "turnover_proxy",
)

_WEIGHTED_COLUMNS = (
    "raw_factor",
    "signal",
    "gross_signal_return",
    "net_signal_return",
    "rough_cost",
    "turnover_proxy",
)

_INPUTS: dict[str, pd.DataFrame] | None = None


def _init_worker(input_dir: str) -> None:
    global _INPUTS
    _INPUTS = bt.load_inputs(Path(input_dir))


def _run_sleeve(job: tuple[str, str]) -> dict[str, object]:
    name, tuned_dir_text = job
    assert _INPUTS is not None
    tuned_dir = Path(tuned_dir_text)
    payload = json.loads((tuned_dir / name / "best_params.json").read_text(encoding="utf-8"))
    params = payload["best_params"]
    factor = bt.build_factor(name, params, _INPUTS)
    result = fb.run_fast_research_backtest(
        factor,
        _INPUTS["continuous_prices"],
        _INPUTS["universe"],
        execution_lag=bt.EXECUTION_LAG,
        cost_rate=bt.COST_RATE,
        include_breakdowns=True,
    )
    detail = result["detail"].loc[:, list(SLIM_COLUMNS)].copy()
    detail["realization_date"] = pd.to_datetime(detail["realization_date"])
    return {
        "name": name,
        "params": params,
        "factor_attrs": dict(factor.attrs),
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


def _combine(
    details: dict[str, pd.DataFrame], weights: dict[str, float]
) -> pd.DataFrame:
    parts = []
    for name, detail in details.items():
        piece = detail.copy()
        weight = weights[name]
        for column in _WEIGHTED_COLUMNS:
            piece[column] = piece[column] * weight
        parts.append(piece)
    long = pd.concat(parts, ignore_index=True)
    grouped = long.groupby(["signal_date", "instrument"], sort=True)
    combo = grouped.agg(
        realization_date=("realization_date", "first"),
        research_forward_return=("research_forward_return", "first"),
        raw_factor=("raw_factor", "sum"),
        signal=("signal", "sum"),
        gross_signal_return=("gross_signal_return", "sum"),
        net_signal_return=("net_signal_return", "sum"),
        rough_cost=("rough_cost", "sum"),
        turnover_proxy=("turnover_proxy", "sum"),
    )
    return combo.reset_index()


def _summary_row(
    run: str, label: str, metrics: dict[str, object], weight: float
) -> dict[str, object]:
    return {
        "run": run,
        "label": label,
        "weight": weight,
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


def _daily_cost(detail: pd.DataFrame) -> pd.DataFrame:
    """Collapse a detail frame to one row per date with gross/net/cost/turnover."""

    grouped = detail.groupby("realization_date", sort=True)
    frame = pd.DataFrame(
        {
            "gross": grouped["gross_signal_return"].mean(),
            "net": grouped["net_signal_return"].mean(),
            "cost": grouped["rough_cost"].mean(),
            "turnover": grouped["turnover_proxy"].mean(),
        }
    )
    return frame.dropna(how="all")


def _cost_rows(
    run: str,
    scope: str,
    frame: pd.DataFrame,
    window: tuple[str, str],
    cost_rate: float,
) -> list[dict[str, object]]:
    """Trading-cost accounting for one sleeve or one combination."""

    start, end = (pd.Timestamp(value) for value in window)
    subset = frame.loc[frame.index.to_series().between(start, end)]
    if subset.empty:
        return []

    rows: list[dict[str, object]] = []

    def summarise(period: str, chunk: pd.DataFrame) -> None:
        days = int(len(chunk))
        years = days / 252.0
        gross = float(chunk["gross"].sum())
        net = float(chunk["net"].sum())
        cost = float(chunk["cost"].sum())
        turnover = float(chunk["turnover"].sum())
        volatility = (
            float(chunk["net"].std(ddof=1)) * (252**0.5) if days > 1 else float("nan")
        )
        annual_cost = cost / years if years else float("nan")
        rows.append(
            {
                "run": run,
                "scope": scope,
                "period": period,
                "days": days,
                "gross_return": gross,
                "net_return": net,
                "total_cost": cost,
                "annualized_cost": annual_cost,
                "cost_share_of_gross": cost / gross if gross else float("nan"),
                "cost_over_volatility": annual_cost / volatility if volatility else float("nan"),
                "total_turnover": turnover,
                "mean_daily_turnover": turnover / days if days else float("nan"),
                "implied_cost_bps": cost / turnover * 1e4 if turnover else float("nan"),
                "cost_rate_bps": cost_rate * 1e4,
                "annualized_volatility": volatility,
            }
        )

    summarise("window", subset)
    for year, chunk in subset.groupby(subset.index.year, sort=True):
        summarise(str(int(year)), chunk)
    return rows


def _resolve_specs(args: argparse.Namespace) -> list[dict[str, object]]:
    if args.specs_file:
        payload = json.loads(Path(args.specs_file).read_text(encoding="utf-8"))
        specs: list[dict[str, object]] = []
        for entry in payload:
            factors = tuple(entry["factors"])
            weights = entry.get("weights")
            specs.append(
                {
                    "run_name": str(entry["run_name"]),
                    "factors": factors,
                    "weights": _normalize_weights(factors, weights),
                }
            )
        return specs

    factors = tuple(item.strip() for item in args.factors.split(",") if item.strip())
    weights = None
    if args.weights:
        weights = [float(item) for item in args.weights.split(",") if item.strip()]
    return [
        {
            "run_name": args.run_name,
            "factors": factors,
            "weights": _normalize_weights(factors, weights),
        }
    ]


def _normalize_weights(
    factors: tuple[str, ...], weights: list[float] | None
) -> dict[str, float]:
    if weights is None:
        equal = 1.0 / len(factors)
        return {name: equal for name in factors}
    if len(weights) != len(factors):
        raise SystemExit(
            f"got {len(weights)} weights for {len(factors)} factors: {list(factors)}"
        )
    total = float(sum(weights))
    if total <= 0:
        raise SystemExit(f"weights must be positive, got {weights}")
    return {name: float(weight) / total for name, weight in zip(factors, weights)}


def _scale_combo(
    combo: pd.DataFrame,
    *,
    target: float,
    window: int,
    max_leverage: float,
) -> tuple[pd.DataFrame, pd.Series]:
    """Lever the combination to a volatility target with no look-ahead.

    The leverage applied on date ``t`` is ``target / trailing_vol`` where the
    trailing volatility uses the daily portfolio returns up to ``t - 1`` only,
    so the scaled series is implementable with information available at ``t``.
    Positions, turnover and cost are all scaled by the same factor, which keeps
    the cost accounting consistent with the larger notional.
    """
    if window < 5:
        raise SystemExit(f"--vol-window must be at least 5, got {window}")
    daily = combo.groupby("realization_date", sort=True)["net_signal_return"].mean()
    trailing = (
        daily.rolling(window=window, min_periods=window).std(ddof=1).shift(1)
        * (252 ** 0.5)
    )
    # Zero trailing volatility (a flat sleeve) cannot be scaled up; cap it.
    leverage = (target / trailing.where(trailing.gt(0))).fillna(max_leverage)
    leverage = leverage.where(trailing.notna()).dropna().clip(upper=max_leverage)
    if leverage.empty:
        raise SystemExit(
            f"no date has {window} prior observations; vol targeting impossible"
        )
    scaled = combo.merge(
        leverage.rename("leverage"),
        left_on="realization_date",
        right_index=True,
        how="inner",
    )
    for column in _WEIGHTED_COLUMNS:
        scaled[column] = scaled[column] * scaled["leverage"]
    return scaled.drop(columns=["leverage"]), leverage


def _describe_leverage(leverage: pd.Series, target: float, window: int) -> dict[str, object]:
    return {
        "volatility_target": float(target),
        "volatility_target_window": int(window),
        "volatility_target_basis": "trailing_annualized_std_of_daily_portfolio_return",
        "scaling": "positions_turnover_and_cost_scaled_by_same_leverage",
        "first_scaled_date": str(leverage.index.min().date()),
        "last_scaled_date": str(leverage.index.max().date()),
        "leverage_days": int(leverage.size),
        "leverage_mean": float(leverage.mean()),
        "leverage_median": float(leverage.median()),
        "leverage_min": float(leverage.min()),
        "leverage_max": float(leverage.max()),
        "financing_cost": "not modelled (futures margin interest ignored)",
    }


def _save_combo(
    *,
    run_name: str,
    factors: tuple[str, ...],
    weights: dict[str, float],
    items: dict[str, dict[str, object]],
    combo: pd.DataFrame,
    out_dir: Path,
    tuned_dir: Path,
    universe_settings: dict[str, object],
    config_extra: dict[str, object] | None = None,
    leverage: pd.Series | None = None,
    window: tuple[str, str] = TEN_YEAR,
    label: str = "10y",
) -> tuple[dict[str, object], dict[str, object]]:
    combo_overall = fb._metric_row(combo, 252)
    combo_ten = _window_metrics(combo, window)
    combo_2025 = _window_metrics(combo, Y2025)

    combo_dir = out_dir / run_name
    combo_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([combo_overall], columns=fb.METRIC_COLUMNS).to_csv(
        combo_dir / "overall.csv", index=False, float_format="%.17g"
    )
    fb._year_breakdown(combo, 252).to_csv(
        combo_dir / "by_year.csv", index=False, float_format="%.17g"
    )
    fb._instrument_breakdown(combo, 252).to_csv(
        combo_dir / "by_instrument.csv", index=False, float_format="%.17g"
    )

    components = {}
    for name in factors:
        params = items[name]["params"]
        detail = items[name]["detail"]
        components[name] = {
            "weight": weights[name],
            "factor_parameters": params,
            "signal_scale": float(params["signal_scale"]),
            "train_window": {"start": TRAIN_START, "end": TRAIN_END},
            "ten_year_sharpe": float(_window_metrics(detail, window)["sharpe"]),
            "y2025_sharpe": float(_window_metrics(detail, Y2025)["sharpe"]),
        }

    combo_config = {
        "run_name": run_name,
        "run_type": "capital_weighted_sleeve_portfolio",
        "factor_name": run_name,
        "components": components,
        "aggregation": (
            "capital_weighted_sleeve_sum: portfolio_net_return = sum_i weight_i * "
            "net_signal_return_i; each sleeve keeps its own positions and pays its own "
            "turnover cost before weighting"
        ),
        "cost_rate": bt.COST_RATE,
        "cost_definition": "turnover_proxy * cost_rate per sleeve, charged inside the sleeve",
        "execution_lag": bt.EXECUTION_LAG,
        "execution_price_field": fb.DEFAULT_EXECUTION_PRICE_FIELD,
        "annualization_factor": 252,
        "cross_instrument_aggregation": (
            "mean_of_available_instrument_signal_returns_by_realization_date"
        ),
        "window": {"start": window[0], "end": window[1], "label": label},
        "parameter_source": str(tuned_dir),
        "universe_settings": universe_settings,
        "engine": "china_cta.research.fast_backtest.run_fast_research_backtest",
        "research_only": True,
        "cash_pnl_allowed": False,
        "is_actual_futures_fee": False,
    }
    if config_extra:
        combo_config.update(config_extra)
    (combo_dir / "config.json").write_text(
        json.dumps(combo_config, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    daily = (
        combo.groupby("realization_date", sort=True)["net_signal_return"].mean().dropna()
    )
    daily.to_frame("daily_net_return").to_csv(
        combo_dir / "daily_net_return.csv", float_format="%.17g"
    )
    if leverage is not None:
        leverage.rename("leverage").to_frame().to_csv(
            combo_dir / "leverage.csv", float_format="%.17g"
        )
    return combo_overall, {"ten": combo_ten, "y2025": combo_2025, "daily": daily}


def _plot_comparison(
    *,
    combos: dict[str, dict[str, object]],
    sleeve_equity: pd.DataFrame,
    factors: tuple[str, ...],
    out_dir: Path,
    window: tuple[str, str] = TEN_YEAR,
) -> Path | None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        start, end = window
        fig, axes = plt.subplots(1, 2, figsize=(16, 5.8))
        panel = sleeve_equity.loc[pd.Timestamp(start) : pd.Timestamp(end)]
        wealth = (1.0 + panel.fillna(0.0)).cumprod()
        for name in factors:
            axes[0].plot(wealth.index, wealth[name], linewidth=0.9, alpha=0.6, label=name)
        colours = ["black", "#c0392b", "#2471a3", "#7d3c98"]
        for position, (run_name, record) in enumerate(combos.items()):
            daily = record["daily"].loc[pd.Timestamp(start) : pd.Timestamp(end)]
            curve = (1.0 + daily).cumprod()
            axes[0].plot(
                curve.index,
                curve,
                linewidth=2.4,
                color=colours[position % len(colours)],
                label=run_name,
            )
        axes[0].set_title(f"Net equity, {start} .. {end} (capital weighted sleeves)")
        axes[0].set_yscale("log")
        axes[0].grid(alpha=0.3)
        axes[0].legend(fontsize=7, loc="upper left")

        rebase = max(pd.Timestamp("2025-01-01"), pd.Timestamp(start))
        for position, (run_name, record) in enumerate(combos.items()):
            daily = record["daily"]
            mask = daily.index >= rebase
            curve = (1.0 + daily.loc[mask]).cumprod()
            axes[1].plot(
                curve.index,
                curve,
                linewidth=2.2,
                color=colours[position % len(colours)],
                label=run_name,
            )
        axes[1].set_title(f"net equity rebased at {rebase.date()}")
        axes[1].grid(alpha=0.3)
        axes[1].legend(fontsize=8, loc="upper left")
        fig.autofmt_xdate()
        target = out_dir / "comparison_equity.png"
        try:
            fig.savefig(target, dpi=140, bbox_inches="tight")
        except OSError:
            fig.savefig(target, dpi=140)
        return target
    except Exception as error:  # pragma: no cover
        print(f"plot skipped: {error!r}")
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--processes", type=int, default=3)
    parser.add_argument("--factors", default=",".join(DEFAULT_FACTORS))
    parser.add_argument("--weights", default=None)
    parser.add_argument("--run-name", default=DEFAULT_RUN_NAME)
    parser.add_argument("--specs-file", default=None)
    parser.add_argument("--input-dir", default=str(INPUT_DIR))
    parser.add_argument("--tuned-dir", default=str(DEFAULT_TUNED_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--vol-target", type=float, default=0.0)
    parser.add_argument("--vol-window", type=int, default=60)
    parser.add_argument("--vol-max-leverage", type=float, default=10.0)
    parser.add_argument("--start", default=TEN_YEAR[0])
    parser.add_argument("--end", default=TEN_YEAR[1])
    args = parser.parse_args()

    window = (args.start, args.end)
    label = "10y" if window == TEN_YEAR else "window"
    if window[0] < TRAIN_START:
        raise SystemExit(f"--start cannot precede {TRAIN_START}")

    tuned_dir = Path(args.tuned_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    specs = _resolve_specs(args)

    union: list[str] = []
    for spec in specs:
        for name in spec["factors"]:
            if name not in union:
                union.append(name)

    missing = [name for name in union if not (tuned_dir / name / "best_params.json").exists()]
    if missing:
        available = sorted(path.name for path in tuned_dir.iterdir() if path.is_dir())
        raise SystemExit(
            f"no tuned parameters for {missing} under {tuned_dir}; available: {available}"
        )

    print(f"combinations: {len(specs)} | unique factors: {len(union)}", flush=True)
    for spec in specs:
        print(f"  {spec['run_name']}: {list(spec['factors'])}", flush=True)

    jobs = [(name, str(tuned_dir)) for name in union]
    with ProcessPoolExecutor(
        max_workers=args.processes,
        initializer=_init_worker,
        initargs=(args.input_dir,),
    ) as pool:
        items: dict[str, dict[str, object]] = {}
        for item in pool.map(_run_sleeve, jobs):
            overall = item["overall"].iloc[0]
            print(
                f"backtested {item['name']:<32} sharpe={overall['sharpe']:.4f} "
                f"ann={overall['annualized_net_signal_return']:.4f} "
                f"mdd={overall['max_drawdown']:.4f} obs={int(overall['observations'])}",
                flush=True,
            )
            items[item["name"]] = item

    data_end = max(
        pd.Timestamp(item["detail"]["realization_date"].max()) for item in items.values()
    )
    if pd.Timestamp(window[1]) > data_end:
        print(
            f"WARNING: requested window ends {window[1]} but the research inputs stop at "
            f"{data_end.date()}; every metric below is measured up to {data_end.date()}",
            flush=True,
        )

    universe_settings = {
        "input_dir": args.input_dir,
        "universe": "point_in_time_eligible_from_research_inputs",
        "fixed_pool_applied": False,
        "execution_lag_sessions": bt.EXECUTION_LAG,
        "execution_price_field": fb.DEFAULT_EXECUTION_PRICE_FIELD,
        "cost_rate": bt.COST_RATE,
        "annualization_factor": 252,
        "parameter_source": str(tuned_dir),
        "note": "sleeves rebuilt from tuning best parameters",
    }

    summary: list[dict[str, object]] = []
    for name in union:
        item = items[name]
        params = item["params"]
        fb.save_research_run(
            {
                "overall": item["overall"],
                "by_year": item["by_year"],
                "by_instrument": item["by_instrument"],
                "metadata": item["metadata"],
            },
            f"{name}_tuned300_v1",
            factor_parameters=params,
            signal_normalization_parameters={
                "signal_scale": float(params["signal_scale"]),
                "source": f"{tuned_dir.name} best_trial",
            },
            universe_settings=universe_settings,
            output_root=out_dir,
            overwrite=True,
        )
        ten = _window_metrics(item["detail"], window)
        y25 = _window_metrics(item["detail"], Y2025)
        summary.append(_summary_row(name, label, ten, 1.0))
        summary.append(_summary_row(name, "2025", y25, 1.0))
        print(
            f"saved {name}_tuned300_v1 | {label} {ten['sharpe']:.4f} | "
            f"2025 {y25['sharpe']:.4f}",
            flush=True,
        )

    combos: dict[str, dict[str, object]] = {}
    combo_frames: dict[str, pd.DataFrame] = {}
    for spec in specs:
        run_name = str(spec["run_name"])
        factors = tuple(spec["factors"])
        weights = dict(spec["weights"])  # type: ignore[arg-type]
        combo = _combine({name: items[name]["detail"] for name in factors}, weights)
        record = _save_combo(
            run_name=run_name,
            factors=factors,
            weights=weights,
            items=items,
            combo=combo,
            out_dir=out_dir,
            tuned_dir=tuned_dir,
            universe_settings=universe_settings,
            window=window,
            label=label,
        )[1]
        combos[run_name] = record
        combo_frames[run_name] = combo
        summary.append(_summary_row(run_name, label, record["ten"], 1.0))
        summary.append(_summary_row(run_name, "2025", record["y2025"], 1.0))
        print(
            f"combined {run_name:<24} {label} {record['ten']['sharpe']:.4f} | "
            f"2025 {record['y2025']['sharpe']:.4f}",
            flush=True,
        )

        vol_target = float(spec.get("vol_target") or args.vol_target or 0.0)
        if vol_target > 0:
            scaled, leverage = _scale_combo(
                combo,
                target=vol_target,
                window=args.vol_window,
                max_leverage=args.vol_max_leverage,
            )
            vol_name = f"{run_name}_vol{int(round(vol_target * 100))}"
            extra = _describe_leverage(leverage, vol_target, args.vol_window)
            extra["base_run"] = run_name
            extra["max_leverage_cap"] = float(args.vol_max_leverage)
            extra["capped_days"] = int(
                (leverage >= args.vol_max_leverage - 1e-12).sum()
            )
            vol_record = _save_combo(
                run_name=vol_name,
                factors=factors,
                weights=weights,
                items=items,
                combo=scaled,
                out_dir=out_dir,
                tuned_dir=tuned_dir,
                universe_settings=universe_settings,
                config_extra=extra,
                leverage=leverage,
                window=window,
                label=label,
            )[1]
            combos[vol_name] = vol_record
            combo_frames[vol_name] = scaled
            summary.append(_summary_row(vol_name, label, vol_record["ten"], 1.0))
            summary.append(_summary_row(vol_name, "2025", vol_record["y2025"], 1.0))
            print(
                f"vol-targeted {vol_name:<18} {label} {vol_record['ten']['sharpe']:.4f} "
                f"vol={vol_record['ten']['annualized_volatility']:.4f} | "
                f"2025 {vol_record['y2025']['sharpe']:.4f} "
                f"vol={vol_record['y2025']['annualized_volatility']:.4f} | "
                f"leverage median={extra['leverage_median']:.2f} "
                f"max={extra['leverage_max']:.2f} capped_days={extra['capped_days']}",
                flush=True,
            )

    summary_frame = pd.DataFrame(summary)
    summary_frame.to_csv(out_dir / "final_summary.csv", index=False, float_format="%.17g")

    sleeve_equity = pd.DataFrame(
        {
            name: items[name]["detail"]
            .groupby("realization_date", sort=True)["net_signal_return"]
            .mean()
            for name in union
        }
    ).sort_index()
    sleeve_equity.to_csv(out_dir / "sleeve_daily_net_return.csv", float_format="%.17g")

    comparison = summary_frame.pivot_table(
        index="run",
        columns="label",
        values=[
            "sharpe",
            "annualized_net_signal_return",
            "annualized_volatility",
            "max_drawdown",
            "mean_turnover_proxy",
        ],
    )
    comparison.columns = [f"{metric}_{tag}" for metric, tag in comparison.columns]
    comparison.to_csv(out_dir / "combo_comparison.csv", float_format="%.17g")

    cost_rows: list[dict[str, object]] = []
    for name in union:
        cost_rows += _cost_rows(
            name, "sleeve", _daily_cost(items[name]["detail"]), window, bt.COST_RATE
        )
    for run_name, frame in combo_frames.items():
        cost_rows += _cost_rows(
            run_name, "combo", _daily_cost(frame), window, bt.COST_RATE
        )
    if cost_rows:
        cost_frame = pd.DataFrame(cost_rows)
        cost_frame.to_csv(
            out_dir / "cost_report.csv", index=False, float_format="%.17g"
        )
        print(
            f"\n=== trading cost ({window[0]} .. {window[1]}, "
            f"{bt.COST_RATE * 1e4:.1f} bp per unit turnover) ==="
        )
        print(
            f"{'run':<34}{'scope':<8}{'days':>6}{'gross':>10}{'net':>10}"
            f"{'cost':>9}{'ann_cost':>10}{'cost/gross':>11}{'turn/day':>10}{'implied_bp':>11}"
        )
        for row in cost_frame[cost_frame["period"] == "window"].to_dict("records"):
            print(
                f"{row['run']:<34}{row['scope']:<8}{int(row['days']):>6}"
                f"{row['gross_return']:>10.4f}{row['net_return']:>10.4f}"
                f"{row['total_cost']:>9.4f}{row['annualized_cost']:>10.4f}"
                f"{row['cost_share_of_gross']:>11.4f}"
                f"{row['mean_daily_turnover']:>10.4f}{row['implied_cost_bps']:>11.3f}"
            )

    target = _plot_comparison(
        combos=combos,
        sleeve_equity=sleeve_equity,
        factors=tuple(union),
        out_dir=out_dir,
        window=window,
    )
    if target is not None:
        print(f"\nwrote {target}")

    print(f"\n=== summary ({label}: {window[0]} .. {window[1]} / 2025) ===")
    for run_name in [*union, *combos]:
        ten = summary_frame[
            (summary_frame["run"] == run_name) & (summary_frame["label"] == label)
        ].iloc[0]
        y25 = summary_frame[
            (summary_frame["run"] == run_name) & (summary_frame["label"] == "2025")
        ].iloc[0]
        print(
            f"{run_name:<34} {label} sharpe={ten['sharpe']:.4f} "f"ann={ten['annualized_net_signal_return']:.4f} "
            f"vol={ten['annualized_volatility']:.4f} mdd={ten['max_drawdown']:.4f} | "
            f"2025 sharpe={y25['sharpe']:.4f} ann={y25['annualized_net_signal_return']:.4f} "
            f"mdd={y25['max_drawdown']:.4f}"
        )

    print(f"\nwrote {out_dir / 'final_summary.csv'}")
    print(f"wrote {out_dir / 'combo_comparison.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
