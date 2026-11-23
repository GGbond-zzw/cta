"""Bayesian parameter tuning for the project's qualified single factors.

The study maximizes the training-period net Sharpe of the project's existing
fast research backtest, subject to observation/drawdown/turnover constraints.
The 2022-2025 period is evaluated only after the search and is never used to
select parameters.

The registry below contains exactly the four sleeves of the live book --
``fixed_maturity_carry_90_180d``, ``historical_skewness_252d``,
``oi_participation_trend_60d`` and ``xsmom_252_21``.  Everything else lives in
:mod:`china_cta.factors.unqualified` and is researched through
``scripts/research/rerun_all_factors.py`` instead of being tuned here.

``signal_scale`` is not a search dimension: it only sets the clipping threshold
of ``raw_factor / signal_scale``, i.e. it sizes positions and therefore drives
the turnover cost.  Every factor is tuned with the scale pinned to its baseline
value, which is the value stored in ``results/qualified``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from china_cta.factors.cta_common import cross_sectional_table, standard_table
from china_cta.factors.mined.sleeves import build_mined_factor
from china_cta.factors.cta_curve import calculate_curve_metrics
from china_cta.factors.cta_momentum_base import calculate_time_series_momentum
from china_cta.factors.qualified.fixed_maturity_carry import (
    compute_curve_carry_factor,
)
from china_cta.factors.qualified.historical_skewness import (
    compute_historical_skewness_factor,
)
from china_cta.factors.qualified.oi_participation_trend import (
    compute_oi_participation_trend_factor,
)
from china_cta.research.fast_backtest import run_fast_research_backtest


MINED_TUNING_FACTORS: tuple[str, ...] = (
    "crowded_trend_reversal_60d",
    "volume_burst_vol_reversal_60d",
)

TRAIN_START = "2016-01-04"
TRAIN_END = "2021-12-31"
OOS_START = "2022-01-04"
OOS_END = "2025-12-31"
COST_RATE = 0.0001
EXECUTION_LAG = 1
MIN_OBSERVATIONS = 10_000
MAX_DRAWDOWN = -0.40
MAX_TURNOVER = 0.50

TUNING_INPUT_DIR = Path("data/research_inputs/cta_alpha22")


def load_inputs(input_dir: Path = TUNING_INPUT_DIR) -> dict[str, pd.DataFrame]:
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
        raise FileNotFoundError("Missing tuning inputs: " + ", ".join(missing))
    inputs = {key: pd.read_parquet(path) for key, path in paths.items()}
    flows_path = input_dir / "product_flows.parquet"
    if flows_path.is_file():
        inputs["product_flows"] = pd.read_parquet(flows_path)
    inputs["continuous_prices"].attrs.update(
        {
            "usage": "signal_research_only",
            "cash_pnl_allowed": False,
            "adjust_type": "pre",
            "adjust_method": "prev_close_ratio",
        }
    )
    return inputs


def _window(frame: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    dates = pd.to_datetime(frame["trading_date"], errors="raise")
    mask = dates.between(pd.Timestamp(start), pd.Timestamp(end))
    result = frame.loc[mask].copy()
    result.attrs.update(frame.attrs)
    return result


def _rescale_signal(table: pd.DataFrame, scale: float) -> pd.DataFrame:
    result = table.copy()
    result["signal"] = (pd.to_numeric(result["raw_factor"]) / scale).clip(-1.0, 1.0)
    result.attrs.update(table.attrs)
    result.attrs["signal_scale"] = scale
    return result


def _rename_factor(table: pd.DataFrame, name: str) -> pd.DataFrame:
    table = table.copy()
    table["factor_name"] = name
    table.attrs["factor_name"] = name
    return table


def build_factor(name: str, params: dict[str, Any], inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build one qualified factor with a parameter dictionary."""

    prices = inputs["continuous_prices"]
    snapshots = inputs["contract_snapshots"]
    universe = inputs["universe"]
    scale = float(params["signal_scale"])

    if name == "xsmom_252_21":
        raw = calculate_time_series_momentum(
            prices,
            lookback=int(params["lookback"]),
            skip=int(params["skip"]),
        )
        table = cross_sectional_table(
            raw,
            universe,
            factor_name=name,
            family="B_cross_sectional_momentum",
            definition="per_date_rank_of_tsmom_in_eligible_universe",
            lookback_trading_periods=int(params["lookback"]),
            skip_trading_periods=int(params["skip"]),
            price_field="close",
            adjust_method="prev_close_ratio",
            raw_factor_normalization="cross_sectional_rank_minus1_plus1",
        )
        return _rescale_signal(_rename_factor(table, name), scale)

    if name == "fixed_maturity_carry_90_180d":
        table = compute_curve_carry_factor(
            snapshots,
            universe,
            near_days=int(params["near_days"]),
            far_days=int(params["far_days"]),
            min_days_to_maturity=int(params["min_days_to_maturity"]),
            max_gap_days=int(params["max_gap_days"]),
            signal_scale=scale,
        )
        return _rename_factor(table, name)

    if name == "oi_participation_trend_60d":
        table = compute_oi_participation_trend_factor(
            prices,
            snapshots,
            universe,
            trend_horizons=(63, 126, 252),
            trend_smoothing_span=int(params["trend_smoothing_span"]),
            trend_deadband=float(params["trend_deadband"]),
            trend_volatility_halflife=int(params["trend_volatility_halflife"]),
            trend_target_annualized_volatility=float(
                params["trend_target_annualized_volatility"]
            ),
            oi_growth_lookback=int(params["oi_growth_lookback"]),
            oi_smoothing_span=int(params["oi_smoothing_span"]),
            oi_normalization_lookback=int(params["oi_normalization_lookback"]),
            minimum_oi_observations=int(params["minimum_oi_observations"]),
            minimum_contracts=int(params["minimum_contracts"]),
            rebalance_every=int(params["rebalance_every"]),
            signal_scale=scale,
        )
        return _rename_factor(table, name)

    if name == "historical_skewness_252d":
        table = compute_historical_skewness_factor(
            prices,
            universe,
            lookback=int(params["lookback"]),
            signal_scale=scale,
        )
        return _rename_factor(table, name)

    if name in MINED_TUNING_FACTORS:
        return build_mined_factor(name, params, inputs)

    raise ValueError(f"unknown tuning factor: {name}")


