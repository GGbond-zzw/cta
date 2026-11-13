"""Registered warehouse-receipt growth (unqualified)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from china_cta.factors.cta_common import rolling_count, standard_table


FACTOR_NAME = "receipt_mom_20"
SIGNAL_SCALE = 0.20


def calculate_receipt_mom_20(
    warehouse_stocks: pd.DataFrame, *, lookback: int = 20
) -> pd.DataFrame:
    if lookback < 1:
        raise ValueError("lookback must be a positive integer")
    required = ("trading_date", "underlying_symbol", "on_warrant")
    missing = sorted(set(required) - set(warehouse_stocks.columns))
    if missing:
        raise ValueError(f"warehouse_stocks is missing fields: {missing}")
    frame = warehouse_stocks.loc[:, required].copy()
    frame["trading_date"] = pd.to_datetime(
        frame["trading_date"], errors="raise"
    ).dt.normalize()
    frame["underlying_symbol"] = (
        frame["underlying_symbol"].astype("string").str.strip().str.upper()
    )
    frame["on_warrant"] = pd.to_numeric(frame["on_warrant"], errors="coerce")
    if frame.duplicated(["trading_date", "underlying_symbol"]).any():
        raise ValueError("warehouse_stocks contains duplicate date/product rows")
    frame = frame.rename(columns={"underlying_symbol": "instrument"}).sort_values(
        ["instrument", "trading_date"]
    ).reset_index(drop=True)
    warrant = frame["on_warrant"].where(
        np.isfinite(frame["on_warrant"]) & frame["on_warrant"].gt(0)
    )
    previous = warrant.groupby(frame["instrument"], sort=False).shift(lookback)
    count = rolling_count(warrant, frame["instrument"], window=lookback + 1)
    raw = np.log(warrant / previous).where(count.eq(lookback + 1))
    frame["raw_factor"] = raw.where(np.isfinite(raw))
    return frame.loc[:, ["trading_date", "instrument", "raw_factor"]]


def build(inputs: dict) -> pd.DataFrame:
    raw = calculate_receipt_mom_20(inputs["warehouse_stocks"])
    return standard_table(
        raw,
        inputs["universe"],
        factor_name=FACTOR_NAME,
        signal_scale=SIGNAL_SCALE,
        family="F_inventory_and_spot",
        definition="log_on_warrant_ratio_20d",
        lookback_trading_periods=20,
        source="rqdatac.futures.get_warehouse_stocks.on_warrant",
        direction="IC- prior; repository call: not tested",
        raw_factor_normalization="log_growth",
    )
