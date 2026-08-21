"""The single Phase 3 factor output contract and minimal signal scaling."""

from __future__ import annotations

import re
from typing import Final

import numpy as np
import pandas as pd


FACTOR_COLUMNS: Final[tuple[str, ...]] = (
    "trading_date",
    "instrument",
    "factor_name",
    "raw_factor",
    "signal",
)


def make_factor_table(
    raw_factors: pd.DataFrame,
    universe: pd.DataFrame,
    *,
    factor_name: str,
    signal_scale: float,
) -> pd.DataFrame:
    """Filter to the PIT universe and apply one transparent signal mapping.

    ``trading_date`` is the information date and after-close signal date. The
    earliest permitted execution is the next trading session.
    """

    if not re.fullmatch(r"[a-z0-9_]+", factor_name):
        raise ValueError("factor_name must use lowercase letters, digits, and '_'")
    if not np.isfinite(signal_scale) or signal_scale <= 0:
        raise ValueError("signal_scale must be a positive finite number")

    required_raw = ("trading_date", "instrument", "raw_factor")
    required_universe = ("trading_date", "instrument", "eligible")
    missing_raw = sorted(set(required_raw) - set(raw_factors.columns))
    missing_universe = sorted(set(required_universe) - set(universe.columns))
    if missing_raw:
        raise ValueError(f"raw_factors is missing fields: {missing_raw}")
    if missing_universe:
        raise ValueError(f"universe is missing fields: {missing_universe}")

    raw = raw_factors.loc[:, required_raw].copy()
    eligible = universe.loc[:, required_universe].copy()
    for frame in (raw, eligible):
        frame["trading_date"] = pd.to_datetime(
            frame["trading_date"], errors="raise"
        ).dt.normalize()
        frame["instrument"] = (
            frame["instrument"].astype("string").str.strip().str.upper()
        )
    raw["raw_factor"] = pd.to_numeric(raw["raw_factor"], errors="coerce")
    if np.isinf(raw["raw_factor"].dropna()).any():
        raise ValueError("raw_factor cannot contain infinity")
    if raw.duplicated(["trading_date", "instrument"]).any():
        raise ValueError("raw_factors contains duplicate date/instrument rows")
    if eligible.duplicated(["trading_date", "instrument"]).any():
        raise ValueError("universe contains duplicate date/instrument rows")

    eligible = eligible.loc[eligible["eligible"].eq(True)]
    result = raw.merge(
        eligible.loc[:, ["trading_date", "instrument"]],
        on=["trading_date", "instrument"],
        how="inner",
        validate="one_to_one",
    )
    result["factor_name"] = factor_name
    result["signal"] = (result["raw_factor"] / signal_scale).clip(-1.0, 1.0)
    result = (
        result.loc[:, FACTOR_COLUMNS]
        .sort_values(["trading_date", "instrument"])
        .reset_index(drop=True)
    )
    result.attrs.update(
        {
            "information_date": "trading_date",
            "signal_available_at": "after_close_of_trading_date",
            "earliest_trade_at": "next_trading_session",
            "signal_is_position": False,
            "signal_scale": float(signal_scale),
        }
    )
    return result
