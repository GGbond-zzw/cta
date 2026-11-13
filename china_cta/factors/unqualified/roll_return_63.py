"""Realized roll return over the last 63 sessions (unqualified)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from china_cta.factors.cta_common import standard_table
from china_cta.factors.cta_curve import normalize_snapshots


FACTOR_NAME = "roll_return_63"
SIGNAL_SCALE = 0.05


def calculate_roll_return_63(
    contract_snapshots: pd.DataFrame,
    dominant_map: pd.DataFrame,
    *,
    window: int = 63,
) -> pd.DataFrame:
    """Sum the realized long roll return over the last ``window`` sessions.

    On a roll date the long position sells the old contract and buys the new
    one: ``P_old/P_new - 1``. Positive in backwardation, matching carry_ann.
    """

    if window < 2:
        raise ValueError("window must be >= 2")
    required_map = (
        "trading_date",
        "underlying_symbol",
        "dominant_order_book_id",
    )
    missing = sorted(set(required_map) - set(dominant_map.columns))
    if missing:
        raise ValueError(f"dominant_map is missing fields: {missing}")
    optional = ["changed"] if "changed" in dominant_map.columns else []
    mapping = dominant_map.loc[:, [*required_map, *optional]].copy()
    mapping["trading_date"] = pd.to_datetime(
        mapping["trading_date"], errors="raise"
    ).dt.normalize()
    mapping["underlying_symbol"] = (
        mapping["underlying_symbol"].astype("string").str.strip().str.upper()
    )
    mapping["dominant_order_book_id"] = (
        mapping["dominant_order_book_id"].astype("string").str.strip().str.upper()
    )
    mapping = mapping.rename(columns={"underlying_symbol": "instrument"})
    mapping = mapping.sort_values(["instrument", "trading_date"]).reset_index(
        drop=True
    )
    if mapping.duplicated(["trading_date", "instrument"]).any():
        raise ValueError("dominant_map contains duplicate date/instrument rows")
    mapping["old_contract"] = mapping.groupby("instrument", sort=False)[
        "dominant_order_book_id"
    ].shift(1)
    if "changed" not in mapping.columns:
        mapping["changed"] = mapping["dominant_order_book_id"].ne(
            mapping["old_contract"]
        ) & mapping["old_contract"].notna()

    snapshots = normalize_snapshots(contract_snapshots)
    contract_prices = snapshots.loc[
        :, ["trading_date", "instrument", "order_book_id", "price"]
    ]
    new_prices = contract_prices.rename(
        columns={"order_book_id": "dominant_order_book_id", "price": "new_price"}
    )
    old_prices = contract_prices.rename(
        columns={"order_book_id": "old_contract", "price": "old_price"}
    )
    frame = mapping.merge(
        new_prices,
        on=["trading_date", "instrument", "dominant_order_book_id"],
        how="left",
        validate="many_to_one",
    )
    frame = frame.merge(
        old_prices,
        on=["trading_date", "instrument", "old_contract"],
        how="left",
        validate="many_to_one",
    )
    changed = frame["changed"].fillna(False).astype(bool)
    frame["roll_return"] = np.where(
        changed,
        frame["old_price"] / frame["new_price"] - 1.0,
        0.0,
    )
    missing_roll_input = changed & (
        frame["old_price"].isna() | frame["new_price"].isna()
    )
    frame.loc[missing_roll_input, "roll_return"] = np.nan

    frame = frame.sort_values(["instrument", "trading_date"]).reset_index(drop=True)
    frame["raw_factor"] = frame.groupby("instrument", sort=False)[
        "roll_return"
    ].transform(
        lambda values: values.rolling(
            window, min_periods=window
        ).sum()
    )
    frame["raw_factor"] = frame["raw_factor"].where(
        np.isfinite(frame["raw_factor"])
    )
    return frame.loc[:, ["trading_date", "instrument", "raw_factor"]]


def build(inputs: dict) -> pd.DataFrame:
    raw = calculate_roll_return_63(
        inputs["contract_snapshots"], inputs["dominant_map"], window=63
    )
    return standard_table(
        raw,
        inputs["universe"],
        factor_name=FACTOR_NAME,
        signal_scale=SIGNAL_SCALE,
        family="C_carry_and_roll",
        definition="63d_sum_of_old_over_new_minus_1_on_roll_days",
        roll_window=63,
        price_field="close",
        direction="IC+ prior; repository call: not tested",
        raw_factor_normalization="cumulative_63d",
        reference_deviation=(
            "reference build_continuous.py uses new/old-1; this project uses "
            "old/new-1 so roll_return and carry_ann share sign"
        ),
    )
