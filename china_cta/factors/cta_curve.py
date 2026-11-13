"""Shared real-contract curve helpers for carry and term-structure factors."""

from __future__ import annotations

import numpy as np
import pandas as pd

from china_cta.factors.cta_common import valid_price


def normalize_snapshots(contract_snapshots: pd.DataFrame) -> pd.DataFrame:
    """Validate real-contract snapshots and expose an ``instrument`` column."""

    required = (
        "trading_date",
        "underlying_symbol",
        "order_book_id",
        "maturity_date",
        "days_to_maturity",
        "price",
        "price_field",
    )
    missing = sorted(set(required) - set(contract_snapshots.columns))
    if missing:
        raise ValueError(f"contract_snapshots is missing fields: {missing}")
    snapshots = contract_snapshots.loc[:, required].copy().rename(
        columns={"underlying_symbol": "instrument"}
    )
    snapshots["trading_date"] = pd.to_datetime(
        snapshots["trading_date"], errors="raise"
    ).dt.normalize()
    snapshots["maturity_date"] = pd.to_datetime(
        snapshots["maturity_date"], errors="coerce"
    ).dt.normalize()
    for column in ("instrument", "order_book_id", "price_field"):
        snapshots[column] = snapshots[column].astype("string").str.strip()
    snapshots["instrument"] = snapshots["instrument"].str.upper()
    snapshots["order_book_id"] = snapshots["order_book_id"].str.upper()
    snapshots["price_field"] = snapshots["price_field"].str.lower()
    snapshots["days_to_maturity"] = pd.to_numeric(
        snapshots["days_to_maturity"], errors="coerce"
    )
    actual_days = (snapshots["maturity_date"] - snapshots["trading_date"]).dt.days
    if (
        snapshots["maturity_date"].notna()
        & snapshots["days_to_maturity"].ne(actual_days)
    ).any():
        raise ValueError("days_to_maturity must match calendar days to maturity_date")
    snapshots["price"] = pd.to_numeric(snapshots["price"], errors="coerce")
    if snapshots.duplicated(
        ["trading_date", "instrument", "order_book_id"]
    ).any():
        raise ValueError("contract_snapshots contains duplicate contract rows")
    if snapshots["price_field"].isna().any() or snapshots[
        "price_field"
    ].ne("close").any():
        raise ValueError("CTA curve factors require close prices")
    return snapshots.sort_values(
        ["instrument", "trading_date", "days_to_maturity", "order_book_id"]
    ).reset_index(drop=True)


def calculate_curve_metrics(
    contract_snapshots: pd.DataFrame,
    *,
    min_days_to_maturity: int = 30,
) -> pd.DataFrame:
    """Near/second/third contract prices plus carry, slope and curvature."""

    if (
        isinstance(min_days_to_maturity, bool)
        or not isinstance(min_days_to_maturity, int)
        or min_days_to_maturity < 0
    ):
        raise ValueError("min_days_to_maturity must be a non-negative integer")
    snapshots = normalize_snapshots(contract_snapshots)
    rows: list[dict[str, object]] = []
    for (date, instrument), curve in snapshots.groupby(
        ["trading_date", "instrument"], sort=True
    ):
        eligible = curve.loc[
            curve["days_to_maturity"].gt(min_days_to_maturity)
            & valid_price(curve["price"]).notna()
        ].sort_values(["days_to_maturity", "order_book_id"])
        row: dict[str, object] = {
            "trading_date": date,
            "instrument": instrument,
            "near_contract": pd.NA,
            "far_contract": pd.NA,
            "third_contract": pd.NA,
            "near_days": np.nan,
            "far_days": np.nan,
            "third_days": np.nan,
            "near_price": np.nan,
            "far_price": np.nan,
            "third_price": np.nan,
            "gap_days": np.nan,
            "status": "insufficient_contracts",
            "carry_ann": np.nan,
            "ts_slope": np.nan,
            "ts_curvature": np.nan,
        }
        if len(eligible) >= 1:
            near = eligible.iloc[0]
            row.update(
                near_contract=near["order_book_id"],
                near_days=float(near["days_to_maturity"]),
                near_price=float(near["price"]),
            )
        if len(eligible) >= 2:
            far = eligible.iloc[1]
            gap = float(far["days_to_maturity"]) - float(near["days_to_maturity"])
            row.update(
                far_contract=far["order_book_id"],
                far_days=float(far["days_to_maturity"]),
                far_price=float(far["price"]),
                gap_days=gap,
                status="ok" if gap > 0 else "non_positive_gap",
            )
            if gap > 0:
                row["carry_ann"] = (
                    float(near["price"]) / float(far["price"]) - 1.0
                ) * 365.0 / gap
                row["ts_slope"] = (
                    np.log(float(far["price"]) / float(near["price"])) / gap
                )
        if len(eligible) >= 3:
            third = eligible.iloc[2]
            row.update(
                third_contract=third["order_book_id"],
                third_days=float(third["days_to_maturity"]),
                third_price=float(third["price"]),
            )
            second_price = float(eligible.iloc[1]["price"])
            row["ts_curvature"] = (
                float(third["price"])
                - 2.0 * second_price
                + float(near["price"])
            ) / second_price
        rows.append(row)
    if not rows:
        return pd.DataFrame(
            columns=[
                "trading_date",
                "instrument",
                "near_contract",
                "far_contract",
                "third_contract",
                "near_days",
                "far_days",
                "third_days",
                "near_price",
                "far_price",
                "third_price",
                "gap_days",
                "status",
                "carry_ann",
                "ts_slope",
                "ts_curvature",
            ]
        )
    result = pd.DataFrame(rows)
    for column in ("carry_ann", "ts_slope", "ts_curvature"):
        result[column] = pd.to_numeric(result[column], errors="coerce").where(
            np.isfinite(result[column])
        )
    return result
