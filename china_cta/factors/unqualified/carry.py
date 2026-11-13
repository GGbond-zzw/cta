"""One transparent real-contract near-main Carry baseline."""

from __future__ import annotations

from typing import Final

import pandas as pd

from china_cta.factors.schema import make_factor_table


CARRY_DIAGNOSTIC_COLUMNS: Final[tuple[str, ...]] = (
    "trading_date",
    "instrument",
    "near_contract",
    "far_contract",
    "near_maturity",
    "far_maturity",
    "near_price",
    "far_price",
    "maturity_gap_days",
    "raw_factor",
)


def calculate_near_main_carry(contract_snapshots: pd.DataFrame) -> pd.DataFrame:
    """Return real-contract inputs and natural-day annualized near-main Carry.

    The far contract is the RQData rule-0/rank-1 dominant contract. The near
    contract is the earliest non-expired real contract maturing before it.
    """

    required = (
        "trading_date",
        "underlying_symbol",
        "order_book_id",
        "maturity_date",
        "days_to_maturity",
        "price",
        "price_field",
        "dominant_rank",
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
    snapshots["price"] = pd.to_numeric(snapshots["price"], errors="coerce")
    snapshots["days_to_maturity"] = pd.to_numeric(
        snapshots["days_to_maturity"], errors="coerce"
    )
    snapshots["dominant_rank"] = pd.to_numeric(
        snapshots["dominant_rank"], errors="coerce"
    )
    if snapshots.duplicated(
        ["trading_date", "underlying_symbol", "order_book_id"]
    ).any():
        raise ValueError("contract_snapshots contains duplicate contract rows")
    if snapshots["price_field"].isna().any() or snapshots["price_field"].ne("close").any():
        raise ValueError("Carry baseline requires close prices")

    rows: list[dict[str, object]] = []
    grouped = snapshots.groupby(
        ["trading_date", "underlying_symbol"], sort=True, dropna=False
    )
    for (trading_date, instrument), curve in grouped:
        # Carry 必须来自当时真实存在的月份合约；主力是 far，主力前最早未到期合约是 near。
        main_rows = curve.loc[curve["dominant_rank"].eq(1)]
        main = main_rows.iloc[0] if len(main_rows) == 1 else None
        near = None
        if main is not None and pd.notna(main["maturity_date"]):
            near_candidates = curve.loc[
                curve["maturity_date"].notna()
                & curve["maturity_date"].lt(main["maturity_date"])
                & curve["days_to_maturity"].gt(0)
            ].sort_values(["maturity_date", "order_book_id"])
            if not near_candidates.empty:
                near = near_candidates.iloc[0]

        near_maturity = near["maturity_date"] if near is not None else pd.NaT
        far_maturity = main["maturity_date"] if main is not None else pd.NaT
        maturity_gap = (
            (far_maturity - near_maturity).days
            if pd.notna(near_maturity) and pd.notna(far_maturity)
            else pd.NA
        )
        near_price = near["price"] if near is not None else pd.NA
        far_price = main["price"] if main is not None else pd.NA
        raw_factor = pd.NA
        if (
            pd.notna(maturity_gap)
            and maturity_gap > 0
            and pd.notna(near_price)
            and pd.notna(far_price)
            and near_price > 0
            and far_price > 0
        ):
            raw_factor = (near_price / far_price - 1.0) * 365.0 / maturity_gap

        rows.append(
            {
                "trading_date": trading_date,
                "instrument": instrument,
                "near_contract": near["order_book_id"] if near is not None else pd.NA,
                "far_contract": main["order_book_id"] if main is not None else pd.NA,
                "near_maturity": near_maturity,
                "far_maturity": far_maturity,
                "near_price": near_price,
                "far_price": far_price,
                "maturity_gap_days": maturity_gap,
                "raw_factor": raw_factor,
            }
        )

    result = pd.DataFrame(rows, columns=CARRY_DIAGNOSTIC_COLUMNS)
    for column in ("near_price", "far_price", "raw_factor"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result["maturity_gap_days"] = pd.array(
        result["maturity_gap_days"], dtype="Int64"
    )
    return result


def compute_carry_factor(
    contract_snapshots: pd.DataFrame,
    universe: pd.DataFrame,
    *,
    signal_scale: float = 0.20,
) -> pd.DataFrame:
    """Return the standard factor table for near-main annualized Carry."""

    diagnostics = calculate_near_main_carry(contract_snapshots)
    result = make_factor_table(
        diagnostics.loc[:, ["trading_date", "instrument", "raw_factor"]],
        universe,
        factor_name="carry_near_main",
        signal_scale=signal_scale,
    )
    result.attrs.update(
        {
            "definition": "(near_close / main_close - 1) * 365 / maturity_gap_days",
            "contract_selection": "earliest_non_expired_contract_before_rule0_rank1_main",
            "price_field": "close",
        }
    )
    return result


def build(inputs: dict) -> pd.DataFrame:
    return compute_carry_factor(
        inputs["contract_snapshots"], inputs["universe"]
    )
