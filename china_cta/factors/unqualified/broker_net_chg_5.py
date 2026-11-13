"""Top-20 member net-long change scaled by total OI (unqualified)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from china_cta.factors.cta_common import standard_table, total_open_interest


FACTOR_NAME = "broker_net_chg_5"
SIGNAL_SCALE = 0.02


def calculate_broker_net_chg_5(
    contract_snapshots: pd.DataFrame,
    member_rank: pd.DataFrame,
    *,
    top_n: int = 20,
    lookback: int = 5,
) -> pd.DataFrame:
    if top_n < 1:
        raise ValueError("top_n must be a positive integer")
    if lookback < 1:
        raise ValueError("lookback must be a positive integer")
    required = ("trading_date", "underlying_symbol", "side", "rank", "volume")
    missing = sorted(set(required) - set(member_rank.columns))
    if missing:
        raise ValueError(f"member_rank is missing fields: {missing}")
    members = member_rank.loc[:, required].copy()
    members["trading_date"] = pd.to_datetime(
        members["trading_date"], errors="raise"
    ).dt.normalize()
    members["underlying_symbol"] = (
        members["underlying_symbol"].astype("string").str.strip().str.upper()
    )
    members["side"] = members["side"].astype("string").str.lower()
    members["rank"] = pd.to_numeric(members["rank"], errors="coerce")
    members["volume"] = pd.to_numeric(members["volume"], errors="coerce")
    members = members.loc[
        members["rank"].le(top_n)
        & members["volume"].gt(0)
        & members["side"].isin(["long", "short"])
    ]
    if members.duplicated(
        ["trading_date", "underlying_symbol", "side", "rank"]
    ).any():
        raise ValueError("member_rank contains duplicate date/product/side/rank rows")
    top = (
        members.groupby(["trading_date", "underlying_symbol", "side"], sort=True)[
            "volume"
        ]
        .sum()
        .unstack("side")
    )
    if "long" not in top.columns or "short" not in top.columns:
        raise ValueError("member_rank must contain both long and short sides")
    net = (top["long"] - top["short"]).rename("net_long").reset_index().rename(
        columns={"underlying_symbol": "instrument"}
    )

    totals = total_open_interest(contract_snapshots, minimum_contracts=2).rename(
        columns={"total_open_interest": "total_oi"}
    )
    frame = net.merge(
        totals, on=["trading_date", "instrument"], how="left", validate="one_to_one"
    )
    frame = frame.sort_values(["instrument", "trading_date"]).reset_index(drop=True)
    previous_net = frame.groupby("instrument", sort=False)["net_long"].shift(
        lookback
    )
    count = frame.groupby("instrument", sort=False)["net_long"].transform(
        lambda values: values.rolling(
            lookback + 1, min_periods=lookback + 1
        ).count()
    )
    raw = (frame["net_long"] - previous_net) / frame["total_oi"].where(
        frame["total_oi"].gt(0)
    )
    frame["raw_factor"] = raw.where(count.eq(lookback + 1) & np.isfinite(raw))
    return frame.loc[:, ["trading_date", "instrument", "raw_factor"]]


def build(inputs: dict) -> pd.DataFrame:
    raw = calculate_broker_net_chg_5(
        inputs["contract_snapshots"], inputs["member_rank"]
    )
    return standard_table(
        raw,
        inputs["universe"],
        factor_name=FACTOR_NAME,
        signal_scale=SIGNAL_SCALE,
        family="E_positioning",
        definition="top20_member_net_long_change_5d_over_total_oi",
        top_n=20,
        lookback_trading_periods=5,
        member_rank_by="long_and_short",
        direction="IC+ prior; repository call: not tested",
        raw_factor_normalization="open_interest",
    )