def _backtest_window(
    factor: pd.DataFrame,
    inputs: dict[str, pd.DataFrame],
    start: str,
    end: str,
) -> dict[str, Any]:
    factor_window = _window(factor, start, end)
    if factor_window.empty:
        raise ValueError("factor table is empty in the evaluation window")
    prices = _window(inputs["continuous_prices"], start, end)
    universe = _window(inputs["universe"], start, end)
    result = run_fast_research_backtest(
        factor_window,
        prices,
        universe,
        execution_lag=EXECUTION_LAG,
        cost_rate=COST_RATE,
        include_breakdowns=False,
    )
    overall = result["overall"].iloc[0]
    return {
        "overall": overall.to_dict(),
        "observations": float(overall.get("observations", np.nan)),
        "sharpe": float(overall.get("sharpe", np.nan)),
        "annualized_net": float(
            overall.get("annualized_net_signal_return", np.nan)
        ),
        "annualized_vol": float(overall.get("annualized_volatility", np.nan)),
        "max_drawdown": float(overall.get("max_drawdown", np.nan)),
        "turnover": float(overall.get("mean_turnover_proxy", np.nan)),
        "ic": float(overall.get("ic", np.nan)),
        "rank_ic": float(overall.get("rank_ic", np.nan)),
    }


def evaluate_params(
    name: str,
    params: dict[str, Any],
    inputs: dict[str, pd.DataFrame],
    start: str,
    end: str,
) -> dict[str, Any]:
    factor = build_factor(name, params, inputs)
    return _backtest_window(factor, inputs, start, end)


