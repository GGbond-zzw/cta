"""Shared helpers for the 22-factor CTA alpha catalog.

The catalog is implemented on top of the project's existing Phase 3 contract:
one five-column factor table per definition, a point-in-time eligible
universe, and research-only ratio-adjusted continuous prices.
"""

from __future__ import annotations

import math
from typing import Final

import numpy as np
import pandas as pd

from china_cta.factors.schema import make_factor_table


ANNUALIZATION: Final[int] = 252


class FactorDataUnavailable(RuntimeError):
    """Raised when the provider does not expose a required input series."""


def require_research_prices(frame: pd.DataFrame) -> None:
    """Reject anything that is not the project's signal-research continuous price."""

    if frame.attrs.get("usage") != "signal_research_only":
        raise ValueError("CTA alpha factors require research continuous prices")
    if frame.attrs.get("cash_pnl_allowed") is not False:
        raise ValueError("CTA alpha factor input cannot be used for cash P&L")
    if (
        frame.attrs.get("adjust_type") != "pre"
        or frame.attrs.get("adjust_method") != "prev_close_ratio"
    ):
        raise ValueError(
            "CTA alpha factors require pre-adjusted prev_close_ratio prices"
        )


def normalize_continuous(
    frame: pd.DataFrame, fields: tuple[str, ...] | list[str]
) -> pd.DataFrame:
    """Return a sorted, numeric date/instrument panel for the requested fields."""

    require_research_prices(frame)
    requested = tuple(fields)
    required = ("trading_date", "underlying_symbol", *requested)
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"continuous panel is missing fields: {missing}")
    data = frame.loc[:, required].copy().rename(
        columns={"underlying_symbol": "instrument"}
    )
    data["trading_date"] = pd.to_datetime(
        data["trading_date"], errors="raise"
    ).dt.normalize()
    data["instrument"] = (
        data["instrument"].astype("string").str.strip().str.upper()
    )
    for field in requested:
        data[field] = pd.to_numeric(data[field], errors="coerce")
    if data.duplicated(["trading_date", "instrument"]).any():
        raise ValueError("continuous panel contains duplicate date/instrument rows")
    return data.sort_values(["instrument", "trading_date"]).reset_index(drop=True)


def valid_price(series: pd.Series) -> pd.Series:
    """Return the series with non-positive/non-finite values replaced by NA."""

    return series.where(np.isfinite(series) & series.gt(0))


def log_return(
    price: pd.Series, instrument: pd.Series, *, periods: int = 1
) -> pd.Series:
    """Per-instrument log return without filling missing prices."""

    values = valid_price(price)
    logged = np.log(values)
    return logged.groupby(instrument, sort=False).diff(periods)


def annualized_volatility(
    price: pd.Series,
    instrument: pd.Series,
    *,
    window: int = 20,
) -> pd.Series:
    """Annualized rolling standard deviation of log returns."""

    returns = log_return(price, instrument)
    volatility = returns.groupby(instrument, sort=False).transform(
        lambda values: values.rolling(
            window, min_periods=window
        ).std(ddof=1)
    )
    volatility = volatility * math.sqrt(ANNUALIZATION)
    return volatility.where(np.isfinite(volatility) & volatility.gt(0))


def rolling_count(
    price: pd.Series, instrument: pd.Series, *, window: int
) -> pd.Series:
    """Count of valid prices in a rolling window, per instrument."""

    values = valid_price(price)
    return values.groupby(instrument, sort=False).transform(
        lambda series: series.rolling(
            window, min_periods=window
        ).count()
    )


def lagged_return(
    price: pd.Series,
    instrument: pd.Series,
    *,
    lag: int,
    window: int | None = None,
) -> pd.Series:
    """Simple return from ``t-lag`` to ``t`` with a complete price window."""

    values = valid_price(price)
    base = values.groupby(instrument, sort=False).shift(lag)
    observations = window if window is not None else lag + 1
    count = rolling_count(values, instrument, window=observations)
    return (values / base - 1.0).where(count.eq(observations))


