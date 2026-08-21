"""Minimal point-in-time futures contract semantics for CTA research."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

import pandas as pd

from china_cta.data.rqdata_adapter import (
    DataValidationError,
    DateLike,
    RQDataAdapter,
)


UNIVERSE_COLUMNS: Final[tuple[str, ...]] = (
    "trading_date",
    "instrument",
    "eligible",
    "reason",
)
CONTRACT_SNAPSHOT_COLUMNS: Final[tuple[str, ...]] = (
    "trading_date",
    "underlying_symbol",
    "order_book_id",
    "maturity_date",
    "days_to_maturity",
    "price",
    "price_field",
    "volume",
    "open_interest",
    "dominant_rank",
    "has_bar",
)
ROLL_MAP_COLUMNS: Final[tuple[str, ...]] = (
    "trading_date",
    "underlying_symbol",
    "dominant_order_book_id",
    "previous_dominant_order_book_id",
    "changed",
)

_PRE_OPEN_TRADING_PARAMETERS: Final[tuple[str, ...]] = (
    "long_margin_ratio",
    "short_margin_ratio",
    "min_order_quantity",
    "max_order_quantity",
    "min_margin_ratio",
    "trade_unit",
    "price_unit",
)
_POST_CLOSE_TRADING_PARAMETERS: Final[tuple[str, ...]] = (
    "commission_type",
    "open_commission",
    "close_commission",
    "discount_rate",
    "close_commission_today",
)
_EXCHANGE_DEPENDENT_TRADING_PARAMETERS: Final[tuple[str, ...]] = (
    "non_member_limit_rate",
    "client_limit_rate",
    "non_member_limit",
    "client_limit",
    "daily_price_limit",
)


@dataclass(frozen=True, slots=True)
class ContractRoles:
    """Explicit Phase 2 contract identities for one product and date.

    Signal and trade contracts are intentionally separate fields even though
    both use RQData's rule-0/rank-1 dominant contract in the v1 baseline.
    """

    trading_date: pd.Timestamp
    underlying_symbol: str
    signal_contract: str
    trade_contract: str
    curve_contracts: tuple[str, ...]


def get_research_universe(
    adapter: RQDataAdapter,
    trading_date: DateLike,
    *,
    min_listing_history_days: int = 0,
    min_volume: float = 0.0,
    min_open_interest: float = 0.0,
) -> pd.DataFrame:
    """Return an end-of-day, point-in-time product eligibility table.

    With positive liquidity thresholds, same-day daily volume/open interest is
    used and the resulting universe is therefore only available after close.
    """

    date = _normalize_date(trading_date)
    if min_listing_history_days < 0:
        raise ValueError("min_listing_history_days cannot be negative")
    if min_volume < 0 or min_open_interest < 0:
        raise ValueError("liquidity thresholds cannot be negative")

    point_in_time_master = adapter.get_future_instruments(date)
    real_contracts = _real_contract_rows(point_in_time_master, date)
    candidate_products = sorted(
        product
        for product in real_contracts["underlying_symbol"]
        .dropna()
        .astype(str)
        .unique()
        if product
    )

    full_master = adapter.get_future_instruments()
    historical_real = full_master.loc[
        full_master["listed_date"].notna()
        & full_master["maturity_date"].notna()
        & full_master["listed_date"].le(date)
    ]
    first_listed = historical_real.groupby("underlying_symbol")[
        "listed_date"
    ].min()

    liquid_products: set[str] | None = None
    if (min_volume > 0 or min_open_interest > 0) and not real_contracts.empty:
        ids = real_contracts["order_book_id"].astype(str).tolist()
        bars = adapter.get_bars(
            ids,
            date,
            date,
            fields=("volume", "open_interest"),
        )
        bar_products = bars.merge(
            real_contracts.loc[:, ["order_book_id", "underlying_symbol"]],
            on="order_book_id",
            how="inner",
            validate="many_to_one",
        )
        liquid = bar_products.loc[
            bar_products["volume"].ge(min_volume)
            & bar_products["open_interest"].ge(min_open_interest)
        ]
        liquid_products = set(liquid["underlying_symbol"].astype(str))

    rows: list[dict[str, object]] = []
    for product in candidate_products:
        reasons: list[str] = []
        listed = first_listed.get(product, pd.NaT)
        if pd.isna(listed):
            reasons.append("missing_listing_history")
        elif (date - pd.Timestamp(listed)).days < min_listing_history_days:
            reasons.append("insufficient_listing_history")

        if liquid_products is not None and product not in liquid_products:
            reasons.append("insufficient_liquidity")

        rows.append(
            {
                "trading_date": date,
                "instrument": product,
                "eligible": not reasons,
                "reason": ";".join(reasons) if reasons else "eligible",
            }
        )

    result = pd.DataFrame(rows, columns=UNIVERSE_COLUMNS)
    if not result.empty:
        result["instrument"] = result["instrument"].astype("string")
        result["eligible"] = result["eligible"].astype(bool)
    return result


def get_contract_snapshot(
    adapter: RQDataAdapter,
    underlying_symbol: str,
    trading_date: DateLike,
    *,
    price_field: Literal["close", "settlement"] = "settlement",
) -> pd.DataFrame:
    """Return all real contracts RQData says were tradable on the date.

    Daily price, volume and open interest are end-of-day observations. Missing
    provider values are kept missing and are never forward-filled.
    """

    date = _normalize_date(trading_date)
    product = _normalize_product(underlying_symbol)
    if price_field not in ("close", "settlement"):
        raise ValueError("price_field must be 'close' or 'settlement'")

    contract_ids = adapter.get_future_contracts(product, date)
    point_in_time_master = adapter.get_future_instruments(date)
    master = point_in_time_master.loc[
        point_in_time_master["order_book_id"].isin(contract_ids),
        ["order_book_id", "underlying_symbol", "maturity_date"],
    ].copy()
    missing_master = sorted(set(contract_ids) - set(master["order_book_id"]))
    if missing_master:
        raise DataValidationError(
            "RQData get_contracts/all_instruments disagree for "
            f"{product} on {date.date()}: {missing_master}"
        )
    if not master["underlying_symbol"].eq(product).all():
        raise DataValidationError("Contract snapshot contains another product")

    bars = adapter.get_bars(
        contract_ids,
        date,
        date,
        fields=(price_field, "volume", "open_interest"),
    )
    if not bars["trading_date"].eq(date).all():
        raise DataValidationError("Contract bars do not match the requested date")
    bar_values = bars.loc[
        :,
        ["order_book_id", price_field, "volume", "open_interest"],
    ].copy()
    bar_values["has_bar"] = True

    snapshot = master.merge(
        bar_values,
        on="order_book_id",
        how="left",
        validate="one_to_one",
    )
    snapshot["has_bar"] = snapshot["has_bar"].eq(True)
    snapshot.insert(0, "trading_date", date)
    snapshot["days_to_maturity"] = (
        snapshot["maturity_date"] - date
    ).dt.days.astype("Int64")
    snapshot["price"] = snapshot.pop(price_field)
    snapshot["price_field"] = price_field

    dominant = get_dominant_contract(adapter, product, date)
    snapshot["dominant_rank"] = pd.array(
        [1 if contract == dominant else pd.NA for contract in snapshot["order_book_id"]],
        dtype="Int64",
    )
    if dominant not in set(snapshot["order_book_id"]):
        raise DataValidationError(
            f"Dominant contract {dominant} is absent from the real-contract snapshot"
        )

    return (
        snapshot.loc[:, CONTRACT_SNAPSHOT_COLUMNS]
        .sort_values(["maturity_date", "order_book_id"])
        .reset_index(drop=True)
    )


def get_curve_snapshot(
    adapter: RQDataAdapter,
    underlying_symbol: str,
    trading_date: DateLike,
    *,
    price_field: Literal["close", "settlement"] = "settlement",
) -> pd.DataFrame:
    """Return the price-bearing real-contract curve sorted by maturity."""

    snapshot = get_contract_snapshot(
        adapter,
        underlying_symbol,
        trading_date,
        price_field=price_field,
    )
    return snapshot.loc[snapshot["price"].notna()].reset_index(drop=True)


def get_dominant_contract(
    adapter: RQDataAdapter,
    underlying_symbol: str,
    trading_date: DateLike,
) -> str:
    """Return RQData rule-0/rank-1 dominant real contract for one date."""

    date = _normalize_date(trading_date)
    product = _normalize_product(underlying_symbol)
    mapping = adapter.get_dominant_map(product, date, date, rule=0, rank=1)
    exact = mapping.loc[
        mapping["trading_date"].eq(date), "dominant_order_book_id"
    ]
    if len(exact) != 1:
        raise DataValidationError(
            f"Expected one dominant contract for {product} on {date.date()}"
        )
    return str(exact.iloc[0])


def get_roll_map(
    adapter: RQDataAdapter,
    underlying_symbol: str,
    start_date: DateLike,
    end_date: DateLike,
) -> pd.DataFrame:
    """Identify RQData dominant changes without inventing a roll state machine."""

    product = _normalize_product(underlying_symbol)
    mapping = adapter.get_dominant_map(
        product,
        _normalize_date(start_date),
        _normalize_date(end_date),
        rule=0,
        rank=1,
    ).sort_values("trading_date")
    result = mapping.copy()
    result["previous_dominant_order_book_id"] = result[
        "dominant_order_book_id"
    ].shift(1).astype("string")
    result["changed"] = (
        result["previous_dominant_order_book_id"].notna()
        & result["dominant_order_book_id"].ne(
            result["previous_dominant_order_book_id"]
        )
    )
    return result.loc[:, ROLL_MAP_COLUMNS].reset_index(drop=True)


def get_contract_roles(
    adapter: RQDataAdapter,
    underlying_symbol: str,
    trading_date: DateLike,
) -> ContractRoles:
    """Return the three explicit Phase 2 contract roles for one date."""

    date = _normalize_date(trading_date)
    product = _normalize_product(underlying_symbol)
    dominant = get_dominant_contract(adapter, product, date)
    curve_contracts = adapter.get_future_contracts(product, date)
    return ContractRoles(
        trading_date=date,
        underlying_symbol=product,
        signal_contract=dominant,
        trade_contract=dominant,
        curve_contracts=curve_contracts,
    )


def get_signal_continuous_price(
    adapter: RQDataAdapter,
    underlying_symbols: str | list[str] | tuple[str, ...],
    start_date: DateLike,
    end_date: DateLike,
    *,
    fields: str | list[str] | tuple[str, ...] | None = None,
    adjust_type: str = "pre",
    adjust_method: str = "prev_close_spread",
) -> pd.DataFrame:
    """Return RQData continuous prices explicitly restricted to research.

    The output is unsuitable for cash P&L, account valuation or settlement.
    """

    frame = adapter.get_dominant_price(
        underlying_symbols,
        start_date,
        end_date,
        fields=fields,
        adjust_type=adjust_type,
        adjust_method=adjust_method,
        rule=0,
        rank=1,
    ).copy()
    frame.attrs["usage"] = "signal_research_only"
    frame.attrs["cash_pnl_allowed"] = False
    frame.attrs["adjust_type"] = adjust_type
    frame.attrs["adjust_method"] = adjust_method
    frame.attrs["rule"] = 0
    frame.attrs["rank"] = 1
    return frame


def get_trading_parameter_availability() -> pd.DataFrame:
    """Return official timing annotations for historical trading parameters."""

    groups = (
        ("pre_open", True, _PRE_OPEN_TRADING_PARAMETERS),
        ("post_close", False, _POST_CLOSE_TRADING_PARAMETERS),
        ("exchange_dependent", False, _EXCHANGE_DEPENDENT_TRADING_PARAMETERS),
    )
    return pd.DataFrame(
        [
            {
                "field": field,
                "availability": availability,
                "allowed_for_same_day_decision": allowed,
            }
            for availability, allowed, fields in groups
            for field in fields
        ]
    )


def _real_contract_rows(master: pd.DataFrame, date: pd.Timestamp) -> pd.DataFrame:
    return master.loc[
        master["listed_date"].notna()
        & master["maturity_date"].notna()
        & master["listed_date"].le(date)
        & master["maturity_date"].ge(date)
        & (master["de_listed_date"].isna() | master["de_listed_date"].ge(date))
    ].copy()


def _normalize_date(value: DateLike) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError("trading_date cannot be missing")
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_localize(None)
    return timestamp.normalize()


def _normalize_product(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("underlying_symbol must be a non-empty string")
    return value.strip().upper()
