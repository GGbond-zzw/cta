"""Shared aggregate open-interest calculation used by OI factors."""

from __future__ import annotations

import numpy as np
import pandas as pd


def calculate_aggregate_oi_growth(
    contract_snapshots: pd.DataFrame,
    *,
    lookback: int = 20,
    minimum_contracts: int = 2,
) -> pd.DataFrame:
    """Total-curve open-interest growth over a complete window."""

    if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback < 1:
        raise ValueError("lookback must be a positive integer")
    if (
        isinstance(minimum_contracts, bool)
        or not isinstance(minimum_contracts, int)
        or minimum_contracts < 1
    ):
        raise ValueError("minimum_contracts must be a positive integer")
    required = (
        "trading_date",
        "underlying_symbol",
        "order_book_id",
        "open_interest",
    )
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
    snapshots["order_book_id"] = (
        snapshots["order_book_id"].astype("string").str.strip().str.upper()
    )
    snapshots["open_interest"] = pd.to_numeric(
        snapshots["open_interest"], errors="coerce"
    )
    if snapshots.duplicated(
        ["trading_date", "underlying_symbol", "order_book_id"]
    ).any():
        raise ValueError("contract_snapshots contains duplicate contract rows")

    def summarize(group: pd.DataFrame) -> pd.Series:
        valid = group["open_interest"].where(
            np.isfinite(group["open_interest"]) & group["open_interest"].ge(0)
        )
        complete = valid.notna().all() and len(group) >= minimum_contracts
        return pd.Series(
            {
                "contracts_count": len(group),
                "total_open_interest": float(valid.sum()) if complete else np.nan,
            }
        )

    totals = (
        snapshots.groupby(
            ["trading_date", "underlying_symbol"], sort=True, dropna=False
        )
        .apply(summarize, include_groups=False)
        .reset_index()
        .rename(columns={"underlying_symbol": "instrument"})
        .sort_values(["instrument", "trading_date"])
        .reset_index(drop=True)
    )
    valid_total = totals["total_open_interest"].where(
        np.isfinite(totals["total_open_interest"])
        & totals["total_open_interest"].gt(0)
    )
    grouped = valid_total.groupby(totals["instrument"], sort=False)
    base = grouped.shift(lookback)
    count = grouped.transform(
        lambda values: values.rolling(
            lookback + 1, min_periods=lookback + 1
        ).count()
    )
    totals["raw_factor"] = (valid_total / base - 1.0).where(
        count.eq(lookback + 1)
    )
    totals["contracts_count"] = pd.array(totals["contracts_count"], dtype="Int64")
    return totals.loc[
        :,
        [
            "trading_date",
            "instrument",
            "contracts_count",
            "total_open_interest",
            "raw_factor",
        ],
    ]