def _constraint_violation(metrics: dict[str, Any]) -> str | None:
    if not np.isfinite(metrics["sharpe"]):
        return "non_finite_sharpe"
    if metrics["observations"] < MIN_OBSERVATIONS:
        return f"observations_lt_{MIN_OBSERVATIONS}"
    if metrics["max_drawdown"] < MAX_DRAWDOWN:
        return f"max_drawdown_lt_{MAX_DRAWDOWN}"
    if metrics["turnover"] > MAX_TURNOVER:
        return f"turnover_gt_{MAX_TURNOVER}"
    return None


@dataclass(frozen=True)
class TuningSpec:
    """One tunable factor: search space, baseline, and pinned parameters."""

    name: str
    description: str
    baseline: dict[str, Any]
    suggest: Callable[[Any], dict[str, Any]]
    resolve: Callable[[dict[str, Any]], dict[str, Any]]
    fixed: dict[str, Any] = field(default_factory=dict)
    scale_range: tuple[float, float] | None = None


def _resolve_identity(params: dict[str, Any]) -> dict[str, Any]:
    return dict(params)


def _resolve_fixed_carry(params: dict[str, Any]) -> dict[str, Any]:
    resolved = dict(params)
    resolved["far_days"] = int(resolved["near_days"]) + int(resolved.pop("far_offset"))
    return resolved


# ``signal = clip(raw_factor / signal_scale, -1, 1)``: the scale is only the
# clipping threshold, so it sizes positions instead of shaping the signal.  A
# search over it would buy lower turnover cost rather than a better factor, so
# it stays at the baseline value declared in ``TUNING_SPECS``.


def _suggest_xsmom(trial: Any) -> dict[str, Any]:
    lookback = trial.suggest_int("lookback", 126, 504, step=6)
    skip = trial.suggest_int("skip", 0, min(63, lookback - 21))
    return {"lookback": lookback, "skip": skip}


def _suggest_fixed_carry(trial: Any) -> dict[str, Any]:
    near = trial.suggest_int("near_days", 30, 180, step=10)
    offset = trial.suggest_int("far_offset", 60, 240, step=10)
    min_days = trial.suggest_int(
        "min_days_to_maturity", 0, min(60, near - 1)
    )
    max_gap = trial.suggest_int("max_gap_days", 30, 240, step=10)
    return {
        "near_days": near,
        "far_offset": offset,
        "min_days_to_maturity": min_days,
        "max_gap_days": max_gap,
    }


def _suggest_oi_participation(trial: Any) -> dict[str, Any]:
    norm_lookback = trial.suggest_int(
        "oi_normalization_lookback", 126, 504, step=6
    )
    return {
        "trend_smoothing_span": trial.suggest_int(
            "trend_smoothing_span", 3, 30
        ),
        "trend_deadband": trial.suggest_float("trend_deadband", 0.0, 0.20),
        "trend_volatility_halflife": trial.suggest_int(
            "trend_volatility_halflife", 5, 60
        ),
        "trend_target_annualized_volatility": trial.suggest_float(
            "trend_target_annualized_volatility", 0.08, 0.30
        ),
        "oi_growth_lookback": trial.suggest_int("oi_growth_lookback", 20, 120),
        "oi_smoothing_span": trial.suggest_int("oi_smoothing_span", 3, 30),
        "oi_normalization_lookback": norm_lookback,
        "minimum_oi_observations": trial.suggest_int(
            "minimum_oi_observations", 60, norm_lookback
        ),
        "minimum_contracts": trial.suggest_int("minimum_contracts", 2, 4),
        "rebalance_every": trial.suggest_int("rebalance_every", 1, 10),
    }


