"""Small, read-only reconciliation of RQAlpha close-based futures MTM."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd


def reconcile_close_based_mtm(
    formal_result: Mapping[str, Any],
) -> dict[str, pd.DataFrame]:
    """Reconcile daily close-based position P&L without rebuilding accounting.

    This helper is deliberately limited to the Phase 6 Golden configuration:
    daily ``current_bar`` matching, close-price settlement, and zero slippage.
    It independently recomputes only the transparent price component

    ``previous close position * close change * contract multiplier``.

    RQAlpha remains the source of truth for trading P&L, transaction costs,
    margin, account equity, and NAV. The returned daily table combines the
    manual price component with those native fields solely to expose a
    reconciliation difference.
    """

    metadata = formal_result.get("metadata", {})
    formal_config = metadata.get("formal_config", {})
    required_config = {
        "frequency": "1d",
        "matching_type": "current_bar",
        "futures_settlement_price_type": "close",
        "slippage_value": 0,
    }
    mismatches = {
        key: formal_config.get(key)
        for key, expected in required_config.items()
        if formal_config.get(key) != expected
    }
    if mismatches:
        raise ValueError(
            "Golden close-based MTM reconciliation requires "
            f"{required_config}; mismatches={mismatches}"
        )

    account = _require_frame(formal_result, "future_account")
    positions = _require_frame(formal_result, "future_positions")
    trades = _require_frame(formal_result, "trades")
    _require_columns(
        account,
        (
            "position_pnl",
            "trading_pnl",
            "daily_pnl",
            "transaction_cost",
            "total_value",
            "margin",
        ),
        "future_account",
    )
    _require_columns(
        positions,
        ("order_book_id", "contract_multiplier", "last_price"),
        "future_positions",
    )
    _require_columns(
        trades,
        (
            "trading_datetime",
            "order_book_id",
            "last_price",
            "commission",
            "transaction_cost",
        ),
        "trades",
    )

    account_daily = account.copy()
    account_daily.index = pd.to_datetime(account_daily.index).normalize()
    if account_daily.index.has_duplicates:
        raise ValueError("future_account must have one row per trading date")
    dates = pd.DatetimeIndex(account_daily.index).sort_values()

    position_rows = positions.reset_index(names="trading_date").copy()
    position_rows["trading_date"] = pd.to_datetime(
        position_rows["trading_date"]
    ).dt.normalize()
    position_rows["position_at_close"] = (
        _numeric_column(position_rows, "LONG_quantity", default=0.0)
        - _numeric_column(position_rows, "SHORT_quantity", default=0.0)
    )

    trade_rows = trades.copy()
    trade_rows["trading_date"] = pd.to_datetime(
        trade_rows["trading_datetime"]
    ).dt.normalize()
    price_from_trades = _unique_daily_trade_prices(trade_rows)
    price_from_positions = position_rows.loc[
        :, ["trading_date", "order_book_id", "last_price"]
    ].rename(columns={"last_price": "accounting_price"})
    observed_prices = _coalesce_prices(
        pd.concat([price_from_positions, price_from_trades], ignore_index=True)
    )

    multipliers = position_rows.loc[
        :, ["order_book_id", "contract_multiplier"]
    ].drop_duplicates()
    if multipliers["order_book_id"].duplicated().any():
        raise ValueError("A contract has inconsistent multipliers in RQAlpha results")

    contracts = sorted(
        set(position_rows["order_book_id"]) | set(trade_rows["order_book_id"])
    )
    grid = pd.MultiIndex.from_product(
        [dates, contracts], names=["trading_date", "order_book_id"]
    ).to_frame(index=False)
    contract_daily = grid.merge(
        position_rows.loc[
            :, ["trading_date", "order_book_id", "position_at_close"]
        ],
        on=["trading_date", "order_book_id"],
        how="left",
        validate="one_to_one",
    )
    contract_daily["position_at_close"] = contract_daily[
        "position_at_close"
    ].fillna(0.0)
    contract_daily = contract_daily.merge(
        observed_prices,
        on=["trading_date", "order_book_id"],
        how="left",
        validate="one_to_one",
    ).merge(
        multipliers,
        on="order_book_id",
        how="left",
        validate="many_to_one",
    )
    if contract_daily["contract_multiplier"].isna().any():
        missing = sorted(
            contract_daily.loc[
                contract_daily["contract_multiplier"].isna(), "order_book_id"
            ].unique()
        )
        raise ValueError(f"Missing contract multiplier for {missing}")

    grouped = contract_daily.groupby("order_book_id", sort=False)
    contract_daily["previous_position"] = grouped[
        "position_at_close"
    ].shift(1).fillna(0.0)
    contract_daily["previous_accounting_price"] = grouped[
        "accounting_price"
    ].shift(1)
    needs_price = contract_daily["previous_position"].ne(0)
    missing_price = needs_price & (
        contract_daily["accounting_price"].isna()
        | contract_daily["previous_accounting_price"].isna()
    )
    if missing_price.any():
        sample = contract_daily.loc[
            missing_price, ["trading_date", "order_book_id"]
        ].to_dict("records")
        raise ValueError(f"Missing accounting price while carrying a position: {sample}")

    contract_daily["price_change"] = (
        contract_daily["accounting_price"]
        - contract_daily["previous_accounting_price"]
    )
    # 只复算透明的价格变动分量用于 Golden 对账，不复制 RQAlpha 账户或保证金引擎。
    contract_daily["manual_gross_pnl_component"] = 0.0
    contract_daily.loc[needs_price, "manual_gross_pnl_component"] = (
        contract_daily.loc[needs_price, "previous_position"]
        * contract_daily.loc[needs_price, "price_change"]
        * contract_daily.loc[needs_price, "contract_multiplier"]
    )

    commission = (
        trade_rows.groupby("trading_date", sort=True)[
            ["commission", "transaction_cost"]
        ]
        .sum()
        .rename(
            columns={
                "commission": "trade_commission",
                "transaction_cost": "trade_transaction_cost",
            }
        )
    )
    daily = (
        contract_daily.groupby("trading_date", sort=True)[
            "manual_gross_pnl_component"
        ]
        .sum()
        .rename("manual_position_pnl")
        .to_frame()
        .join(account_daily, how="left")
        .join(commission, how="left")
    )
    daily[["trade_commission", "trade_transaction_cost"]] = daily[
        ["trade_commission", "trade_transaction_cost"]
    ].fillna(0.0)
    daily["manual_daily_pnl"] = (
        daily["manual_position_pnl"]
        + daily["trading_pnl"]
        - daily["transaction_cost"]
    )
    daily["reconciliation_difference"] = (
        daily["manual_daily_pnl"] - daily["daily_pnl"]
    )
    daily.index.name = "trading_date"

    contract_columns = [
        "trading_date",
        "order_book_id",
        "accounting_price",
        "previous_accounting_price",
        "price_change",
        "position_at_close",
        "previous_position",
        "contract_multiplier",
        "manual_gross_pnl_component",
    ]
    return {
        "contract_daily": contract_daily.loc[
            :, contract_columns
        ].reset_index(drop=True),
        "daily": daily.reset_index(),
    }


def _require_frame(result: Mapping[str, Any], key: str) -> pd.DataFrame:
    value = result.get(key)
    if not isinstance(value, pd.DataFrame):
        raise TypeError(f"formal_result[{key!r}] must be a DataFrame")
    if value.empty:
        raise ValueError(f"formal_result[{key!r}] cannot be empty")
    return value


def _require_columns(
    frame: pd.DataFrame, columns: tuple[str, ...], name: str
) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"{name} is missing required columns: {missing}")


def _numeric_column(
    frame: pd.DataFrame, name: str, *, default: float
) -> pd.Series:
    if name not in frame:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[name], errors="raise").fillna(default)


def _unique_daily_trade_prices(trades: pd.DataFrame) -> pd.DataFrame:
    grouped = trades.groupby(["trading_date", "order_book_id"], sort=True)[
        "last_price"
    ]
    ranges = grouped.agg(["min", "max"])
    inconsistent = ~np.isclose(
        ranges["min"], ranges["max"], rtol=0, atol=1e-12
    )
    if inconsistent.any():
        sample = ranges.loc[inconsistent].reset_index().to_dict("records")
        raise ValueError(
            "Golden close-based reconciliation requires one execution price per "
            f"contract/day; found {sample}"
        )
    return ranges["min"].rename("accounting_price").reset_index()


def _coalesce_prices(prices: pd.DataFrame) -> pd.DataFrame:
    grouped = prices.groupby(["trading_date", "order_book_id"], sort=True)[
        "accounting_price"
    ]
    ranges = grouped.agg(["min", "max"])
    inconsistent = ~np.isclose(
        ranges["min"], ranges["max"], rtol=0, atol=1e-12
    )
    if inconsistent.any():
        sample = ranges.loc[inconsistent].reset_index().to_dict("records")
        raise ValueError(
            "RQAlpha trade price and close position price differ in current-bar "
            f"Golden run: {sample}"
        )
    return ranges["min"].rename("accounting_price").reset_index()
