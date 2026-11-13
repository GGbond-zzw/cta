"""Shared daily liquidity score used by the monthly 30-product selector."""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd


REAL_CONTRACT = re.compile(r"^[A-Z]{1,3}[0-9]{1,2}(0[1-9]|1[0-2])$")


@dataclass(frozen=True)
class ScreenConfig:
    window: int = 60
    top: int = 30
    min_data_share: float = 0.9
    min_active_share: float = 0.9
    min_recent_ratio: float = 0.25
    order_notional_cny: float | None = None
    max_participation: float = 0.005


def screen_products(master: pd.DataFrame, bars: pd.DataFrame,
                    dates: list[str], config: ScreenConfig) -> pd.DataFrame:
    """Score commodity products using only contract bars in the given dates."""
    master_columns = {"order_book_id", "underlying_symbol", "exchange", "product", "contract_multiplier"}
    bar_columns = {"trading_date", "order_book_id", "volume", "open_interest", "settlement"}
    if not master_columns <= set(master.columns):
        raise ValueError(f"Instrument master missing {sorted(master_columns - set(master.columns))}")
    if not bar_columns <= set(bars.columns):
        raise ValueError(f"Daily bars missing {sorted(bar_columns - set(bars.columns))}")
    master = master.loc[
        master["product"].eq("Commodity")
        & master["order_book_id"].astype(str).str.fullmatch(REAL_CONTRACT.pattern),
        ["order_book_id", "underlying_symbol", "exchange", "contract_multiplier"],
    ].drop_duplicates("order_book_id")
    bars = bars.loc[bars["trading_date"].astype(str).str[:10].isin(dates), list(bar_columns)].copy()
    bars["trading_date"] = bars["trading_date"].astype(str).str[:10]
    if bars.duplicated(["trading_date", "order_book_id"]).any():
        raise ValueError("Duplicate contract-day bars")
    data = bars.merge(master, on="order_book_id", how="inner", validate="many_to_one")
    for column in ("volume", "open_interest", "settlement", "contract_multiplier"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.loc[(data["volume"] >= 0) & (data["open_interest"] >= 0)].copy()
    data["priced"] = (data["settlement"] > 0) & (data["contract_multiplier"] > 0)
    data["turnover_cny"] = np.where(
        data["priced"], data["volume"] * data["settlement"] * data["contract_multiplier"], 0.0)
    data["oi_notional_cny"] = np.where(
        data["priced"], data["open_interest"] * data["settlement"] * data["contract_multiplier"], 0.0)
    data["covered_volume"] = np.where(data["priced"], data["volume"], 0.0)
    data["covered_oi"] = np.where(data["priced"], data["open_interest"], 0.0)
    group = ["underlying_symbol", "exchange", "trading_date"]
    daily = data.groupby(group, as_index=False).agg(
        volume_lots=("volume", "sum"), oi_lots=("open_interest", "sum"),
        covered_volume=("covered_volume", "sum"), covered_oi=("covered_oi", "sum"),
        turnover_cny=("turnover_cny", "sum"), oi_notional_cny=("oi_notional_cny", "sum"),
    )
    daily["price_covered"] = (
        (daily["covered_volume"] >= 0.95 * daily["volume_lots"])
        & (daily["covered_oi"] >= 0.95 * daily["oi_lots"])
        & (daily["covered_volume"] > 0)
    )
    proxy = data.sort_values(
        ["underlying_symbol", "exchange", "trading_date", "open_interest", "volume", "order_book_id"],
        ascending=[True, True, True, False, False, True],
    ).drop_duplicates(group)
    proxy = proxy[group + ["turnover_cny", "priced"]].rename(
        columns={"turnover_cny": "proxy_turnover_cny", "priced": "proxy_priced"})
    daily = daily.merge(proxy, on=group, how="left", validate="one_to_one")
    recent_dates = set(dates[-min(20, len(dates)):])
    rows = []
    for (symbol, exchange), group_data in daily.groupby(["underlying_symbol", "exchange"], sort=True):
        covered = group_data.loc[group_data["price_covered"] & group_data["proxy_priced"]]
        data_share = len(group_data) / len(dates)
        price_share = len(covered) / len(dates)
        recent_price_share = covered["trading_date"].isin(recent_dates).sum() / len(recent_dates)
        active_share = (group_data["volume_lots"] > 0).sum() / len(dates)
        median_turnover = covered["turnover_cny"].median()
        recent_turnover = covered.loc[covered["trading_date"].isin(recent_dates), "turnover_cny"].median()
        recent_ratio = (float(recent_turnover / median_turnover)
                        if pd.notna(recent_turnover) and pd.notna(median_turnover) and median_turnover > 0
                        else np.nan)
        p10_proxy = covered["proxy_turnover_cny"].quantile(0.1)
        capacity = float(p10_proxy * config.max_participation) if pd.notna(p10_proxy) else np.nan
        reasons = []
        if data_share < config.min_data_share:
            reasons.append("insufficient_bar_coverage")
        if price_share < config.min_data_share:
            reasons.append("insufficient_price_coverage")
        if recent_price_share < config.min_data_share:
            reasons.append("insufficient_recent_price_coverage")
        if active_share < config.min_active_share:
            reasons.append("inactive_days")
        if not np.isfinite(recent_ratio) or recent_ratio < config.min_recent_ratio:
            reasons.append("liquidity_decline")
        if not np.isfinite(p10_proxy) or p10_proxy <= 0:
            reasons.append("illiquid_trade_contract")
        if config.order_notional_cny is not None and (
                not np.isfinite(capacity) or capacity < config.order_notional_cny):
            reasons.append("order_exceeds_participation_limit")
        rows.append({
            "underlying_symbol": symbol, "exchange": exchange,
            "data_days": len(group_data), "priced_days": len(covered),
            "active_share": active_share, "recent_price_share": recent_price_share,
            "recent_turnover_ratio": recent_ratio,
            "median_volume_lots": group_data["volume_lots"].median(),
            "median_oi_lots": group_data["oi_lots"].median(),
            "median_turnover_cny": median_turnover,
            "median_oi_notional_cny": covered["oi_notional_cny"].median(),
            "p10_proxy_contract_turnover_cny": p10_proxy,
            "estimated_order_capacity_cny": capacity,
            "exclusion_reason": ";".join(reasons),
        })
    result = pd.DataFrame(rows)
    if result.empty:
        raise RuntimeError("No commodity products in daily bars")
    eligible = result["exclusion_reason"].eq("")
    result["score"] = np.nan
    if eligible.any():
        scores = pd.Series(1.0, index=result.index)
        for column, weight in {
            "median_turnover_cny": 0.40,
            "median_oi_notional_cny": 0.25,
            "p10_proxy_contract_turnover_cny": 0.25,
            "recent_turnover_ratio": 0.10,
        }.items():
            scores.loc[eligible] *= result.loc[eligible, column].rank(pct=True).clip(lower=1e-9).pow(weight)
        result.loc[eligible, "score"] = scores.loc[eligible]
    result = result.sort_values(
        ["score", "median_turnover_cny", "underlying_symbol"],
        ascending=[False, False, True], na_position="last").reset_index(drop=True)
    result.insert(0, "rank", pd.array(
        [i + 1 if ok else pd.NA for i, ok in enumerate(result["exclusion_reason"].eq(""))],
        dtype="Int64"))
    result["selected"] = result["rank"].notna() & (result["rank"] <= config.top)
    return result
