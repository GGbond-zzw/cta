"""Carry scaled by 20-day realized volatility (qualified)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from china_cta.factors.cta_common import (
    annualized_volatility,
    normalize_continuous,
    standard_table,
)
from china_cta.factors.cta_curve import calculate_curve_metrics


FACTOR_NAME = "vol_scaled_carry"
SIGNAL_SCALE = 0.50


def calculate_vol_scaled_carry(
    contract_snapshots: pd.DataFrame,
    continuous_prices: pd.DataFrame,
    *,
    min_days_to_maturity: int = 30,
    volatility_window: int = 20,
) -> pd.DataFrame:
    metrics = calculate_curve_metrics(
        contract_snapshots, min_days_to_maturity=min_days_to_maturity
    )
    prices = normalize_continuous(continuous_prices, ("close",))
    volatility = annualized_volatility(
        prices["close"], prices["instrument"], window=volatility_window
    )
    vol_frame = pd.DataFrame(
        {
            "trading_date": prices["trading_date"],
            "instrument": prices["instrument"],
            "annualized_volatility": volatility,
        }
    )
    frame = metrics.loc[
        :, ["trading_date", "instrument", "carry_ann"]
    ].merge(
        vol_frame,
        on=["trading_date", "instrument"],
        how="left",
        validate="one_to_one",
    )
    frame["raw_factor"] = frame["carry_ann"] / frame[
        "annualized_volatility"
    ].where(frame["annualized_volatility"].gt(0))
    frame["raw_factor"] = frame["raw_factor"].where(
        np.isfinite(frame["raw_factor"])
    )
    return frame.loc[:, ["trading_date", "instrument", "raw_factor"]]


def build(inputs: dict) -> pd.DataFrame:
    raw = calculate_vol_scaled_carry(
        inputs["contract_snapshots"], inputs["continuous_prices"]
    )
    return standard_table(
        raw,
        inputs["universe"],
        factor_name=FACTOR_NAME,
        signal_scale=SIGNAL_SCALE,
        family="C_carry_and_roll",
        definition="carry_ann_divided_by_20d_annualized_volatility",
        min_days_to_maturity=30,
        volatility_window=20,
        price_field="close",
        direction="IC+ prior; repository call: IC- in China",
        raw_factor_normalization="volatility_scaled",
    )
