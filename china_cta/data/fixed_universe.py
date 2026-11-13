"""Load one screened commodity list as a fixed set for an entire backtest.

This is intentionally ex-post for dates before the list's ranking month. It
does not manufacture prices or eligibility before a product was listed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


DEFAULT_FIXED_POOL_FILE = Path(
    "results/liquidity_monthly_2026-09/selected_products.json"
)


@dataclass(frozen=True)
class FixedProductPool:
    products: tuple[str, ...]
    holding_month: str
    source_file: Path

    @property
    def run_suffix(self) -> str:
        return f"fixedpool_{self.holding_month.replace('-', '_')}"


def load_fixed_product_pool(path: Path = DEFAULT_FIXED_POOL_FILE) -> FixedProductPool:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Fixed product list not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    month = payload.get("holding_month")
    if not isinstance(month, str) or len(month) != 7 or str(pd.Period(month, freq="M")) != month:
        raise ValueError(f"Invalid holding_month in {path}")
    if (payload.get("ranking_month") != str(pd.Period(month, freq="M") - 1)
            or payload.get("daily_top_share") != 0.6
            or payload.get("daily_lookback_days") != 60
            or payload.get("monthly_ordering") != "median of daily v2 liquidity scores"):
        raise ValueError(f"File was not produced by the agreed monthly screening method: {path}")
    products = payload.get("products")
    if (not isinstance(products, list) or len(products) != 30
            or any(not isinstance(symbol, str) or not symbol or symbol != symbol.upper()
                   for symbol in products)
            or len(set(products)) != 30):
        raise ValueError(f"Expected 30 unique uppercase products in {path}")
    return FixedProductPool(tuple(products), month, path.resolve())
