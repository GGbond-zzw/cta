"""Thin Phase 5 Target Position to RQAlpha Plus formal-backtest bridge."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final, Mapping

import pandas as pd
from rqalpha.apis import instruments, order_to, update_universe
from rqalpha_plus import run_func

from china_cta.formal_backtest.results import load_formal_result


TARGET_POSITION_COLUMNS: Final[tuple[str, ...]] = (
    "trading_date",
    "order_book_id",
    "target_quantity",
    "source_tag",
)
ORDER_COLUMNS: Final[tuple[str, ...]] = (
    "target_trading_date",
    "order_book_id",
    "requested_target_quantity",
    "source_tag",
    "implicit_zero",
    "order_id",
    "quantity",
    "filled_quantity",
    "unfilled_quantity",
    "status",
    "message",
    "side",
    "position_effect",
    "avg_price",
    "transaction_cost",
)
TARGET_EXECUTION_COLUMNS: Final[tuple[str, ...]] = (
    "target_trading_date",
    "order_book_id",
    "requested_target_quantity",
    "source_tag",
    "implicit_zero",
    "order_count",
)

_ACTUAL_FUTURE_PATTERN = re.compile(r"^[A-Z]{1,2}\d{4}$")
_SUPPORTED_DAILY_MATCHING = frozenset({"current_bar", "vwap"})
_SUPPORTED_SLIPPAGE_MODELS = frozenset(
    {"PriceRatioSlippage", "TickSizeSlippage"}
)


@dataclass(frozen=True, slots=True)
class FormalBacktestConfig:
    """All explicit settings that define the Phase 6 v1 formal run."""

    start_date: str
    end_date: str
    initial_capital: float
    data_bundle_path: str | Path
    output_root: str | Path = "results/formal_backtest"
    frequency: str = "1d"
    matching_type: str = "current_bar"
    volume_limit: bool = True
    volume_percent: float = 0.25
    price_limit: bool = True
    inactive_limit: bool = True
    slippage_model: str = "PriceRatioSlippage"
    slippage_value: float = 0.0
    futures_time_series_trading_parameters: bool = True
    futures_settlement_price_type: str = "close"
    futures_commission_multiplier: float = 1.0
    margin_multiplier: float = 1.0
    capital_gain_tax_rate: float = 0.0
    auto_update_bundle: bool = False
    log_level: str = "warning"
    strategy_name: str = "cta_phase6_formal_v1"


def run_formal_backtest(
    target_positions: pd.DataFrame,
    config: FormalBacktestConfig,
    *,
    rebalance_dates: Iterable[object] | None = None,
) -> dict[str, Any]:
    """Run a daily RQAlpha Plus backtest from complete target snapshots.

    A target row's ``trading_date`` is its effective / earliest execution
    trading date.  On that date's daily ``handle_bar`` callback, the adapter
    submits ``order_to(actual_contract, target_quantity)`` without another
    date shift. ``rebalance_dates`` identifies complete snapshot dates,
    including snapshots with no target rows. Contracts targeted previously but
    absent from a later snapshot are submitted with target 0. Dates outside
    ``rebalance_dates`` do not rebalance and leave prior targets unchanged.
    """

    _validate_config(config)
    if rebalance_dates is None:
        rebalance_dates = target_positions.attrs.get("rebalance_dates")
    targets = _normalize_target_positions(target_positions, config)
    normalized_rebalance_dates = _normalize_rebalance_dates(
        targets, rebalance_dates, config
    )
    versions = _installed_versions()
    target_fingerprint = _target_fingerprint(targets, normalized_rebalance_dates)
    config_metadata = _config_metadata(config)
    run_fingerprint = _run_fingerprint(
        target_fingerprint, config_metadata, versions
    )

    output_root = Path(config.output_root).expanduser().resolve()
    run_directory = output_root / run_fingerprint[:16]
    result_path = run_directory / "rqalpha_result.pkl"
    report_path = run_directory / "rqalpha_report"
    metadata_path = run_directory / "metadata.json"
    orders_path = run_directory / "orders.csv"
    executions_path = run_directory / "target_executions.csv"
    run_directory.mkdir(parents=True, exist_ok=True)

    schedule = _build_target_schedule(targets, normalized_rebalance_dates)
    contract_ids = sorted(targets["order_book_id"].unique().tolist())
    state: dict[str, Any] = {
        "processed_dates": set(),
        "seen_contracts": set(),
        "order_refs": [],
        "executions": [],
    }

    def init(context: Any) -> None:
        if contract_ids:
            _validate_rqalpha_instruments(contract_ids)
            update_universe(contract_ids)
        context.phase6_target_schedule = schedule
        context.phase6_processed_dates = state["processed_dates"]

    def handle_bar(context: Any, bar_dict: Any) -> None:
        del bar_dict
        target_date = pd.Timestamp(context.now).normalize()
        if target_date not in schedule or target_date in state["processed_dates"]:
            return
        _submit_target_snapshot(target_date, schedule[target_date], state)
        state["processed_dates"].add(target_date)

    rqalpha_config = _build_rqalpha_config(
        config,
        result_path=result_path,
        report_path=report_path,
    )
    native_result = run_func(
        config=rqalpha_config,
        init=init,
        handle_bar=handle_bar,
    )

    unprocessed_dates = sorted(set(schedule) - state["processed_dates"])
    if unprocessed_dates:
        dates = ", ".join(date.date().isoformat() for date in unprocessed_dates)
        raise RuntimeError(
            "RQAlpha did not reach Target Position trading_date(s): " + dates
        )

    orders = _snapshot_orders(state["order_refs"])
    executions = pd.DataFrame(
        state["executions"], columns=TARGET_EXECUTION_COLUMNS
    ).sort_values(["target_trading_date", "order_book_id"]).reset_index(drop=True)
    metadata = {
        "adapter_version": "phase6_rqalpha_plus_v1",
        "run_fingerprint": run_fingerprint,
        "target_fingerprint": target_fingerprint,
        "target_source_tags": sorted(targets["source_tag"].unique().tolist()),
        "target_position_schema": list(TARGET_POSITION_COLUMNS),
        "target_schedule_semantics": "complete_position_snapshot_per_trading_date",
        "rebalance_dates": [
            date.date().isoformat() for date in normalized_rebalance_dates
        ],
        "empty_complete_snapshot_dates": [
            date.date().isoformat()
            for date in normalized_rebalance_dates
            if date not in set(targets["trading_date"])
        ],
        "target_trading_date_definition": (
            "target_effective_date_earliest_execution_trading_date"
        ),
        "callback": "handle_bar",
        "order_submission_at": "daily_handle_bar_of_target_trading_date",
        "matching_at": f"rqalpha_daily_{config.matching_type}",
        "additional_adapter_lag_sessions": 0,
        "investment_decision_recomputed": False,
        "alpha_recomputed": False,
        "portfolio_recomputed": False,
        "target_quantity_recomputed": False,
        "order_bridge": "order_to(actual_contract, target_quantity)",
        "rqalpha_versions": versions,
        "formal_config": config_metadata,
        "rqalpha_config": rqalpha_config,
        "artifacts": {
            "native_result": str(result_path),
            "native_report": str(report_path),
            "metadata": str(metadata_path),
            "orders": str(orders_path),
            "target_executions": str(executions_path),
        },
    }

    loaded = load_formal_result(native_result, orders=orders, metadata=metadata)
    orders.to_csv(orders_path, index=False)
    executions.to_csv(executions_path, index=False)
    metadata_path.write_text(
        json.dumps(loaded["metadata"], ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    loaded["target_executions"] = executions
    return loaded


def _normalize_target_positions(
    target_positions: pd.DataFrame,
    config: FormalBacktestConfig,
) -> pd.DataFrame:
    missing = [
        column for column in TARGET_POSITION_COLUMNS if column not in target_positions
    ]
    if missing:
        raise ValueError(f"Target Position is missing required columns: {missing}")

    role = target_positions.attrs.get("trading_date_role")
    expected_role = "target_effective_date_earliest_execution_trading_date"
    if role is not None and role != expected_role:
        raise ValueError("Target Position trading_date semantics conflict with Phase 6")

    targets = target_positions.loc[:, TARGET_POSITION_COLUMNS].copy()
    targets["trading_date"] = pd.to_datetime(
        targets["trading_date"], errors="raise"
    )
    if targets["trading_date"].isna().any():
        raise ValueError("Target Position trading_date cannot be missing")
    if not targets["trading_date"].eq(targets["trading_date"].dt.normalize()).all():
        raise ValueError("Target Position trading_date must not contain a time component")

    targets["order_book_id"] = targets["order_book_id"].astype(str).str.strip()
    invalid_contracts = sorted(
        contract
        for contract in targets["order_book_id"].unique()
        if not _ACTUAL_FUTURE_PATTERN.fullmatch(contract)
    )
    if invalid_contracts:
        raise ValueError(
            "Target Position must contain real futures contracts, not continuous "
            f"symbols: {invalid_contracts}"
        )

    quantities = pd.to_numeric(targets["target_quantity"], errors="raise")
    if quantities.isna().any() or not quantities.map(math.isfinite).all():
        raise ValueError("target_quantity must contain finite integers")
    if not quantities.eq(quantities.round()).all():
        raise ValueError("target_quantity must contain integers")
    targets["target_quantity"] = quantities.astype("int64")

    if targets["source_tag"].isna().any():
        raise ValueError("source_tag cannot be missing")
    targets["source_tag"] = targets["source_tag"].astype(str).str.strip()
    if targets["source_tag"].eq("").any():
        raise ValueError("source_tag cannot be empty")
    if targets.duplicated(["trading_date", "order_book_id"]).any():
        raise ValueError("Target Position contains duplicate date/contract rows")

    start_date = pd.Timestamp(config.start_date).normalize()
    end_date = pd.Timestamp(config.end_date).normalize()
    outside = targets.loc[
        targets["trading_date"].lt(start_date)
        | targets["trading_date"].gt(end_date)
    ]
    if not outside.empty:
        raise ValueError("Target Position dates must be inside the formal run range")
    return targets.sort_values(["trading_date", "order_book_id"]).reset_index(
        drop=True
    )


def _normalize_rebalance_dates(
    targets: pd.DataFrame,
    rebalance_dates: Iterable[object] | None,
    config: FormalBacktestConfig,
) -> pd.DatetimeIndex:
    if rebalance_dates is None:
        dates = pd.DatetimeIndex(targets["trading_date"].unique())
    else:
        if isinstance(rebalance_dates, (str, bytes)):
            raise ValueError("rebalance_dates must be an iterable of dates")
        dates = pd.DatetimeIndex(pd.to_datetime(list(rebalance_dates), errors="raise"))

    if dates.empty:
        raise ValueError("At least one rebalance date is required")
    if dates.hasnans:
        raise ValueError("rebalance_dates cannot contain missing values")
    if dates.tz is not None:
        raise ValueError("rebalance_dates must be timezone-naive trading dates")
    if not dates.equals(dates.normalize()):
        raise ValueError("rebalance_dates must not contain a time component")
    if dates.duplicated().any():
        raise ValueError("rebalance_dates cannot contain duplicates")
    dates = dates.sort_values()

    target_dates = pd.DatetimeIndex(targets["trading_date"].unique())
    missing_target_dates = target_dates.difference(dates)
    if not missing_target_dates.empty:
        missing = ", ".join(
            date.date().isoformat() for date in missing_target_dates
        )
        raise ValueError(
            "Every Target Position date must be a rebalance date: " + missing
        )

    start_date = pd.Timestamp(config.start_date).normalize()
    end_date = pd.Timestamp(config.end_date).normalize()
    if (dates < start_date).any() or (dates > end_date).any():
        raise ValueError("rebalance_dates must be inside the formal run range")
    return dates


def _validate_config(config: FormalBacktestConfig) -> None:
    start_date = pd.Timestamp(config.start_date).normalize()
    end_date = pd.Timestamp(config.end_date).normalize()
    if start_date > end_date:
        raise ValueError("start_date cannot be after end_date")
    if config.frequency != "1d":
        raise ValueError("Phase 6 v1 supports only frequency='1d'")
    if config.matching_type not in _SUPPORTED_DAILY_MATCHING:
        raise ValueError(
            f"Daily matching_type must be one of {sorted(_SUPPORTED_DAILY_MATCHING)}"
        )
    if not math.isfinite(config.initial_capital) or config.initial_capital <= 0:
        raise ValueError("initial_capital must be a positive finite number")
    if config.volume_limit:
        if not math.isfinite(config.volume_percent) or not (
            0 < config.volume_percent <= 1
        ):
            raise ValueError("volume_percent must be in (0, 1] when enabled")
    elif not math.isfinite(config.volume_percent) or config.volume_percent < 0:
        raise ValueError("volume_percent must be non-negative")
    if config.slippage_model not in _SUPPORTED_SLIPPAGE_MODELS:
        raise ValueError(
            f"slippage_model must be one of {sorted(_SUPPORTED_SLIPPAGE_MODELS)}"
        )
    if not math.isfinite(config.slippage_value) or config.slippage_value < 0:
        raise ValueError("slippage_value must be a non-negative finite number")
    for name, value in (
        ("futures_commission_multiplier", config.futures_commission_multiplier),
        ("margin_multiplier", config.margin_multiplier),
    ):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be a positive finite number")
    if not config.futures_time_series_trading_parameters:
        raise ValueError(
            "Phase 6 formal futures runs require historical trading parameters"
        )
    if config.futures_settlement_price_type not in {"close", "settlement"}:
        raise ValueError("futures_settlement_price_type must be close or settlement")
    bundle_path = Path(config.data_bundle_path).expanduser()
    if not bundle_path.is_dir():
        raise FileNotFoundError(f"RQAlpha data bundle not found: {bundle_path}")


def _build_target_schedule(
    targets: pd.DataFrame,
    rebalance_dates: pd.DatetimeIndex,
) -> dict[pd.Timestamp, dict[str, tuple[int, str]]]:
    schedule: dict[pd.Timestamp, dict[str, tuple[int, str]]] = {
        pd.Timestamp(target_date): {} for target_date in rebalance_dates
    }
    for target_date, daily in targets.groupby("trading_date", sort=True):
        schedule[pd.Timestamp(target_date)] = {
            row.order_book_id: (int(row.target_quantity), str(row.source_tag))
            for row in daily.itertuples(index=False)
        }
    return schedule


def _submit_target_snapshot(
    target_date: pd.Timestamp,
    desired: Mapping[str, tuple[int, str]],
    state: dict[str, Any],
) -> None:
    state["seen_contracts"].update(desired)
    for contract in sorted(state["seen_contracts"]):
        if contract in desired:
            quantity, source_tag = desired[contract]
            implicit_zero = False
        else:
            quantity = 0
            source_tag = "implicit_zero_from_complete_snapshot"
            implicit_zero = True
        returned = order_to(contract, quantity)
        order_objects = _as_order_list(returned)
        state["executions"].append(
            {
                "target_trading_date": target_date,
                "order_book_id": contract,
                "requested_target_quantity": quantity,
                "source_tag": source_tag,
                "implicit_zero": implicit_zero,
                "order_count": len(order_objects),
            }
        )
        state["order_refs"].extend(
            {
                "target_trading_date": target_date,
                "order_book_id": contract,
                "requested_target_quantity": quantity,
                "source_tag": source_tag,
                "implicit_zero": implicit_zero,
                "order": order,
            }
            for order in order_objects
        )


def _as_order_list(returned: Any) -> list[Any]:
    if returned is None:
        return []
    if isinstance(returned, (list, tuple)):
        return [order for order in returned if order is not None]
    return [returned]


def _snapshot_orders(order_refs: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for reference in order_refs:
        order = reference["order"]
        rows.append(
            {
                **{key: reference[key] for key in ORDER_COLUMNS[:5]},
                "order_id": getattr(order, "order_id", None),
                "quantity": getattr(order, "quantity", None),
                "filled_quantity": getattr(order, "filled_quantity", None),
                "unfilled_quantity": getattr(order, "unfilled_quantity", None),
                "status": _enum_name(getattr(order, "status", None)),
                "message": str(getattr(order, "message", "") or ""),
                "side": _enum_name(getattr(order, "side", None)),
                "position_effect": _enum_name(
                    getattr(order, "position_effect", None)
                ),
                "avg_price": getattr(order, "avg_price", None),
                "transaction_cost": getattr(order, "transaction_cost", None),
            }
        )
    return pd.DataFrame(rows, columns=ORDER_COLUMNS).sort_values(
        ["target_trading_date", "order_book_id", "order_id"], na_position="last"
    ).reset_index(drop=True)


def _validate_rqalpha_instruments(contract_ids: list[str]) -> None:
    returned = instruments(contract_ids)
    values = returned if isinstance(returned, list) else [returned]
    by_id = {
        str(getattr(instrument, "order_book_id", "")): instrument
        for instrument in values
        if instrument is not None
    }
    missing = sorted(set(contract_ids) - set(by_id))
    if missing:
        raise ValueError(f"RQAlpha bundle does not contain contracts: {missing}")
    non_futures = sorted(
        contract
        for contract, instrument in by_id.items()
        if "FUTURE" not in _enum_name(getattr(instrument, "type", None)).upper()
    )
    if non_futures:
        raise ValueError(f"Target schedule contains non-futures: {non_futures}")


def _build_rqalpha_config(
    config: FormalBacktestConfig,
    *,
    result_path: Path,
    report_path: Path,
) -> dict[str, Any]:
    return {
        "base": {
            "start_date": pd.Timestamp(config.start_date).date().isoformat(),
            "end_date": pd.Timestamp(config.end_date).date().isoformat(),
            "frequency": config.frequency,
            "accounts": {"future": float(config.initial_capital)},
            "data_bundle_path": str(
                Path(config.data_bundle_path).expanduser().resolve()
            ),
            "init_positions": "",
            "round_price": False,
            "forced_liquidation": True,
            "margin_multiplier": float(config.margin_multiplier),
            "futures_time_series_trading_parameters": (
                config.futures_time_series_trading_parameters
            ),
            "auto_update_bundle": config.auto_update_bundle,
            "capital_gain_tax_rate": float(config.capital_gain_tax_rate),
        },
        "extra": {
            "log_level": config.log_level,
            "enable_profiler": False,
            "log_file": None,
        },
        "mod": {
            "sys_accounts": {
                "validate_future_position": True,
                "auto_switch_order_value": False,
                "futures_settlement_price_type": (
                    config.futures_settlement_price_type
                ),
            },
            "sys_risk": {
                "validate_price": True,
                "validate_is_trading": True,
                "validate_cash": True,
                "validate_self_trade": False,
            },
            "sys_simulation": {
                "enabled": True,
                "signal": False,
                "matching_type": config.matching_type,
                "price_limit": config.price_limit,
                "liquidity_limit": False,
                "volume_limit": config.volume_limit,
                "volume_percent": float(config.volume_percent),
                "slippage_model": config.slippage_model,
                "slippage": float(config.slippage_value),
                "inactive_limit": config.inactive_limit,
                "management_fee": [],
            },
            "sys_transaction_cost": {
                "enabled": True,
                "futures_commission_multiplier": float(
                    config.futures_commission_multiplier
                ),
            },
            "sys_analyser": {
                "enabled": True,
                "record": True,
                "strategy_name": config.strategy_name,
                "benchmark": None,
                "output_file": str(result_path),
                "report_save_path": str(report_path),
                "plot": False,
                "plot_save_file": None,
            },
            "sys_progress": {"enabled": False, "show": False},
        },
    }


def _config_metadata(config: FormalBacktestConfig) -> dict[str, Any]:
    values = asdict(config)
    values["start_date"] = pd.Timestamp(config.start_date).date().isoformat()
    values["end_date"] = pd.Timestamp(config.end_date).date().isoformat()
    values["data_bundle_path"] = str(
        Path(config.data_bundle_path).expanduser().resolve()
    )
    values["output_root"] = str(Path(config.output_root).expanduser().resolve())
    values["account_type"] = "FUTURE"
    return values


def _installed_versions() -> dict[str, str]:
    return {
        distribution: importlib.metadata.version(distribution)
        for distribution in ("rqalpha", "rqalpha-plus", "rqdatac")
    }


def _target_fingerprint(
    targets: pd.DataFrame,
    rebalance_dates: pd.DatetimeIndex,
) -> str:
    canonical = targets.copy()
    canonical["trading_date"] = canonical["trading_date"].dt.strftime("%Y-%m-%d")
    payload = canonical.to_dict(orient="records")
    target_dates = set(targets["trading_date"])
    empty_snapshot_dates = [
        date.date().isoformat()
        for date in rebalance_dates
        if date not in target_dates
    ]
    if empty_snapshot_dates:
        return _json_sha256(
            {
                "target_positions": payload,
                "empty_complete_snapshot_dates": empty_snapshot_dates,
            }
        )
    return _json_sha256(payload)


def _run_fingerprint(
    target_fingerprint: str,
    config_metadata: Mapping[str, Any],
    versions: Mapping[str, str],
) -> str:
    result_config = dict(config_metadata)
    result_config.pop("output_root", None)
    return _json_sha256(
        {
            "target_fingerprint": target_fingerprint,
            "formal_config": result_config,
            "rqalpha_versions": dict(versions),
        }
    )


def _json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _enum_name(value: Any) -> str:
    if value is None:
        return ""
    return str(getattr(value, "name", value))