def _suggest_crowded_trend(trial: Any) -> dict[str, Any]:
    return {
        "trend_window": trial.suggest_int("trend_window", 20, 120, step=10),
        "correlation_window": trial.suggest_int("correlation_window", 20, 120, step=10),
    }


def _suggest_volume_coflow(trial: Any) -> dict[str, Any]:
    return {"correlation_window": trial.suggest_int("correlation_window", 5, 60, step=5)}


def _suggest_volume_burst(trial: Any) -> dict[str, Any]:
    return {
        "smoothing_window": trial.suggest_int("smoothing_window", 20, 120, step=10),
        "correlation_window": trial.suggest_int("correlation_window", 5, 60, step=5),
        "delta_window": trial.suggest_int("delta_window", 5, 60, step=5),
        "volatility_window": trial.suggest_int("volatility_window", 20, 120, step=10),
    }


def _suggest_skew_ts(trial: Any) -> dict[str, Any]:
    return {"lookback": trial.suggest_int("lookback", 63, 504, step=21)}


TUNING_SPECS: dict[str, TuningSpec] = {
    "xsmom_252_21": TuningSpec(
        name="xsmom_252_21",
        description="cross-sectional 12-1 momentum",
        baseline={"lookback": 252, "skip": 21, "signal_scale": 1.0},
        suggest=_suggest_xsmom,
        resolve=_resolve_identity,
        fixed={"signal_scale": 1.0},
    ),
    "fixed_maturity_carry_90_180d": TuningSpec(
        name="fixed_maturity_carry_90_180d",
        description="fixed-maturity 90/180-day carry",
        baseline={
            "near_days": 90,
            "far_offset": 90,
            "min_days_to_maturity": 30,
            "max_gap_days": 120,
            "signal_scale": 0.20,
        },
        suggest=_suggest_fixed_carry,
        resolve=_resolve_fixed_carry,
        fixed={"signal_scale": 0.20},
    ),
    "oi_participation_trend_60d": TuningSpec(
        name="oi_participation_trend_60d",
        description="slow trend scaled by aggregate OI participation",
        baseline={
            "trend_smoothing_span": 10,
            "trend_deadband": 0.05,
            "trend_volatility_halflife": 20,
            "trend_target_annualized_volatility": 0.15,
            "oi_growth_lookback": 60,
            "oi_smoothing_span": 10,
            "oi_normalization_lookback": 252,
            "minimum_oi_observations": 126,
            "minimum_contracts": 2,
            "rebalance_every": 5,
            "signal_scale": 0.50,
        },
        suggest=_suggest_oi_participation,
        resolve=_resolve_identity,
        fixed={"signal_scale": 0.50},
    ),
    "crowded_trend_reversal_60d": TuningSpec(
        name="crowded_trend_reversal_60d",
        description="mined: fade trends pushed by high channel position and volatility",
        baseline={
            "trend_window": 60,
            "correlation_window": 60,
            "signal_scale": 0.7073720289720415,
        },
        suggest=_suggest_crowded_trend,
        resolve=_resolve_identity,
        fixed={"signal_scale": 0.7073720289720415},
    ),
    "volume_burst_vol_reversal_60d": TuningSpec(
        name="volume_burst_vol_reversal_60d",
        description="mined: fade volume bursts that arrive while volatility expands",
        baseline={
            "smoothing_window": 60,
            "correlation_window": 20,
            "delta_window": 20,
            "volatility_window": 60,
            "signal_scale": 0.3029101622490162,
        },
        suggest=_suggest_volume_burst,
        resolve=_resolve_identity,
        fixed={"signal_scale": 0.3029101622490162},
    ),
    "historical_skewness_252d": TuningSpec(
        name="historical_skewness_252d",
        description="absolute historical return skewness",
        baseline={"lookback": 252, "signal_scale": 1.0},
        suggest=_suggest_skew_ts,
        resolve=_resolve_identity,
        fixed={"signal_scale": 1.0},
    ),
}