def cross_sectional_rank_score(values: pd.Series) -> pd.Series:
    """Map same-date ranks to [-1, 1], leaving fewer than two peers unavailable."""

    result = pd.Series(np.nan, index=values.index, dtype="float64")
    valid = values.dropna()
    if len(valid) < 2:
        return result
    ranks = valid.rank(method="average", ascending=True)
    result.loc[valid.index] = 2.0 * (ranks - 1.0) / (len(valid) - 1.0) - 1.0
    return result


def standard_table(
    raw: pd.DataFrame,
    universe: pd.DataFrame,
    *,
    factor_name: str,
    signal_scale: float,
    **metadata: object,
) -> pd.DataFrame:
    """Apply the project's five-column contract and attach factor metadata."""

    if raw.duplicated(["trading_date", "instrument"]).any():
        raise ValueError(f"{factor_name} raw panel has duplicate date/instrument rows")
    result = make_factor_table(
        raw.loc[:, ["trading_date", "instrument", "raw_factor"]],
        universe,
        factor_name=factor_name,
        signal_scale=signal_scale,
    )
    result.attrs.update(metadata)
    return result


def cross_sectional_table(
    raw: pd.DataFrame,
    universe: pd.DataFrame,
    *,
    factor_name: str,
    **metadata: object,
) -> pd.DataFrame:
    """Rank a raw time-series factor within each eligible daily universe."""

    required = ("trading_date", "instrument", "raw_factor")
    missing = sorted(set(required) - set(raw.columns))
    if missing:
        raise ValueError(f"raw panel is missing fields: {missing}")
    eligible = universe.loc[universe["eligible"].eq(True)].copy()
    eligible["trading_date"] = pd.to_datetime(
        eligible["trading_date"], errors="raise"
    ).dt.normalize()
    eligible["instrument"] = (
        eligible["instrument"].astype("string").str.strip().str.upper()
    )
    frame = raw.loc[:, required].copy()
    frame["trading_date"] = pd.to_datetime(
        frame["trading_date"], errors="raise"
    ).dt.normalize()
    frame["instrument"] = (
        frame["instrument"].astype("string").str.strip().str.upper()
    )
    merged = frame.merge(
        eligible.loc[:, ["trading_date", "instrument"]],
        on=["trading_date", "instrument"],
        how="inner",
        validate="one_to_one",
    )
    merged = merged.sort_values(["trading_date", "instrument"]).reset_index(drop=True)
    merged["raw_factor"] = merged.groupby("trading_date", sort=False)[
        "raw_factor"
    ].transform(cross_sectional_rank_score)
    return standard_table(
        merged,
        universe,
        factor_name=factor_name,
        signal_scale=1.0,
        **metadata,
    )


def total_open_interest(
    contract_snapshots: pd.DataFrame,
    *,
    minimum_contracts: int = 2,
) -> pd.DataFrame:
    """Sum OI across every active real contract, or leave the date unavailable."""

    required = ("trading_date", "underlying_symbol", "order_book_id", "open_interest")
    missing = sorted(set(required) - set(contract_snapshots.columns))
    if missing:
        raise ValueError(f"contract_snapshots is missing fields: {missing}")
    snapshots = contract_snapshots.loc[:, required].copy()
    snapshots["trading_date"] = pd.to_datetime(
        snapshots["trading_date"], errors="raise"
    ).dt.normalize()
    snapshots["underlying_symbol"] = (
        snapshots["underlying_symbol"].astype("string").str.strip().str.upper()
    )
    snapshots["open_interest"] = pd.to_numeric(
        snapshots["open_interest"], errors="coerce"
    )

    def summarize(group: pd.DataFrame) -> float:
        valid = group["open_interest"].where(
            np.isfinite(group["open_interest"]) & group["open_interest"].ge(0)
        )
        if len(group) < minimum_contracts or not valid.notna().all():
            return float("nan")
        return float(valid.sum())

    totals = (
        snapshots.groupby(["trading_date", "underlying_symbol"], sort=True)
        .apply(summarize, include_groups=False)
        .rename("total_open_interest")
        .reset_index()
        .rename(columns={"underlying_symbol": "instrument"})
    )
    return totals
