"""Carry between two fixed calendar-day maturities, using real contract closes."""

from __future__ import annotations

from typing import Final

import numpy as np
import pandas as pd

from china_cta.factors.schema import make_factor_table


_PRICE_FIELDS = (
    "target_days", "price", "lower_contract", "upper_contract",
    "lower_days", "upper_days", "lower_weight", "gap_days", "status",
)
CURVE_CARRY_DIAGNOSTIC_COLUMNS: Final[tuple[str, ...]] = (
    "trading_date", "instrument",
    *(f"{side}_{field}" for side in ("near", "far") for field in _PRICE_FIELDS),
    "raw_factor",
)


def _validate_parameters(near_days, far_days, min_days_to_maturity, max_gap_days):
    for name, value in (
        ("near_days", near_days), ("far_days", far_days),
        ("min_days_to_maturity", min_days_to_maturity), ("max_gap_days", max_gap_days),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    if not min_days_to_maturity < near_days < far_days:
        raise ValueError("require min_days_to_maturity < near_days < far_days")
    if max_gap_days == 0:
        raise ValueError("max_gap_days must be positive")


def _interpolate_price(curve: pd.DataFrame, target: int, max_gap: int) -> dict:
    """Select by tenor before price validation; never replace a missing quote."""
    result = dict.fromkeys(_PRICE_FIELDS, np.nan)
    result.update(target_days=target, lower_contract=pd.NA, upper_contract=pd.NA,
                  status="unbracketed")
    lower = curve.loc[curve["days_to_maturity"].le(target)]
    upper = curve.loc[curve["days_to_maturity"].ge(target)]
    if lower.empty or upper.empty:
        return result
    lo, hi = lower.iloc[-1], upper.iloc[0]
    lo_days, hi_days = float(lo["days_to_maturity"]), float(hi["days_to_maturity"])
    gap = hi_days - lo_days
    # A quoted exact target needs no second contract.
    weight = 1.0 if gap == 0 else (hi_days - target) / gap
    result.update(lower_contract=lo["order_book_id"], upper_contract=hi["order_book_id"],
                  lower_days=lo_days, upper_days=hi_days, lower_weight=weight, gap_days=gap)
    if gap > max_gap:
        result["status"] = "gap_too_large"
    elif not (_valid_price(lo["price"]) and _valid_price(hi["price"])):
        result["status"] = "invalid_price"
    else:
        result.update(price=weight * float(lo["price"]) + (1 - weight) * float(hi["price"]),
                      status="exact" if gap == 0 else "interpolated")
    return result


def calculate_curve_carry(
    contract_snapshots: pd.DataFrame, *, near_days: int = 90, far_days: int = 180,
    min_days_to_maturity: int = 30, max_gap_days: int = 120,
) -> pd.DataFrame:
    """Return linear fixed-maturity prices and annualized log carry.

    Carry = (log(P_near) - log(P_far)) * 365 / (far_days - near_days).
    Tenors are natural days to the supplied maturity_date, not delivery months.
    No extrapolation or forward filling. A missing bracket quote, excessive
    bracket gap or duplicate tenor invalidates the affected price/date.
    Prices are research estimates, not a self-financing return index.
    """
    _validate_parameters(near_days, far_days, min_days_to_maturity, max_gap_days)
    snapshots = _normalize_snapshots(contract_snapshots)
    rows = []
    for (date, instrument), curve in snapshots.groupby(
        ["trading_date", "underlying_symbol"], sort=True, dropna=False
    ):
        eligible = curve.loc[
            curve["maturity_date"].notna()
            & curve["days_to_maturity"].gt(min_days_to_maturity)
        ].sort_values(["days_to_maturity", "order_book_id"])
        row = {"trading_date": date, "instrument": instrument, "raw_factor": np.nan}
        for side, target in (("near", near_days), ("far", far_days)):
            price = _interpolate_price(eligible, target, max_gap_days)
            if eligible["days_to_maturity"].duplicated().any():
                price.update(price=np.nan, status="duplicate_tenor")
            row.update({f"{side}_{key}": value for key, value in price.items()})
        if _valid_price(row["near_price"]) and _valid_price(row["far_price"]):
            row["raw_factor"] = (
                np.log(row["near_price"]) - np.log(row["far_price"])
            ) * 365.0 / (far_days - near_days)
        rows.append(row)
    return pd.DataFrame(rows, columns=CURVE_CARRY_DIAGNOSTIC_COLUMNS)


def compute_curve_carry_factor(
    contract_snapshots: pd.DataFrame, universe: pd.DataFrame, *,
    near_days: int = 90, far_days: int = 180, min_days_to_maturity: int = 30,
    max_gap_days: int = 120, signal_scale: float = 0.20,
) -> pd.DataFrame:
    """Return the standard PIT factor table for fixed-maturity carry."""
    diagnostics = calculate_curve_carry(
        contract_snapshots, near_days=near_days, far_days=far_days,
        min_days_to_maturity=min_days_to_maturity, max_gap_days=max_gap_days,
    )
    result = make_factor_table(
        diagnostics.loc[:, ["trading_date", "instrument", "raw_factor"]], universe,
        factor_name=f"fixed_maturity_carry_{near_days}_{far_days}d", signal_scale=signal_scale,
    )
    result.attrs.update({
        "definition": "annualized_log_near_fixed_price_minus_log_far_fixed_price",
        "near_days": near_days, "far_days": far_days,
        "min_days_to_maturity": min_days_to_maturity, "max_gap_days": max_gap_days,
        "interpolation": "linear_price", "maturity_reference": "maturity_date",
        "day_count": "actual_calendar_days_365", "price_field": "close",
        "direction": "long_backwardation_short_contango",
        "raw_factor_normalization": "annualized_log_fixed_maturity_spread",
        "fixed_prices_usage": "signal_research_only", "cash_pnl_allowed": False,
    })
    return result


def _normalize_snapshots(contract_snapshots: pd.DataFrame) -> pd.DataFrame:
    required = (
        "trading_date", "underlying_symbol", "order_book_id", "maturity_date",
        "days_to_maturity", "price", "price_field",
    )
    missing = sorted(set(required) - set(contract_snapshots.columns))
    if missing:
        raise ValueError(f"contract_snapshots is missing fields: {missing}")
    snapshots = contract_snapshots.loc[:, required].copy()
    snapshots["trading_date"] = pd.to_datetime(snapshots["trading_date"], errors="raise").dt.normalize()
    snapshots["maturity_date"] = pd.to_datetime(snapshots["maturity_date"], errors="coerce").dt.normalize()
    for column in ("underlying_symbol", "order_book_id", "price_field"):
        snapshots[column] = snapshots[column].astype("string").str.strip()
    snapshots["underlying_symbol"] = snapshots["underlying_symbol"].str.upper()
    snapshots["order_book_id"] = snapshots["order_book_id"].str.upper()
    snapshots["price_field"] = snapshots["price_field"].str.lower()
    snapshots["days_to_maturity"] = pd.to_numeric(snapshots["days_to_maturity"], errors="coerce")
    actual_days = (snapshots["maturity_date"] - snapshots["trading_date"]).dt.days
    if (snapshots["maturity_date"].notna() & snapshots["days_to_maturity"].ne(actual_days)).any():
        raise ValueError("days_to_maturity must match calendar days to maturity_date")
    snapshots["price"] = pd.to_numeric(snapshots["price"], errors="coerce")
    if snapshots.duplicated(["trading_date", "underlying_symbol", "order_book_id"]).any():
        raise ValueError("contract_snapshots contains duplicate contract rows")
    if snapshots["price_field"].isna().any() or snapshots["price_field"].ne("close").any():
        raise ValueError("curve carry requires close prices")
    return snapshots


def _valid_price(value: object) -> bool:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return bool(np.isfinite(numeric) and numeric > 0)


def build(inputs: dict) -> pd.DataFrame:
    """Build the standard factor table from the shared input bundle."""

    return compute_curve_carry_factor(
        inputs["contract_snapshots"], inputs["universe"]
    )