# The scale search ranges reproduce the bounds used before the scale was
# pinned, so a "scale tuned" study searches exactly the old space.
SCALE_RANGES: dict[str, tuple[float, float]] = {
    "xsmom_252_21": (0.5, 1.0),
    "fixed_maturity_carry_90_180d": (0.05, 0.40),
    "oi_participation_trend_60d": (0.10, 1.0),
    "historical_skewness_252d": (0.5, 1.0),
    "crowded_trend_reversal_60d": (0.30, 1.50),
    "volume_burst_vol_reversal_60d": (0.10, 0.60),
}

SCALE_TUNED_SPECS: dict[str, TuningSpec] = {
    name: replace(spec, fixed={}, scale_range=SCALE_RANGES[name])
    for name, spec in TUNING_SPECS.items()
}

TUNING_SPEC_SETS: dict[str, dict[str, TuningSpec]] = {
    "pinned": TUNING_SPECS,
    "tuned": SCALE_TUNED_SPECS,
}


def _spec_set(tune_scale: bool) -> dict[str, TuningSpec]:
    return SCALE_TUNED_SPECS if tune_scale else TUNING_SPECS


def _suggest_scale(trial: Any, spec: TuningSpec) -> dict[str, Any]:
    """Sample ``signal_scale`` only for the scale-tuned spec set."""

    if spec.scale_range is None:
        return {}
    low, high = spec.scale_range
    return {"signal_scale": trial.suggest_float("signal_scale", low, high)}


def _validated_spec(name: str, *, tune_scale: bool = False) -> TuningSpec:
    """Return a spec, enforcing that its scale handling matches the spec set."""

    spec = _spec_set(tune_scale)[name]
    if spec.scale_range is None:
        if "signal_scale" not in spec.fixed:
            raise RuntimeError(
                f"{name}: signal_scale must be pinned to its baseline"
            )
        for key, value in spec.fixed.items():
            if key not in spec.baseline or spec.baseline[key] != value:
                raise RuntimeError(
                    f"{name}: pinned {key}={value!r} differs from its baseline"
                )
        return spec
    if "signal_scale" in spec.fixed:
        raise RuntimeError(f"{name}: a tuned signal_scale cannot also be pinned")
    low, high = spec.scale_range
    baseline_scale = float(spec.baseline["signal_scale"])
    if not low <= baseline_scale <= high:
        raise RuntimeError(
            f"{name}: baseline signal_scale={baseline_scale!r} is outside"
            f" {spec.scale_range!r}"
        )
    return spec


def _tunable_baseline(spec: TuningSpec) -> dict[str, Any]:
    """Baseline values of the searched parameters only (Optuna rejects extras)."""

    return {
        key: value
        for key, value in spec.baseline.items()
        if key not in spec.fixed
    }


def _validate_specs() -> None:
    for tune_scale in (False, True):
        for name in TUNING_SPECS:
            _validated_spec(name, tune_scale=tune_scale)


_validate_specs()


def objective(
    trial: Any,
    name: str,
    inputs: dict[str, pd.DataFrame],
    *,
    tune_scale: bool = False,
) -> float:
    spec = _validated_spec(name, tune_scale=tune_scale)
    params = spec.resolve(
        {**spec.suggest(trial), **_suggest_scale(trial, spec), **spec.fixed}
    )
    trial.set_user_attr("resolved_params", json.dumps(params, sort_keys=True))
    try:
        metrics = evaluate_params(name, params, inputs, TRAIN_START, TRAIN_END)
    except Exception as exc:  # invalid parameter combinations are regular trials
        trial.set_user_attr("error", f"{type(exc).__name__}: {exc}")
        trial.set_user_attr("constraint_ok", False)
        return -1e9
    for key in (
        "observations",
        "sharpe",
        "annualized_net",
        "annualized_vol",
        "max_drawdown",
        "turnover",
        "ic",
        "rank_ic",
    ):
        trial.set_user_attr(key, metrics[key])
    violation = _constraint_violation(metrics)
    trial.set_user_attr("constraint_ok", violation is None)
    trial.set_user_attr("constraint_violation", violation)
    if violation is not None:
        return -1e9
    return metrics["sharpe"]


