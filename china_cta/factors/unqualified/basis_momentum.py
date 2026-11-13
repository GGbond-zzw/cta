"""Basis-momentum from first- and second-nearby futures strategies."""

from __future__ import annotations

from typing import Final

import numpy as np
import pandas as pd

from china_cta.factors.schema import make_factor_table


BASIS_MOMENTUM_DIAGNOSTIC_COLUMNS: Final[tuple[str, ...]] = (
    "trading_date",
    "instrument",
    "first_contract",
    "second_contract",
    "first_holding_contract",
    "second_holding_contract",
    "first_return",
    "second_return",
    "first_momentum",
    "second_momentum",
    "raw_factor",
)


def calculate_basis_momentum(
    contract_snapshots: pd.DataFrame,
    *,
    lookback: int = 252,
    min_days_to_maturity: int = 60,
) -> pd.DataFrame:
    """Calculate first-nearby momentum minus second-nearby momentum.

    Contracts are selected at each close by increasing maturity, after
    excluding contracts too close to expiry.  The return dated ``t`` prices
    the contracts selected on the preceding observation at both ``t-1`` and
    ``t``.  Consequently, a roll changes the next holding but never creates a
    return by comparing two different contracts.

    ``raw_factor(t) = prod(1 + first_return, lookback)
                    - prod(1 + second_return, lookback)``

    Every return in both windows must be available. Missing prices are not
    filled and the selector never substitutes a farther contract merely
    because a selected contract has no close price.
    """

    if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback < 1:
        raise ValueError("lookback must be a positive integer")
    if (
        isinstance(min_days_to_maturity, bool)
        or not isinstance(min_days_to_maturity, int)
        or min_days_to_maturity < 0
    ):
        raise ValueError("min_days_to_maturity must be a non-negative integer")

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

    snapshots = contract_snapshots.loc[:, required].copy()
    snapshots["trading_date"] = pd.to_datetime(
        snapshots["trading_date"], errors="raise"
    ).dt.normalize()
    snapshots["maturity_date"] = pd.to_datetime(
        snapshots["maturity_date"], errors="coerce"
    ).dt.normalize()
    for column in ("underlying_symbol", "order_book_id", "price_field"):
        snapshots[column] = snapshots[column].astype("string").str.strip()
    snapshots["underlying_symbol"] = snapshots["underlying_symbol"].str.upper()
    snapshots["order_book_id"] = snapshots["order_book_id"].str.upper()
    snapshots["price_field"] = snapshots["price_field"].str.lower()
    snapshots["days_to_maturity"] = pd.to_numeric(
        snapshots["days_to_maturity"], errors="coerce"
    )
    snapshots["price"] = pd.to_numeric(snapshots["price"], errors="coerce")
    if snapshots.duplicated(
        ["trading_date", "underlying_symbol", "order_book_id"]
    ).any():
        raise ValueError("contract_snapshots contains duplicate contract rows")
    if snapshots["price_field"].isna().any() or snapshots[
        "price_field"
    ].ne("close").any():
        raise ValueError("basis-momentum requires close prices")

    snapshots = snapshots.sort_values(
        ["underlying_symbol", "trading_date", "maturity_date", "order_book_id"]
    ).reset_index(drop=True)
    rows: list[dict[str, object]] = []
    for instrument, product in snapshots.groupby("underlying_symbol", sort=True):
        previous_selection: tuple[str, str, float, float] | None = None
        for trading_date, curve in product.groupby("trading_date", sort=True):
            eligible = curve.loc[
                curve["maturity_date"].notna()
                & curve["days_to_maturity"].gt(min_days_to_maturity)
            ].sort_values(["maturity_date", "order_book_id"])
            first = eligible.iloc[0] if len(eligible) >= 1 else None
            second = eligible.iloc[1] if len(eligible) >= 2 else None

            first_return = np.nan
            second_return = np.nan
            first_holding_contract: object = pd.NA
            second_holding_contract: object = pd.NA
            if previous_selection is not None:
                (
                    previous_first_id,
                    previous_second_id,
                    previous_first_price,
                    previous_second_price,
                ) = previous_selection
                first_holding_contract = previous_first_id
                second_holding_contract = previous_second_id
                prices_by_contract = curve.set_index("order_book_id")["price"]
                current_first_price = prices_by_contract.get(
                    previous_first_id, np.nan
                )
                current_second_price = prices_by_contract.get(
                    previous_second_id, np.nan
                )
                if _valid_price(previous_first_price) and _valid_price(
                    current_first_price
                ):
                    first_return = current_first_price / previous_first_price - 1.0
                if _valid_price(previous_second_price) and _valid_price(
                    current_second_price
                ):
                    second_return = (
                        current_second_price / previous_second_price - 1.0
                    )

            rows.append(
                {
                    "trading_date": trading_date,
                    "instrument": instrument,
                    "first_contract": (
                        first["order_book_id"] if first is not None else pd.NA
                    ),
                    "second_contract": (
                        second["order_book_id"] if second is not None else pd.NA
                    ),
                    "first_holding_contract": first_holding_contract,
                    "second_holding_contract": second_holding_contract,
                    "first_return": first_return,
                    "second_return": second_return,
                }
            )
            previous_selection = (
                str(first["order_book_id"]),
                str(second["order_book_id"]),
                float(first["price"]) if _valid_price(first["price"]) else np.nan,
                float(second["price"])
                if _valid_price(second["price"])
                else np.nan,
            ) if first is not None and second is not None else None

    result = pd.DataFrame(rows)
    if result.empty:
        return pd.DataFrame(columns=BASIS_MOMENTUM_DIAGNOSTIC_COLUMNS)
    result = result.sort_values(["instrument", "trading_date"]).reset_index(drop=True)
    first_grouped = result["first_return"].groupby(result["instrument"], sort=False)
    second_grouped = result["second_return"].groupby(
        result["instrument"], sort=False
    )
    result["first_momentum"] = first_grouped.transform(
        lambda values: (1.0 + values).rolling(
            lookback, min_periods=lookback
        ).apply(np.prod, raw=True) - 1.0
    )
    result["second_momentum"] = second_grouped.transform(
        lambda values: (1.0 + values).rolling(
            lookback, min_periods=lookback
        ).apply(np.prod, raw=True) - 1.0
    )
    result["raw_factor"] = result["first_momentum"] - result["second_momentum"]
    return result.loc[:, BASIS_MOMENTUM_DIAGNOSTIC_COLUMNS]


