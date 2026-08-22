"""Lightweight access to RQAlpha's native formal-backtest results."""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


def load_formal_result(
    source: str | Path | Mapping[str, Any],
    *,
    orders: pd.DataFrame | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Expose a small stable view without recomputing RQAlpha accounting.

    ``source`` may be the mapping returned by ``run_func`` or a trusted local
    ``sys_analyser.output_file`` pickle.  RQAlpha's native result remains the
    source of truth for NAV, positions, trades, fees, margin, and MTM.
    """

    native = _read_native_result(source)
    analyser = native.get("sys_analyser", native)
    if not isinstance(analyser, Mapping):
        raise TypeError("RQAlpha sys_analyser result must be a mapping")

    portfolio = _copy_frame(analyser.get("portfolio"))
    future_account = _copy_frame(analyser.get("future_account"))
    future_positions = _copy_frame(analyser.get("future_positions"))
    trades = _copy_frame(analyser.get("trades"))
    order_frame = _copy_frame(orders)

    if "transaction_cost" in future_account.columns:
        transaction_costs = future_account.loc[:, ["transaction_cost"]].copy()
        transaction_costs.attrs["source"] = "rqalpha_future_account"
    else:
        cost_columns = [
            column
            for column in ("tax", "commission", "transaction_cost")
            if column in trades.columns
        ]
        transaction_costs = trades.loc[:, cost_columns].copy()
        transaction_costs.attrs["source"] = "rqalpha_trades"

    result_metadata = dict(metadata or {})
    result_metadata.update(
        {
            "formal_result_source_of_truth": "rqalpha_sys_analyser",
            "nav_recomputed_by_loader": False,
            "mtm_recomputed_by_loader": False,
            "account_recomputed_by_loader": False,
            "native_result_keys": sorted(str(key) for key in analyser),
        }
    )

    return {
        "summary": dict(analyser.get("summary") or {}),
        "portfolio": portfolio,
        "future_account": future_account,
        "future_positions": future_positions,
        "trades": trades,
        "orders": order_frame,
        "transaction_costs": transaction_costs,
        "metadata": result_metadata,
    }


def _read_native_result(
    source: str | Path | Mapping[str, Any],
) -> Mapping[str, Any]:
    if isinstance(source, Mapping):
        return source
    path = Path(source)
    if not path.is_file():
        raise FileNotFoundError(f"RQAlpha result file not found: {path}")
    with path.open("rb") as result_file:
        result = pickle.load(result_file)  # noqa: S301 - trusted local RQAlpha file
    if not isinstance(result, Mapping):
        raise TypeError("RQAlpha output pickle must contain a mapping")
    return result


def _copy_frame(value: Any) -> pd.DataFrame:
    return value.copy() if isinstance(value, pd.DataFrame) else pd.DataFrame()
