"""Minimal vectorized diagnostics for deciding whether an Alpha merits formal backtest."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from china_cta.factors.schema import FACTOR_COLUMNS


DETAIL_COLUMNS: Final[tuple[str, ...]] = (
    "signal_date",
    "instrument",
    "factor_name",
    "raw_factor",
    "signal",
    "execution_lag",
    "return_start",
    "return_end",
    "realization_date",
    "research_exposure",
    "research_forward_return",
    "gross_signal_return",
    "turnover_proxy",
    "cost_rate",
    "rough_cost",
    "net_signal_return",
)

METRIC_COLUMNS: Final[tuple[str, ...]] = (
    "observations",
    "periods",
    "cumulative_gross_signal_return",
    "cumulative_net_signal_return",
    "annualized_net_signal_return",
    "annualized_volatility",
    "sharpe",
    "max_drawdown",
    "mean_turnover_proxy",
    "total_rough_cost",
    "ic",
    "rank_ic",
    "mean_long_short_return",
)

RESEARCH_RETURN_DEFINITION: Final[str] = (
    "ratio_adjusted_dominant_close_to_close_after_execution_lag"
)
SECTOR_DEFERRED_REASON: Final[str] = (
    "reliable point-in-time sector metadata is not part of the stable data contract"
)


def run_fast_research_backtest(
    factor_table: pd.DataFrame,
    research_prices: pd.DataFrame,
    universe: pd.DataFrame,
    *,
    execution_lag: int,
    cost_rate: float = 0.0,
    annualization_factor: int = 252,
    price_field: str = "close",
) -> dict[str, Any]:
    """Align Phase 3 signals with future research returns and summarize them.

    ``execution_lag=1`` means a signal observed after close on date t first
    starts a close-to-close research return at the next price observation.
    This intentionally does not assume execution at close(t).
    """

    _validate_run_settings(execution_lag, cost_rate, annualization_factor)
    factors = _normalize_factors(factor_table)
    eligible = _normalize_universe(universe)
    prices = _normalize_research_prices(research_prices, price_field)

    factor_names = factors["factor_name"].dropna().unique()
    if len(factor_names) != 1:
        raise ValueError("factor_table must contain exactly one factor_name")
    factor_name = str(factor_names[0])

    pit_factors = factors.merge(
        eligible.loc[eligible["eligible"], ["signal_date", "instrument"]],
        on=["signal_date", "instrument"],
        how="inner",
        validate="one_to_one",
    )
    alignment = _build_return_alignment(
        prices,
        execution_lag=execution_lag,
        price_field=price_field,
    )
    detail = pit_factors.merge(
        alignment,
        on=["signal_date", "instrument"],
        how="left",
        validate="one_to_one",
    ).sort_values(["signal_date", "instrument"])

    detail["execution_lag"] = execution_lag
    detail["research_exposure"] = detail["signal"]
    previous_exposure = detail.groupby("instrument", sort=False)[
        "research_exposure"
    ].shift(1)
    detail["turnover_proxy"] = (
        detail["research_exposure"] - previous_exposure.fillna(0.0)
    ).abs().where(detail["research_exposure"].notna())
    detail["gross_signal_return"] = (
        detail["research_exposure"] * detail["research_forward_return"]
    )
    detail["cost_rate"] = float(cost_rate)
    detail["rough_cost"] = detail["turnover_proxy"] * float(cost_rate)
    detail["net_signal_return"] = (
        detail["gross_signal_return"] - detail["rough_cost"]
    )
    detail = detail.loc[:, DETAIL_COLUMNS].reset_index(drop=True)
    detail.attrs.update(
        {
            "research_only": True,
            "cash_pnl_allowed": False,
            "signal_is_position": False,
            "execution_lag": execution_lag,
            "research_return_definition": RESEARCH_RETURN_DEFINITION,
            "return_horizon_price_periods": 1,
            "turnover_proxy_definition": "abs(exposure_t - exposure_t_minus_1)",
            "cost_definition": "turnover_proxy * cost_rate",
        }
    )

    overall = pd.DataFrame(
        [_metric_row(detail, annualization_factor)], columns=METRIC_COLUMNS
    )
    by_year = _year_breakdown(detail, annualization_factor)
    by_instrument = _instrument_breakdown(detail, annualization_factor)
    metadata = {
        "factor_name": factor_name,
        "factor_parameters": {},
        "signal_normalization_parameters": {
            "signal_scale": factor_table.attrs.get("signal_scale")
        },
        "execution_lag": execution_lag,
        "return_horizon_price_periods": 1,
        "research_return_definition": RESEARCH_RETURN_DEFINITION,
        "research_only": True,
        "cash_pnl_allowed": False,
        "price_field": price_field,
        "adjust_type": research_prices.attrs.get("adjust_type"),
        "adjust_method": research_prices.attrs.get("adjust_method"),
        "cost_rate": float(cost_rate),
        "annualization_factor": annualization_factor,
        "cross_instrument_aggregation": (
            "mean_of_available_instrument_signal_returns_by_realization_date"
        ),
        "signal_start_date": _date_string(detail["signal_date"].min()),
        "signal_end_date": _date_string(detail["signal_date"].max()),
        "factor_input_sha256": _frame_sha256(factors),
        "research_price_input_sha256": _frame_sha256(prices),
        "universe_input_sha256": _frame_sha256(eligible),
        "sector_breakdown": "deferred",
        "sector_deferred_reason": SECTOR_DEFERRED_REASON,
    }
    return {
        "detail": detail,
        "overall": overall,
        "by_year": by_year,
        "by_instrument": by_instrument,
        "metadata": metadata,
    }


def run_parameter_surface(
    parameter_grid: Mapping[str, Sequence[Any]],
    factor_builder: Callable[[dict[str, Any]], pd.DataFrame],
    research_prices: pd.DataFrame,
    universe: pd.DataFrame,
    *,
    execution_lag: int,
    cost_rate: float = 0.0,
    annualization_factor: int = 252,
    price_field: str = "close",
) -> dict[str, pd.DataFrame]:
    """Run an explicit parameter grid without ranking or selecting a winner."""

    if not parameter_grid:
        raise ValueError("parameter_grid cannot be empty")
    names = tuple(parameter_grid)
    values: list[tuple[Any, ...]] = []
    for name in names:
        candidates = parameter_grid[name]
        if isinstance(candidates, (str, bytes)) or not isinstance(
            candidates, Sequence
        ):
            raise ValueError(f"parameter_grid[{name!r}] must be a sequence")
        if not candidates:
            raise ValueError(f"parameter_grid[{name!r}] cannot be empty")
        values.append(tuple(candidates))

    collected: dict[str, list[pd.DataFrame]] = {
        "overall": [],
        "by_year": [],
        "by_instrument": [],
    }
    for combination in itertools.product(*values):
        parameters = dict(zip(names, combination, strict=True))
        factors = factor_builder(parameters)
        result = run_fast_research_backtest(
            factors,
            research_prices,
            universe,
            execution_lag=execution_lag,
            cost_rate=cost_rate,
            annualization_factor=annualization_factor,
            price_field=price_field,
        )
        parameter_set = json.dumps(
            _jsonable(parameters),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        for result_name in collected:
            frame = result[result_name].copy()
            frame.insert(0, "factor_name", result["metadata"]["factor_name"])
            frame.insert(0, "parameter_set", parameter_set)
            for offset, name in enumerate(names, start=2):
                frame.insert(offset, name, parameters[name])
            collected[result_name].append(frame)

    return {
        name: pd.concat(frames, ignore_index=True)
        for name, frames in collected.items()
    }


def save_research_run(
    result: Mapping[str, Any],
    run_name: str,
    *,
    factor_parameters: Mapping[str, Any],
    signal_normalization_parameters: Mapping[str, Any],
    universe_settings: Mapping[str, Any],
    parameter_grid: Mapping[str, Sequence[Any]] | None = None,
    parameter_surface: Mapping[str, pd.DataFrame] | None = None,
    output_root: str | Path = "results",
) -> dict[str, Path]:
    """Persist one deterministic config and small CSV summaries locally."""

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", run_name):
        raise ValueError("run_name must contain only letters, digits, '.', '_', or '-'")
    required_result = {"overall", "by_year", "by_instrument", "metadata"}
    missing = sorted(required_result - set(result))
    if missing:
        raise ValueError(f"result is missing fields: {missing}")

    metadata = dict(result["metadata"])
    config = {
        "factor_name": metadata["factor_name"],
        "factor_parameters": _jsonable(factor_parameters),
        "signal_normalization_parameters": _jsonable(
            signal_normalization_parameters
        ),
        "execution_lag": metadata["execution_lag"],
        "return_horizon_price_periods": metadata[
            "return_horizon_price_periods"
        ],
        "research_return_definition": metadata["research_return_definition"],
        "research_only": True,
        "cash_pnl_allowed": False,
        "price_field": metadata["price_field"],
        "adjust_type": metadata["adjust_type"],
        "adjust_method": metadata["adjust_method"],
        "date_range": {
            "start": metadata["signal_start_date"],
            "end": metadata["signal_end_date"],
        },
        "universe_settings": _jsonable(universe_settings),
        "cost_assumption": {
            "cost_rate": metadata["cost_rate"],
            "definition": "turnover_proxy * cost_rate",
            "is_actual_futures_fee": False,
        },
        "annualization_factor": metadata["annualization_factor"],
        "cross_instrument_aggregation": metadata[
            "cross_instrument_aggregation"
        ],
        "parameter_grid": _jsonable(parameter_grid or {}),
        "input_fingerprints": {
            "factor": metadata["factor_input_sha256"],
            "research_prices": metadata["research_price_input_sha256"],
            "universe": metadata["universe_input_sha256"],
        },
        "sector_breakdown": "deferred",
        "sector_deferred_reason": SECTOR_DEFERRED_REASON,
    }

    if parameter_surface is not None:
        expected = {"overall", "by_year", "by_instrument"}
        missing_surface = sorted(expected - set(parameter_surface))
        if missing_surface:
            raise ValueError(
                f"parameter_surface is missing fields: {missing_surface}"
            )

    output_dir = Path(output_root) / run_name
    output_dir.mkdir(parents=True, exist_ok=False)

    paths = {
        "config": output_dir / "config.json",
        "overall": output_dir / "overall.csv",
        "by_year": output_dir / "by_year.csv",
        "by_instrument": output_dir / "by_instrument.csv",
    }
    paths["config"].write_text(
        json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    for name in ("overall", "by_year", "by_instrument"):
        result[name].to_csv(paths[name], index=False, float_format="%.17g")

    if parameter_surface is not None:
        for name in ("overall", "by_year", "by_instrument"):
            path = output_dir / f"parameter_surface_{name}.csv"
            parameter_surface[name].to_csv(
                path, index=False, float_format="%.17g"
            )
            paths[f"parameter_surface_{name}"] = path
    return paths


def _validate_run_settings(
    execution_lag: int,
    cost_rate: float,
    annualization_factor: int,
) -> None:
    if (
        isinstance(execution_lag, bool)
        or not isinstance(execution_lag, int)
        or execution_lag < 1
    ):
        raise ValueError("execution_lag must be a positive integer")
    if not np.isfinite(cost_rate) or cost_rate < 0:
        raise ValueError("cost_rate must be a non-negative finite number")
    if (
        isinstance(annualization_factor, bool)
        or not isinstance(annualization_factor, int)
        or annualization_factor < 1
    ):
        raise ValueError("annualization_factor must be a positive integer")


def _normalize_factors(frame: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(set(FACTOR_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"factor_table is missing fields: {missing}")
    if frame.attrs.get("signal_is_position") is True:
        raise ValueError("factor signal cannot be marked as a position")
    factors = frame.loc[:, FACTOR_COLUMNS].copy().rename(
        columns={"trading_date": "signal_date"}
    )
    factors["signal_date"] = pd.to_datetime(
        factors["signal_date"], errors="raise"
    ).dt.normalize()
    factors["instrument"] = (
        factors["instrument"].astype("string").str.strip().str.upper()
    )
    factors["factor_name"] = (
        factors["factor_name"].astype("string").str.strip()
    )
    for column in ("raw_factor", "signal"):
        factors[column] = pd.to_numeric(factors[column], errors="coerce")
        if np.isinf(factors[column].dropna()).any():
            raise ValueError(f"{column} cannot contain infinity")
    if factors.duplicated(["signal_date", "instrument"]).any():
        raise ValueError("factor_table contains duplicate date/instrument rows")
    return factors.sort_values(["signal_date", "instrument"]).reset_index(
        drop=True
    )


def _normalize_universe(frame: pd.DataFrame) -> pd.DataFrame:
    required = ("trading_date", "instrument", "eligible")
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"universe is missing fields: {missing}")
    universe = frame.loc[:, required].copy().rename(
        columns={"trading_date": "signal_date"}
    )
    universe["signal_date"] = pd.to_datetime(
        universe["signal_date"], errors="raise"
    ).dt.normalize()
    universe["instrument"] = (
        universe["instrument"].astype("string").str.strip().str.upper()
    )
    if universe.duplicated(["signal_date", "instrument"]).any():
        raise ValueError("universe contains duplicate date/instrument rows")
    universe["eligible"] = universe["eligible"].eq(True)
    return universe.sort_values(["signal_date", "instrument"]).reset_index(
        drop=True
    )


def _normalize_research_prices(
    frame: pd.DataFrame,
    price_field: str,
) -> pd.DataFrame:
    if frame.attrs.get("usage") != "signal_research_only":
        raise ValueError("research_prices must be marked signal_research_only")
    if frame.attrs.get("cash_pnl_allowed") is not False:
        raise ValueError("research_prices must be prohibited from cash P&L")
    if frame.attrs.get("adjust_type") != "pre" or frame.attrs.get(
        "adjust_method"
    ) != "prev_close_ratio":
        raise ValueError(
            "research_prices require pre-adjusted prev_close_ratio prices"
        )
    required = ("trading_date", "underlying_symbol", price_field)
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"research_prices is missing fields: {missing}")
    prices = frame.loc[:, required].copy().rename(
        columns={
            "trading_date": "signal_date",
            "underlying_symbol": "instrument",
        }
    )
    prices["signal_date"] = pd.to_datetime(
        prices["signal_date"], errors="raise"
    ).dt.normalize()
    prices["instrument"] = (
        prices["instrument"].astype("string").str.strip().str.upper()
    )
    prices[price_field] = pd.to_numeric(prices[price_field], errors="coerce")
    prices[price_field] = prices[price_field].where(
        np.isfinite(prices[price_field]) & prices[price_field].gt(0)
    )
    if prices.duplicated(["signal_date", "instrument"]).any():
        raise ValueError("research_prices contains duplicate date/instrument rows")
    return prices.sort_values(["instrument", "signal_date"]).reset_index(
        drop=True
    )


def _build_return_alignment(
    prices: pd.DataFrame,
    *,
    execution_lag: int,
    price_field: str,
) -> pd.DataFrame:
    grouped = prices.groupby("instrument", sort=False)
    alignment = prices.loc[:, ["signal_date", "instrument"]].copy()
    alignment["return_start"] = grouped["signal_date"].shift(-execution_lag)
    alignment["return_end"] = grouped["signal_date"].shift(-(execution_lag + 1))
    start_price = grouped[price_field].shift(-execution_lag)
    end_price = grouped[price_field].shift(-(execution_lag + 1))
    alignment["realization_date"] = alignment["return_end"]
    alignment["research_forward_return"] = end_price / start_price - 1.0
    return alignment


def _year_breakdown(
    detail: pd.DataFrame,
    annualization_factor: int,
) -> pd.DataFrame:
    years = detail["realization_date"].dropna().dt.year.unique()
    rows = []
    for year in sorted(years):
        subset = detail.loc[detail["realization_date"].dt.year.eq(year)]
        rows.append({"year": int(year), **_metric_row(subset, annualization_factor)})
    return pd.DataFrame(rows, columns=("year", *METRIC_COLUMNS))


def _instrument_breakdown(
    detail: pd.DataFrame,
    annualization_factor: int,
) -> pd.DataFrame:
    rows = []
    for instrument, subset in detail.groupby("instrument", sort=True):
        rows.append(
            {
                "instrument": instrument,
                **_metric_row(subset, annualization_factor),
            }
        )
    return pd.DataFrame(rows, columns=("instrument", *METRIC_COLUMNS))


def _metric_row(frame: pd.DataFrame, annualization_factor: int) -> dict[str, Any]:
    valid = frame.loc[
        frame["realization_date"].notna()
        & frame["net_signal_return"].notna()
    ]
    daily = (
        valid.groupby("realization_date", sort=True)[
            ["gross_signal_return", "net_signal_return"]
        ]
        .mean()
        .dropna(subset=["net_signal_return"])
    )
    gross = daily["gross_signal_return"]
    net = daily["net_signal_return"]
    annualized_volatility = (
        float(net.std(ddof=1) * math.sqrt(annualization_factor))
        if len(net) >= 2
        else np.nan
    )
    sharpe = (
        float(net.mean() * annualization_factor / annualized_volatility)
        if np.isfinite(annualized_volatility) and annualized_volatility > 0
        else np.nan
    )
    daily_cost = (
        valid.groupby("realization_date", sort=True)["rough_cost"].mean()
        if not valid.empty
        else pd.Series(dtype="float64")
    )
    return {
        "observations": int(len(valid)),
        "periods": int(len(daily)),
        "cumulative_gross_signal_return": _compound(gross),
        "cumulative_net_signal_return": _compound(net),
        "annualized_net_signal_return": (
            float(net.mean() * annualization_factor) if not net.empty else np.nan
        ),
        "annualized_volatility": annualized_volatility,
        "sharpe": sharpe,
        "max_drawdown": _max_drawdown(net),
        "mean_turnover_proxy": float(frame["turnover_proxy"].mean()),
        "total_rough_cost": (
            float(daily_cost.sum()) if not daily_cost.empty else np.nan
        ),
        "ic": _mean_cross_sectional_correlation(frame, rank=False),
        "rank_ic": _mean_cross_sectional_correlation(frame, rank=True),
        "mean_long_short_return": _mean_long_short_return(frame),
    }


def _compound(returns: pd.Series) -> float:
    if returns.empty:
        return np.nan
    return float((1.0 + returns).prod() - 1.0)


def _max_drawdown(returns: pd.Series) -> float:
    if returns.empty:
        return np.nan
    wealth = pd.Series(
        np.concatenate(([1.0], (1.0 + returns).cumprod().to_numpy()))
    )
    return float((wealth / wealth.cummax() - 1.0).min())


def _mean_cross_sectional_correlation(
    frame: pd.DataFrame,
    *,
    rank: bool,
) -> float:
    values: list[float] = []
    for _, cross_section in frame.groupby("signal_date", sort=True):
        valid = cross_section.loc[
            cross_section[["raw_factor", "research_forward_return"]]
            .notna()
            .all(axis=1),
            ["raw_factor", "research_forward_return"],
        ]
        if (
            len(valid) < 2
            or valid["raw_factor"].nunique() < 2
            or valid["research_forward_return"].nunique() < 2
        ):
            continue
        if rank:
            correlation = valid["raw_factor"].rank().corr(
                valid["research_forward_return"].rank()
            )
        else:
            correlation = valid["raw_factor"].corr(
                valid["research_forward_return"]
            )
        if pd.notna(correlation):
            values.append(float(correlation))
    return float(np.mean(values)) if values else np.nan


def _mean_long_short_return(frame: pd.DataFrame) -> float:
    values: list[float] = []
    for _, cross_section in frame.groupby("signal_date", sort=True):
        valid = cross_section.loc[
            cross_section[["signal", "research_forward_return"]]
            .notna()
            .all(axis=1)
        ]
        long_returns = valid.loc[
            valid["signal"].gt(0), "research_forward_return"
        ]
        short_returns = valid.loc[
            valid["signal"].lt(0), "research_forward_return"
        ]
        if not long_returns.empty and not short_returns.empty:
            values.append(float(long_returns.mean() - short_returns.mean()))
    return float(np.mean(values)) if values else np.nan


def _frame_sha256(frame: pd.DataFrame) -> str:
    normalized = frame.copy()
    header = json.dumps(
        {
            "columns": list(normalized.columns),
            "dtypes": [str(dtype) for dtype in normalized.dtypes],
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    row_hashes = pd.util.hash_pandas_object(normalized, index=False).to_numpy()
    digest = hashlib.sha256(header)
    digest.update(row_hashes.tobytes())
    return digest.hexdigest()


def _date_string(value: Any) -> str | None:
    return None if pd.isna(value) else pd.Timestamp(value).date().isoformat()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported config value type: {type(value).__name__}")