def compute_basis_momentum_factor(
    contract_snapshots: pd.DataFrame,
    universe: pd.DataFrame,
    *,
    lookback: int = 252,
    min_days_to_maturity: int = 60,
    signal_scale: float = 0.20,
) -> pd.DataFrame:
    """Return the standard factor table for commodity basis-momentum."""

    diagnostics = calculate_basis_momentum(
        contract_snapshots,
        lookback=lookback,
        min_days_to_maturity=min_days_to_maturity,
    )
    result = make_factor_table(
        diagnostics.loc[:, ["trading_date", "instrument", "raw_factor"]],
        universe,
        factor_name=f"basis_momentum_{lookback}d",
        signal_scale=signal_scale,
    )
    result.attrs.update(
        {
            "definition": (
                "compound_return(first_nearby_strategy, lookback) - "
                "compound_return(second_nearby_strategy, lookback)"
            ),
            "lookback_trading_periods": lookback,
            "min_days_to_maturity": min_days_to_maturity,
            "price_field": "close",
            "contract_selection": (
                "first_two_real_contracts_by_maturity_after_expiry_buffer"
            ),
            "return_construction": (
                "previous_close_selection_priced_on_same_contract_next_observation"
            ),
            "direction": "long_positive_basis_momentum_short_negative",
            "raw_factor_normalization": "none",
        }
    )
    return result


def _valid_price(value: object) -> bool:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return bool(np.isfinite(numeric) and numeric > 0)


def build(inputs: dict) -> pd.DataFrame:
    return compute_basis_momentum_factor(
        inputs["contract_snapshots"], inputs["universe"]
    )
