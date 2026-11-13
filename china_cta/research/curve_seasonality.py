"""Delivery-month structure after removing each day's linear futures-curve slope.

This is a diagnostic of delivery-month *curvature*, not the complete seasonal
component of futures prices. In particular, a seasonal effect collinear with
the daily level or linear slope is deliberately unidentified here.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd


_REAL_ID = re.compile(r"^[A-Z]+[0-9]{1,2}(?:0[1-9]|1[0-2])$")


def delivery_month_from_id(order_book_id: str) -> int:
    """Use contract-code delivery month, not last-trading/maturity date month."""
    value = str(order_book_id).strip().upper()
    if not _REAL_ID.fullmatch(value):
        raise ValueError(f"not a real futures contract ID: {order_book_id}")
    month = int(value[-2:])
    if not 1 <= month <= 12:
        raise ValueError(f"invalid contract delivery month: {order_book_id}")
    return month


def daily_curve_residuals(
    snapshots: pd.DataFrame, *, min_days_to_maturity: int = 30,
    max_days_to_maturity: int = 540, min_contracts: int = 4,
    min_volume: float = 1, min_open_interest: float = 1,
    curve_degree: int = 1,
    min_volume_share: float = 0, min_open_interest_share: float = 0,
) -> pd.DataFrame:
    """Demean log close prices against a *same-day* maturity curve.

    Returns one residual per sufficiently liquid real contract. Days with
    fewer than ``min_contracts`` eligible contracts remain unobserved.
    """
    required = {
        "trading_date", "underlying_symbol", "order_book_id",
        "days_to_maturity", "price", "price_field", "volume", "open_interest",
    }
    if required - set(snapshots):
        raise ValueError(f"snapshots missing fields: {sorted(required - set(snapshots))}")
    if not (0 <= min_days_to_maturity < max_days_to_maturity):
        raise ValueError("invalid maturity interval")
    if curve_degree not in (1, 2):
        raise ValueError("curve_degree must be 1 or 2")
    if min_contracts < curve_degree + 2 or min_volume < 0 or min_open_interest < 0:
        raise ValueError("invalid contract-count or liquidity threshold")
    if not 0 <= min_volume_share < 1 or not 0 <= min_open_interest_share < 1:
        raise ValueError("relative liquidity thresholds must be in [0, 1)")
    frame = snapshots.loc[:, list(required)].copy()
    frame["trading_date"] = pd.to_datetime(frame["trading_date"]).dt.normalize()
    frame["underlying_symbol"] = frame["underlying_symbol"].astype(str).str.upper()
    frame["order_book_id"] = frame["order_book_id"].astype(str).str.upper()
    frame["price_field"] = frame["price_field"].astype(str).str.lower()
    if frame["price_field"].ne("close").any():
        raise ValueError("only unadjusted close prices are supported")
    if frame.duplicated(["trading_date", "order_book_id"]).any():
        raise ValueError("duplicate contract-date in snapshots")
    for column in ("days_to_maturity", "price", "volume", "open_interest"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.loc[
        frame["days_to_maturity"].between(min_days_to_maturity, max_days_to_maturity)
        & frame["price"].gt(0)
        & frame["volume"].ge(min_volume)
        & frame["open_interest"].ge(min_open_interest)
    ].copy()
    if min_volume_share or min_open_interest_share:
        grouped_liquidity = frame.groupby(["trading_date", "underlying_symbol"])
        max_volume = grouped_liquidity["volume"].transform("max")
        max_oi = grouped_liquidity["open_interest"].transform("max")
        frame = frame.loc[
            frame["volume"].ge(min_volume_share * max_volume)
            & frame["open_interest"].ge(min_open_interest_share * max_oi)
        ].copy()
    frame["delivery_month"] = frame["order_book_id"].map(delivery_month_from_id)
    records = []
    for (date, product), group in frame.groupby(["trading_date", "underlying_symbol"], sort=True):
        if len(group) < min_contracts or group["days_to_maturity"].nunique() < min_contracts:
            continue
        tenor_years = group["days_to_maturity"].to_numpy(dtype=float) / 365.0
        log_price = np.log(group["price"].to_numpy(dtype=float))
        coefficients = np.polyfit(tenor_years, log_price, curve_degree)
        residuals = log_price - np.polyval(coefficients, tenor_years)
        for row, residual in zip(group.itertuples(), residuals, strict=True):
            records.append({
                "trading_date": date, "underlying_symbol": product,
                "order_book_id": row.order_book_id,
                "delivery_month": int(row.delivery_month),
                "days_to_maturity": float(row.days_to_maturity),
                "curve_residual": float(residual),
                "contracts_on_curve": len(group),
            })
    return pd.DataFrame(records, columns=[
        "trading_date", "underlying_symbol", "order_book_id", "delivery_month",
        "days_to_maturity", "curve_residual", "contracts_on_curve",
    ])


def annual_delivery_month_panel(
    residuals: pd.DataFrame, *, min_distinct_days: int = 20,
) -> pd.DataFrame:
    """Collapse overlapping contracts/dates to product-year-delivery-month units."""
    required = {"trading_date", "underlying_symbol", "delivery_month", "curve_residual"}
    if required - set(residuals):
        raise ValueError("residuals missing required fields")
    if min_distinct_days < 1:
        raise ValueError("min_distinct_days must be positive")
    if residuals.empty:
        return pd.DataFrame(columns=[
            "underlying_symbol", "year", "delivery_month", "mean_curve_residual",
            "distinct_days", "contract_observations",
        ])
    frame = residuals.loc[:, list(required)].copy()
    frame["trading_date"] = pd.to_datetime(frame["trading_date"]).dt.normalize()
    frame["year"] = frame["trading_date"].dt.year
    # A contract-month may have several contracts on one date. First average
    # within the date, so no date gets extra weight from duplicate maturities.
    daily = frame.groupby(
        ["underlying_symbol", "year", "delivery_month", "trading_date"],
        observed=True,
    ).agg(curve_residual=("curve_residual", "mean"),
          contract_observations=("curve_residual", "size")).reset_index()
    annual = daily.groupby(["underlying_symbol", "year", "delivery_month"], observed=True).agg(
        mean_curve_residual=("curve_residual", "mean"),
        distinct_days=("trading_date", "nunique"),
        contract_observations=("contract_observations", "sum"),
    ).reset_index()
    annual.loc[annual["distinct_days"].lt(min_distinct_days), "mean_curve_residual"] = np.nan
    return annual