def _trial_frame(study: Any, fixed: dict[str, Any]) -> pd.DataFrame:
    records = []
    for trial in study.trials:
        record = {
            "number": trial.number,
            "value": trial.value,
            "state": trial.state.name,
            "duration_seconds": (
                (trial.datetime_complete - trial.datetime_start).total_seconds()
                if trial.datetime_complete is not None
                and trial.datetime_start is not None
                else None
            ),
        }
        record.update({f"param_{key}": value for key, value in trial.params.items()})
        record.update({f"fixed_{key}": value for key, value in fixed.items()})
        for key, value in trial.user_attrs.items():
            record[f"attr_{key}"] = value
        records.append(record)
    return pd.DataFrame(records)


def run_factor_study(
    name: str,
    inputs: dict[str, pd.DataFrame],
    *,
    trials: int,
    workers: int,
    seed: int,
    output_dir: Path,
    tune_scale: bool = False,
    storage: Path | None = None,
) -> dict[str, Any]:
    import optuna
    from optuna.samplers import TPESampler

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    spec = _validated_spec(name, tune_scale=tune_scale)
    factor_dir = output_dir / name
    factor_dir.mkdir(parents=True, exist_ok=True)

    sampler = TPESampler(
        seed=seed,
        multivariate=True,
        group=True,
        n_startup_trials=10,
    )
    study_kwargs: dict[str, Any] = {"direction": "maximize", "sampler": sampler}
    if storage is not None:
        storage = Path(storage)
        storage.parent.mkdir(parents=True, exist_ok=True)
        study_kwargs.update(
            storage=f"sqlite:///{storage.as_posix()}",
            study_name=name,
            load_if_exists=True,
        )
    study = optuna.create_study(**study_kwargs)

    def search(trial: Any) -> float:
        return objective(trial, name, inputs, tune_scale=tune_scale)

    if not study.trials:
        study.enqueue_trial(_tunable_baseline(spec))
    # The enqueued baseline has to run alone: several workers would race
    # for the single waiting trial and Optuna would reject the batch.
    if not any(trial.state.is_finished() for trial in study.trials):
        study.optimize(search, n_trials=1, n_jobs=1, show_progress_bar=False)
    while True:
        finished = sum(
            1 for trial in study.trials if trial.state.is_finished()
        )
        if finished >= trials:
            break
        study.optimize(
            search,
            n_trials=trials - finished,
            n_jobs=workers,
            show_progress_bar=False,
        )
        if sum(1 for trial in study.trials if trial.state.is_finished()) <= finished:
            break

    valid = [
        trial
        for trial in study.trials
        if trial.value is not None and trial.value > -1e8
    ]
    if not valid:
        raise RuntimeError(f"no feasible trial for {name}")
    best = study.best_trial
    best_params = spec.resolve({**best.params, **spec.fixed})
    baseline_params = spec.resolve({**spec.baseline, **spec.fixed})

    train_best = evaluate_params(name, best_params, inputs, TRAIN_START, TRAIN_END)
    oos_best = evaluate_params(name, best_params, inputs, OOS_START, OOS_END)
    train_baseline = evaluate_params(
        name, baseline_params, inputs, TRAIN_START, TRAIN_END
    )
    oos_baseline = evaluate_params(
        name, baseline_params, inputs, OOS_START, OOS_END
    )

    best_factor = _rename_factor(build_factor(name, best_params, inputs), name)
    best_factor.to_parquet(factor_dir / "best_factor.parquet", index=False)
    _trial_frame(study, spec.fixed).to_csv(
        factor_dir / "trials.csv", index=False
    )
    payload = {
        "factor_name": name,
        "description": spec.description,
        "baseline_params": baseline_params,
        "best_params": best_params,
        "tuned_params": sorted(best.params),
        "fixed_params": dict(spec.fixed),
        "scale_policy": "tuned" if spec.scale_range else "pinned",
        "scale_range": list(spec.scale_range) if spec.scale_range else None,
        "best_trial_number": best.number,
        "best_train": train_best,
        "best_oos": oos_best,
        "baseline_train": train_baseline,
        "baseline_oos": oos_baseline,
        "constraints": {
            "min_observations": MIN_OBSERVATIONS,
            "max_drawdown": MAX_DRAWDOWN,
            "max_turnover": MAX_TURNOVER,
        },
        "split": {
            "train": [TRAIN_START, TRAIN_END],
            "oos": [OOS_START, OOS_END],
        },
        "backtest": {
            "execution_lag": EXECUTION_LAG,
            "cost_rate": COST_RATE,
            "annualization_factor": 252,
        },
    }
    (factor_dir / "best_params.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload


def run_all(
    *,
    factors: list[str] | None = None,
    trials: int = 60,
    workers: int = 6,
    seed: int = 42,
    output_dir: Path = Path("results/tuning"),
    input_dir: Path = TUNING_INPUT_DIR,
    tune_scale: bool = False,
    resume: bool = True,
) -> pd.DataFrame:
    specs = _spec_set(tune_scale)
    selected = factors or list(specs)
    unknown = sorted(set(selected) - set(specs))
    if unknown:
        raise ValueError(f"unknown tuning factors: {unknown}")
    inputs = load_inputs(input_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_rows = []
    for name in selected:
        print(f"Tuning {name} ...", flush=True)
        payload = run_factor_study(
            name,
            inputs,
            trials=trials,
            workers=workers,
            seed=seed,
            output_dir=output_dir,
            tune_scale=tune_scale,
            storage=(
                output_dir / name / "study.sqlite3" if resume else None
            ),
        )
        best = payload["best_train"]
        oos = payload["best_oos"]
        summary_rows.append(
            {
                "factor_name": name,
                "best_train_sharpe": best["sharpe"],
                "best_train_net": best["annualized_net"],
                "best_train_mdd": best["max_drawdown"],
                "best_oos_sharpe": oos["sharpe"],
                "best_oos_net": oos["annualized_net"],
                "best_oos_mdd": oos["max_drawdown"],
                "best_params": json.dumps(
                    payload["best_params"], ensure_ascii=False, sort_keys=True
                ),
            }
        )
        print(
            f"  train {best['sharpe']:.3f} / oos {oos['sharpe']:.3f}",
            flush=True,
        )
    summary = pd.DataFrame(summary_rows).sort_values(
        "best_train_sharpe", ascending=False
    )
    summary.to_csv(output_dir / "summary.csv", index=False)
    manifest = {
        "trial_count_per_factor": trials,
        "workers": workers,
        "seed": seed,
        "split": {"train": [TRAIN_START, TRAIN_END], "oos": [OOS_START, OOS_END]},
        "constraints": {
            "min_observations": MIN_OBSERVATIONS,
            "max_drawdown": MAX_DRAWDOWN,
            "max_turnover": MAX_TURNOVER,
        },
        "backtest": {
            "execution_lag": EXECUTION_LAG,
            "cost_rate": COST_RATE,
            "annualization_factor": 252,
        },
        "input_dir": str(input_dir),
        "factors": selected,
        "fixed_params": {name: dict(specs[name].fixed) for name in selected},
        "scale_policy": (
            "signal_scale is tuned inside its historical range"
            if tune_scale
            else "signal_scale is pinned to each factor's baseline value"
            " from results/qualified and is never tuned"
        ),
        "scale_ranges": (
            {name: list(specs[name].scale_range or ()) for name in selected}
            if tune_scale
            else {}
        ),
        "sampler": "TPESampler(multivariate=True, group=True, n_startup_trials=10)",
    "resume": resume,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary
