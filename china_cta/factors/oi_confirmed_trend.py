"""A transparent open-interest-confirmed Trend research factor."""

from __future__ import annotations

from typing import Final

import numpy as np
import pandas as pd

from china_cta.factors.schema import make_factor_table


OI_TREND_DIAGNOSTIC_COLUMNS: Final[tuple[str, ...]] = (
    "trading_date",
    "instrument",
    "dominant_order_book_id",
    "price_return",
    "open_interest_change",
    "oi_confirmation",
    "roll_in_window",
    "raw_factor",
)


def calculate_oi_confirmed_trend(
    continuous_prices: pd.DataFrame,
    dominant_map: pd.DataFrame,
    *,
    lookback: int = 20,
    price_field: str = "close",
    open_interest_field: str = "open_interest",
) -> pd.DataFrame:
    """Return the auditable components of an OI-confirmed Trend factor.

    ``raw_factor(t)`` is the lookback price return multiplied by the positive
    part of the lookback open-interest change.  A window containing an RQData
    dominant-contract change is unavailable because contract migration can
    create a mechanical open-interest jump.
    """

    if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback < 1:
        raise ValueError("lookback must be a positive integer")
    _validate_research_prices(continuous_prices)

    price_columns = (
        "trading_date",
        "underlying_symbol",
        price_field,
        open_interest_field,
    )
    missing_prices = sorted(set(price_columns) - set(continuous_prices.columns))
    if missing_prices:
        raise ValueError(f"continuous_prices is missing fields: {missing_prices}")

    map_columns = (
        "trading_date",
        "underlying_symbol",
        "dominant_order_book_id",
        "changed",
    )
    missing_map = sorted(set(map_columns) - set(dominant_map.columns))
    if missing_map:
        raise ValueError(f"dominant_map is missing fields: {missing_map}")

    prices = continuous_prices.loc[:, price_columns].copy().rename(
        columns={"underlying_symbol": "instrument"}
    )
    mapping = dominant_map.loc[:, map_columns].copy().rename(
        columns={"underlying_symbol": "instrument"}
    )
    for frame in (prices, mapping):
        frame["trading_date"] = pd.to_datetime(
            frame["trading_date"], errors="raise"
        ).dt.normalize()
        frame["instrument"] = (
            frame["instrument"].astype("string").str.strip().str.upper()
        )
    mapping["dominant_order_book_id"] = (
        mapping["dominant_order_book_id"]
        .astype("string")
        .str.strip()
        .str.upper()
    )
    mapping["changed"] = mapping["changed"].astype("boolean")

    key = ["trading_date", "instrument"]
    if prices.duplicated(key).any():
        raise ValueError("continuous_prices contains duplicate date/instrument rows")
    if mapping.duplicated(key).any():
        raise ValueError("dominant_map contains duplicate date/instrument rows")

    prices[price_field] = pd.to_numeric(prices[price_field], errors="coerce")
    prices[open_interest_field] = pd.to_numeric(
        prices[open_interest_field], errors="coerce"
    )
    frame = prices.merge(mapping, on=key, how="left", validate="one_to_one")
    frame = frame.sort_values(["instrument", "trading_date"]).reset_index(drop=True)

    instrument = frame["instrument"]
    valid_price = frame[price_field].where(
        np.isfinite(frame[price_field]) & frame[price_field].gt(0)
    )
    valid_open_interest = frame[open_interest_field].where(
        np.isfinite(frame[open_interest_field]) & frame[open_interest_field].gt(0)
    )
    base_price = valid_price.groupby(instrument, sort=False).shift(lookback)
    base_open_interest = valid_open_interest.groupby(instrument, sort=False).shift(
        lookback
    )
    price_count = valid_price.groupby(instrument, sort=False).transform(
        lambda values: values.rolling(
            lookback + 1, min_periods=lookback + 1
        ).count()
    )
    open_interest_count = valid_open_interest.groupby(
        instrument, sort=False
    ).transform(
        lambda values: values.rolling(
            lookback + 1, min_periods=lookback + 1
        ).count()
    )
    map_valid = frame["dominant_order_book_id"].notna().astype("int64")
    map_count = map_valid.groupby(instrument, sort=False).transform(
        lambda values: values.rolling(
            lookback + 1, min_periods=lookback + 1
        ).sum()
    )
    changed = frame["changed"].fillna(True).astype("int64")
    roll_count = changed.groupby(instrument, sort=False).transform(
        lambda values: values.rolling(
            lookback + 1, min_periods=lookback + 1
        ).sum()
    )

    # 主力切换会机械改变 OI；只要回看窗口内换过主力，该日因子就明确不可用。
    price_return = valid_price / base_price - 1.0
    open_interest_change = valid_open_interest / base_open_interest - 1.0
    # OI 仅作趋势确认：持仓下降不会反转价格方向，而是把确认强度降为 0。
    oi_confirmation = open_interest_change.clip(lower=0.0)
    complete_window = (
        price_count.eq(lookback + 1)
        & open_interest_count.eq(lookback + 1)
        & map_count.eq(lookback + 1)
        & roll_count.eq(0)
    )

    result = frame.loc[:, ["trading_date", "instrument", "dominant_order_book_id"]].copy()
    result["price_return"] = price_return.where(complete_window)
    result["open_interest_change"] = open_interest_change.where(complete_window)
    result["oi_confirmation"] = oi_confirmation.where(complete_window)
    result["roll_in_window"] = roll_count.gt(0).astype("boolean").where(
        roll_count.notna()
    )
    result["raw_factor"] = (price_return * oi_confirmation).where(complete_window)
    return result.loc[:, OI_TREND_DIAGNOSTIC_COLUMNS]


def compute_oi_confirmed_trend_factor(
    continuous_prices: pd.DataFrame,
    dominant_map: pd.DataFrame,
    universe: pd.DataFrame,
    *,
    lookback: int = 20,
    signal_scale: float = 0.02,
    price_field: str = "close",
    open_interest_field: str = "open_interest",
) -> pd.DataFrame:
    """Return the standard factor table for OI-confirmed Trend."""

    diagnostics = calculate_oi_confirmed_trend(
        continuous_prices,
        dominant_map,
        lookback=lookback,
        price_field=price_field,
        open_interest_field=open_interest_field,
    )
    result = make_factor_table(
        diagnostics.loc[:, ["trading_date", "instrument", "raw_factor"]],
        universe,
        factor_name=f"oi_confirmed_trend_{lookback}d",
        signal_scale=signal_scale,
    )
    result.attrs.update(
        {
            "definition": (
                "(price_t / price_t_minus_lookback - 1) * "
                "max(open_interest_t / open_interest_t_minus_lookback - 1, 0)"
            ),
            "lookback_trading_periods": lookback,
            "price_field": price_field,
            "open_interest_field": open_interest_field,
            "adjust_method": "prev_close_ratio",
            "roll_window_rule": "unavailable_if_rule0_rank1_dominant_changes",
        }
    )
    return result


def _validate_research_prices(continuous_prices: pd.DataFrame) -> None:
    if continuous_prices.attrs.get("usage") != "signal_research_only":
        raise ValueError("OI-confirmed Trend requires research continuous prices")
    if continuous_prices.attrs.get("cash_pnl_allowed") is not False:
        raise ValueError("OI-confirmed Trend input cannot be used for cash P&L")
    if continuous_prices.attrs.get("adjust_type") != "pre" or continuous_prices.attrs.get(
        "adjust_method"
    ) != "prev_close_ratio":
        raise ValueError(
            "OI-confirmed Trend requires pre-adjusted prev_close_ratio prices"
        )
