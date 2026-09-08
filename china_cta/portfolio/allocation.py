"""Minimal, auditable Phase 5 portfolio construction and contract sizing."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping

import numpy as np
import pandas as pd
import yaml

from china_cta.data.contracts import get_dominant_contract
from china_cta.data.rqdata_adapter import (
    DataValidationError,
    RQDataAdapter,
)
from china_cta.factors.schema import FACTOR_COLUMNS
from china_cta.portfolio.volatility import compute_rolling_volatility


TARGET_POSITION_COLUMNS: Final[tuple[str, ...]] = (
    "trading_date",
    "order_book_id",
    "target_quantity",
    "source_tag",
)
PORTFOLIO_MARKET_COLUMNS: Final[tuple[str, ...]] = (
    "signal_date",
    "target_effective_date",
    "instrument",
    "order_book_id",
    "trade_contract_rule",
    "trade_contract_rank",
    "trade_price",
    "price_field",
    "contract_multiplier",
    "long_margin_ratio",
    "short_margin_ratio",
    "daily_volume",
    "open_interest",
    "market_data_reason",
)
CLASSIFICATION_COLUMNS: Final[tuple[str, ...]] = (
    "instrument",
    "sector",
    "industrial_chain",
)
CONTRIBUTION_COLUMNS: Final[tuple[str, ...]] = (
    "signal_date",
    "instrument",
    "factor_name",
    "raw_factor",
    "signal",
    "strategy_weight",
    "weighted_signal_contribution",
    "vol_forecast",
    "inverse_vol_risk",
    "strategy_risk_contribution",
)
DIAGNOSTIC_COLUMNS: Final[tuple[str, ...]] = (
    "signal_date",
    "portfolio_decision_date",
    "target_effective_date",
    "instrument",
    "aggregated_signal",
    "raw_volatility",
    "vol_forecast",
    "vol_floor_applied",
    "aggregated_risk",
    "pre_instrument_cap",
    "post_instrument_cap",
    "sector",
    "sector_gross_pre_cap",
    "sector_scale",
    "sector_gross_post_cap",
    "pre_sector_cap",
    "post_sector_cap",
    "industrial_chain",
    "chain_gross_pre_cap",
    "chain_scale",
    "chain_gross_post_cap",
    "pre_chain_cap",
    "post_chain_cap",
    "estimated_portfolio_risk_pre",
    "portfolio_scale_factor",
    "post_scale_exposure",
    "estimated_portfolio_risk_post",
    "order_book_id",
    "trade_price",
    "price_field",
    "contract_multiplier",
    "contract_notional",
    "target_notional",
    "pre_margin_quantity_float",
    "margin_ratio",
    "estimated_margin_pre",
    "margin_limit",
    "margin_scale",
    "post_margin_quantity_float",
    "estimated_margin_post",
    "target_quantity",
    "daily_volume",
    "open_interest",
    "quantity_to_volume",
    "quantity_to_open_interest",
    "availability_reason",
    "margin_reason",
)


@dataclass(frozen=True, slots=True)
class PortfolioConfig:
    """Every setting that can change a Phase 5 target quantity."""

    initial_capital: float
    portfolio_vol_target: float
    volatility_method: str
    volatility_lookback: int
    minimum_volatility_observations: int
    annualization_factor: int
    volatility_floor: float
    strategy_weights: Mapping[str, float]
    instrument_cap: float | None
    sector_gross_cap: float | None
    chain_gross_cap: float | None
    risk_estimator: str
    max_margin_fraction: float
    target_lag_sessions: int
    trade_contract_rule: int
    trade_contract_rank: int
    trade_price_field: str
    rounding_rule: str
    source_tag: str


def load_product_classification(
    path: str | Path = "config/product_classification_v1.yaml",
) -> pd.DataFrame:
    """Load a small, versioned, non-secret product risk classification."""

    source = Path(path)
    if not source.is_absolute() and not source.exists():
        source = Path(__file__).resolve().parents[2] / source
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("products"), dict):
        raise ValueError("classification config must contain a products mapping")
    version = payload.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("classification config requires a non-empty version")

    rows: list[dict[str, str]] = []
    for instrument, values in payload["products"].items():
        if not isinstance(values, dict):
            raise ValueError(f"classification for {instrument!r} must be a mapping")
        rows.append(
            {
                "instrument": str(instrument).strip().upper(),
                "sector": str(values.get("sector", "")).strip(),
                "industrial_chain": str(
                    values.get("industrial_chain", "")
                ).strip(),
            }
        )
    result = _normalize_classifications(
        pd.DataFrame(rows, columns=CLASSIFICATION_COLUMNS)
    )
    result.attrs["version"] = version.strip()
    result.attrs["source"] = source.as_posix()
    return result


def prepare_portfolio_market_data(
    adapter: RQDataAdapter,
    factor_table: pd.DataFrame,
    config: PortfolioConfig,
) -> pd.DataFrame:
    """Fetch the minimal PIT real-contract inputs needed by allocation.

    A signal observed after the close of ``t`` maps to the official dominant
    contract for its configured later target session. The sizing price,
    volume, and open interest come from the real contract on ``t``. Directional
    margin ratios come from the target session's pre-open trading parameters.
    """

    _validate_config(config)
    factors = _normalize_factors(factor_table)
    pairs = factors.loc[:, ["trading_date", "instrument"]].drop_duplicates()
    pairs = pairs.sort_values(["trading_date", "instrument"]).reset_index(drop=True)
    if pairs.empty:
        return pd.DataFrame(columns=PORTFOLIO_MARKET_COLUMNS)

    first_date = pairs["trading_date"].min()
    last_date = pairs["trading_date"].max()
    calendar = adapter.get_trading_calendar(
        first_date,
        last_date + pd.DateOffset(years=1),
    )
    calendar = pd.DatetimeIndex(pd.to_datetime(calendar)).normalize().unique().sort_values()
    target_dates: dict[pd.Timestamp, pd.Timestamp] = {}
    for signal_date in pairs["trading_date"].unique():
        later = calendar[calendar > signal_date]
        if len(later) < config.target_lag_sessions:
            raise DataValidationError(
                f"No target trading session found after {signal_date.date()}"
            )
        target_dates[pd.Timestamp(signal_date)] = pd.Timestamp(
            later[config.target_lag_sessions - 1]
        )

    rows: list[dict[str, object]] = []
    for pair in pairs.itertuples(index=False):
        signal_date = pd.Timestamp(pair.trading_date)
        target_date = target_dates[signal_date]
        base: dict[str, object] = {
            "signal_date": signal_date,
            "target_effective_date": target_date,
            "instrument": pair.instrument,
            "order_book_id": pd.NA,
            "trade_contract_rule": config.trade_contract_rule,
            "trade_contract_rank": config.trade_contract_rank,
            "trade_price": np.nan,
            "price_field": config.trade_price_field,
            "contract_multiplier": np.nan,
            "long_margin_ratio": np.nan,
            "short_margin_ratio": np.nan,
            "daily_volume": np.nan,
            "open_interest": np.nan,
            "market_data_reason": "available",
        }
        try:
            # 合约按目标生效日 t+1 选择，但 sizing price 只使用信号日 t 已知的真实合约结算价。
            contract = get_dominant_contract(
                adapter,
                pair.instrument,
                target_date,
            )
        except DataValidationError:
            base["market_data_reason"] = "dominant_contract_unavailable"
            rows.append(base)
            continue

        bars = adapter.get_bars(
            contract,
            signal_date,
            signal_date,
            fields=(config.trade_price_field, "volume", "open_interest"),
        )
        exact_bar = bars.loc[
            bars["trading_date"].eq(signal_date)
            & bars["order_book_id"].eq(contract)
        ]
        details = adapter.get_instrument_details(contract)
        exact_detail = details.loc[details["order_book_id"].eq(contract)]
        parameters = adapter.get_trading_parameters(
            contract,
            target_date,
            target_date,
        )
        exact_parameters = parameters.loc[
            parameters["trading_date"].eq(target_date)
            & parameters["order_book_id"].eq(contract)
        ]
        if len(exact_bar) != 1:
            base["market_data_reason"] = "signal_date_trade_bar_unavailable"
        elif len(exact_detail) != 1:
            base["market_data_reason"] = "contract_multiplier_unavailable"
        elif len(exact_parameters) != 1:
            base["market_data_reason"] = "target_date_margin_unavailable"
        else:
            bar = exact_bar.iloc[0]
            detail = exact_detail.iloc[0]
            parameter = exact_parameters.iloc[0]
            base.update(
                {
                    "order_book_id": contract,
                    "trade_price": bar.get(config.trade_price_field),
                    "contract_multiplier": detail.get("contract_multiplier"),
                    "long_margin_ratio": parameter.get("long_margin_ratio"),
                    "short_margin_ratio": parameter.get("short_margin_ratio"),
                    "daily_volume": bar.get("volume"),
                    "open_interest": bar.get("open_interest"),
                }
            )
        rows.append(base)

    result = _normalize_market_data(
        pd.DataFrame(rows, columns=PORTFOLIO_MARKET_COLUMNS)
    )
    result.attrs.update(
        {
            "trade_contract_definition": "rqdata_rule0_rank1_dominant",
            "trade_contract_rule": config.trade_contract_rule,
            "trade_contract_rank": config.trade_contract_rank,
            "trade_price_information_date": "signal_date_close",
            "margin_information_date": "target_effective_date_pre_open",
            "contract_multiplier_source": "rqdatac.instruments",
            "capacity_fields_are_diagnostics_only": True,
        }
    )
    return result


def construct_target_positions(
    factor_table: pd.DataFrame,
    continuous_prices: pd.DataFrame,
    universe: pd.DataFrame,
    portfolio_market_data: pd.DataFrame,
    classifications: pd.DataFrame,
    config: PortfolioConfig,
) -> dict[str, object]:
    """Convert standard Phase 3 signals into integer real-contract targets."""

    _validate_config(config)
    factors = _normalize_factors(factor_table)
    requested_signal_dates = pd.DatetimeIndex(
        factors["trading_date"].dropna().unique()
    )
    eligible = _normalize_universe(universe)
    market = _normalize_market_data(portfolio_market_data)
    classification_version = classifications.attrs.get("version", "unversioned")
    classification = _normalize_classifications(classifications)

    unknown_factors = sorted(
        set(factors["factor_name"].dropna().astype(str))
        - set(config.strategy_weights)
    )
    if unknown_factors:
        raise ValueError(
            f"strategy_weights is missing factor names: {unknown_factors}"
        )

    factors = factors.merge(
        eligible.loc[eligible["eligible"], ["trading_date", "instrument"]],
        on=["trading_date", "instrument"],
        how="inner",
        validate="many_to_one",
    )
    volatility = compute_rolling_volatility(
        continuous_prices,
        lookback=config.volatility_lookback,
        minimum_observations=config.minimum_volatility_observations,
        annualization_factor=config.annualization_factor,
        volatility_floor=config.volatility_floor,
        price_field="close",
    )
    volatility = volatility.rename(columns={"trading_date": "signal_date"})
    contributions = factors.rename(columns={"trading_date": "signal_date"}).merge(
        volatility,
        on=["signal_date", "instrument"],
        how="left",
        validate="many_to_one",
    )
    contributions["strategy_weight"] = contributions["factor_name"].map(
        dict(config.strategy_weights)
    )
    # Phase 3 signal 在这里被直接消费，不做第二次 clipping/rank/z-score。
    contributions["weighted_signal_contribution"] = (
        contributions["signal"] * contributions["strategy_weight"]
    )
    contributions["inverse_vol_risk"] = (
        contributions["signal"] / contributions["vol_forecast"]
    )
    contributions["strategy_risk_contribution"] = (
        contributions["strategy_weight"]
        * contributions["inverse_vol_risk"]
    )
    contributions = contributions.loc[:, CONTRIBUTION_COLUMNS].sort_values(
        ["signal_date", "instrument", "factor_name"]
    ).reset_index(drop=True)

    keys = ["signal_date", "instrument"]
    grouped = contributions.groupby(keys, sort=True, dropna=False)
    # 缺失策略不重分其权重，避免数据缺失时悄悄放大其余 Alpha。
    diagnostics = grouped[
        ["weighted_signal_contribution", "strategy_risk_contribution"]
    ].sum(min_count=1)
    diagnostics = diagnostics.rename(
        columns={
            "weighted_signal_contribution": "aggregated_signal",
            "strategy_risk_contribution": "aggregated_risk",
        }
    )
    diagnostics["has_signal"] = grouped["signal"].apply(
        lambda values: bool(values.notna().any())
    )
    diagnostics = diagnostics.reset_index().merge(
        volatility.loc[
            :,
            [
                "signal_date",
                "instrument",
                "raw_volatility",
                "vol_forecast",
                "vol_floor_applied",
            ],
        ],
        on=keys,
        how="left",
        validate="one_to_one",
    )
    diagnostics = diagnostics.merge(
        market,
        on=keys,
        how="left",
        validate="one_to_one",
    ).merge(
        classification,
        on="instrument",
        how="left",
        validate="many_to_one",
    )
    if config.sector_gross_cap is not None:
        missing_sector = sorted(
            diagnostics.loc[
                diagnostics["sector"].isna(), "instrument"
            ].astype(str).unique()
        )
        if missing_sector:
            raise ValueError(
                "sector classification is required when sector_gross_cap is enabled: "
                f"{missing_sector}"
            )
    if config.chain_gross_cap is not None:
        missing_chain = sorted(
            diagnostics.loc[
                diagnostics["industrial_chain"].isna(), "instrument"
            ].astype(str).unique()
        )
        if missing_chain:
            raise ValueError(
                "industrial-chain classification is required when "
                f"chain_gross_cap is enabled: {missing_chain}"
            )
    diagnostics["market_data_reason"] = diagnostics[
        "market_data_reason"
    ].fillna("missing_portfolio_market_data")
    diagnostics["availability_reason"] = diagnostics.apply(
        lambda row: _availability_reason(row, config), axis=1
    )
    allocatable = diagnostics["availability_reason"].eq("available")

    diagnostics["pre_instrument_cap"] = diagnostics[
        "aggregated_risk"
    ].where(allocatable)
    if config.instrument_cap is None:
        diagnostics["post_instrument_cap"] = diagnostics["pre_instrument_cap"]
    else:
        diagnostics["post_instrument_cap"] = diagnostics[
            "pre_instrument_cap"
        ].clip(-config.instrument_cap, config.instrument_cap)

    _apply_group_gross_cap(
        diagnostics,
        input_column="post_instrument_cap",
        group_column="sector",
        cap=config.sector_gross_cap,
        prefix="sector",
    )
    _apply_group_gross_cap(
        diagnostics,
        input_column="post_sector_cap",
        group_column="industrial_chain",
        cap=config.chain_gross_cap,
        prefix="chain",
    )

    # v1 使用透明的 diagonal risk：忽略品种协方差，再按组合目标波动率整体缩放。
    diagonal_variance = (
        diagnostics["post_chain_cap"] * diagnostics["vol_forecast"]
    ).pow(2)
    risk_squared = diagonal_variance.groupby(
        diagnostics["signal_date"], sort=True
    ).transform("sum")
    diagnostics["estimated_portfolio_risk_pre"] = np.sqrt(risk_squared)
    diagnostics["portfolio_scale_factor"] = np.where(
        diagnostics["estimated_portfolio_risk_pre"].gt(0),
        config.portfolio_vol_target
        / diagnostics["estimated_portfolio_risk_pre"],
        1.0,
    )
    diagnostics["post_scale_exposure"] = (
        diagnostics["post_chain_cap"]
        * diagnostics["portfolio_scale_factor"]
    )
    diagnostics["estimated_portfolio_risk_post"] = (
        diagnostics["estimated_portfolio_risk_pre"]
        * diagnostics["portfolio_scale_factor"]
    )
    # 下面保持完整单位链：风险敞口 -> 名义资金 -> 合约名义价值 -> 整数手数。
    diagnostics["target_notional"] = (
        config.initial_capital * diagnostics["post_scale_exposure"]
    )
    diagnostics["contract_notional"] = (
        diagnostics["trade_price"] * diagnostics["contract_multiplier"]
    )
    diagnostics["pre_margin_quantity_float"] = (
        diagnostics["target_notional"] / diagnostics["contract_notional"]
    )
    diagnostics["margin_ratio"] = np.select(
        [
            diagnostics["target_notional"].gt(0),
            diagnostics["target_notional"].lt(0),
        ],
        [
            diagnostics["long_margin_ratio"],
            diagnostics["short_margin_ratio"],
        ],
        default=0.0,
    )
    diagnostics["estimated_margin_pre"] = (
        diagnostics["target_notional"].abs() * diagnostics["margin_ratio"]
    )
    diagnostics["margin_limit"] = (
        config.initial_capital * config.max_margin_fraction
    )
    total_margin = diagnostics["estimated_margin_pre"].groupby(
        diagnostics["signal_date"], sort=True
    ).transform("sum")
    diagnostics["margin_scale"] = np.where(
        total_margin.gt(diagnostics["margin_limit"]),
        diagnostics["margin_limit"] / total_margin,
        1.0,
    )
    diagnostics["margin_scale"] = diagnostics["margin_scale"].fillna(1.0)
    diagnostics["post_margin_quantity_float"] = (
        diagnostics["pre_margin_quantity_float"]
        * diagnostics["margin_scale"]
    )
    rounded = np.trunc(diagnostics["post_margin_quantity_float"])
    diagnostics["target_quantity"] = pd.array(rounded, dtype="Int64")
    diagnostics["estimated_margin_post"] = (
        diagnostics["target_quantity"].abs()
        * diagnostics["contract_notional"]
        * diagnostics["margin_ratio"]
    )
    diagnostics["margin_reason"] = np.where(
        ~allocatable,
        "not_allocatable",
        np.where(
            diagnostics["margin_scale"].lt(1.0),
            "scaled_to_margin_limit",
            "within_margin_limit",
        ),
    )
    diagnostics["quantity_to_volume"] = (
        diagnostics["target_quantity"].abs() / diagnostics["daily_volume"]
    ).where(diagnostics["daily_volume"].gt(0))
    diagnostics["quantity_to_open_interest"] = (
        diagnostics["target_quantity"].abs() / diagnostics["open_interest"]
    ).where(diagnostics["open_interest"].gt(0))
    diagnostics["portfolio_decision_date"] = diagnostics[
        "target_effective_date"
    ]
    diagnostics = diagnostics.loc[:, DIAGNOSTIC_COLUMNS].sort_values(
        ["signal_date", "instrument"]
    ).reset_index(drop=True)

    target_rows = diagnostics.loc[
        diagnostics["availability_reason"].eq("available")
        & diagnostics["target_quantity"].notna()
        & diagnostics["order_book_id"].notna(),
        ["target_effective_date", "order_book_id", "target_quantity"],
    ].rename(columns={"target_effective_date": "trading_date"})
    target_rows["target_quantity"] = target_rows["target_quantity"].astype("int64")
    target_rows["source_tag"] = config.source_tag
    targets = target_rows.loc[:, TARGET_POSITION_COLUMNS].sort_values(
        ["trading_date", "order_book_id"]
    ).reset_index(drop=True)
    if targets.duplicated(["trading_date", "order_book_id"]).any():
        raise DataValidationError(
            "Target positions contain duplicate date/contract rows"
        )

    # rebalance_dates 记录“完整快照存在”的日期，即使所有目标都 unavailable 而产生 0 行。
    rebalance_dates = pd.DatetimeIndex(
        market.loc[
            market["signal_date"].isin(requested_signal_dates),
            "target_effective_date",
        ].dropna().unique()
    ).normalize().sort_values()

    metadata = {
        "portfolio_version": "portfolio_risk_v1",
        "config": _config_metadata(config),
        "signal_handling": "consume_phase3_signal_directly_no_renormalization",
        "volatility_definition": (
            "rolling_std(price_t / price_t_minus_1 - 1) * sqrt(annualization_factor)"
        ),
        "instrument_risk_definition": "strategy_weight * signal / vol_forecast",
        "strategy_aggregation": "fixed_weighted_sum_without_missing_weight_renormalization",
        "risk_estimator": "diagonal",
        "portfolio_risk_definition": "sqrt(sum((weight_i * vol_i)^2))",
        "target_notional_definition": "initial_capital * post_scale_exposure",
        "target_quantity_definition": (
            "trunc_toward_zero(target_notional / (trade_price * contract_multiplier) * margin_scale)"
        ),
        "signal_information_date": "signal_date_close",
        "signal_available_at": "after_close_of_signal_date",
        "target_trading_date_definition": (
            "target_effective_date_earliest_execution_trading_date"
        ),
        "portfolio_decision_at": "pre_open_of_target_effective_date",
        "earliest_execution_at": "target_effective_date_trading_session",
        "rebalance_date_definition": (
            "complete_target_snapshot_effective_date_including_empty_snapshots"
        ),
        "rebalance_dates": [date.date().isoformat() for date in rebalance_dates],
        "margin_sanity_only": True,
        "formal_margin_accounting": False,
        "capacity_diagnostics_only": True,
        "capacity_changes_target_quantity": False,
        "rqoptimizer_used": False,
        "classification_version": classification_version,
        "input_fingerprints": {
            "factors": _frame_sha256(factors),
            "continuous_prices": _frame_sha256(continuous_prices),
            "universe": _frame_sha256(eligible),
            "portfolio_market_data": _frame_sha256(market),
            "classifications": _frame_sha256(classification),
        },
    }
    targets.attrs.update(
        {
            "trading_date_role": (
                "target_effective_date_earliest_execution_trading_date"
            ),
            "portfolio_decision_at": metadata["portfolio_decision_at"],
            "earliest_execution_at": metadata["earliest_execution_at"],
            "rebalance_dates": metadata["rebalance_dates"],
            "contains_orders": False,
            "contains_cash_pnl": False,
        }
    )
    diagnostics.attrs.update(
        {
            "margin_sanity_only": True,
            "capacity_diagnostics_only": True,
            "formal_accounting": False,
        }
    )
    return {
        "targets": targets,
        "rebalance_dates": rebalance_dates,
        "diagnostics": diagnostics,
        "contributions": contributions,
        "metadata": metadata,
    }


def _validate_config(config: PortfolioConfig) -> None:
    for name, value in (
        ("initial_capital", config.initial_capital),
        ("portfolio_vol_target", config.portfolio_vol_target),
        ("volatility_floor", config.volatility_floor),
        ("max_margin_fraction", config.max_margin_fraction),
    ):
        if not np.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be a positive finite number")
    if config.max_margin_fraction > 1:
        raise ValueError("max_margin_fraction cannot exceed 1")
    for name, value in (
        ("volatility_lookback", config.volatility_lookback),
        (
            "minimum_volatility_observations",
            config.minimum_volatility_observations,
        ),
        ("annualization_factor", config.annualization_factor),
        ("target_lag_sessions", config.target_lag_sessions),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    if (
        config.minimum_volatility_observations < 2
        or config.minimum_volatility_observations > config.volatility_lookback
    ):
        raise ValueError(
            "minimum_volatility_observations must be between 2 and volatility_lookback"
        )
    if config.volatility_method != "rolling_close_to_close_simple_return":
        raise ValueError("Phase 5 v1 supports only rolling close-to-close volatility")
    if config.risk_estimator != "diagonal":
        raise ValueError("Phase 5 v1 supports only the diagonal risk estimator")
    if config.trade_contract_rule != 0 or config.trade_contract_rank != 1:
        raise ValueError("Phase 5 v1 Trade Contract must use rule=0 and rank=1")
    if config.trade_price_field != "settlement":
        raise ValueError("Phase 5 v1 supports only settlement sizing prices")
    if config.rounding_rule != "toward_zero":
        raise ValueError("Phase 5 v1 supports only toward_zero rounding")
    if not re.fullmatch(r"[a-z0-9_]+", config.source_tag):
        raise ValueError("source_tag must use lowercase letters, digits, and '_'")
    if not config.strategy_weights:
        raise ValueError("strategy_weights cannot be empty")
    for factor_name, weight in config.strategy_weights.items():
        if not isinstance(factor_name, str) or not factor_name.strip():
            raise ValueError("strategy_weights keys must be non-empty strings")
        if not np.isfinite(weight) or weight < 0:
            raise ValueError("strategy weights must be non-negative and finite")
    if not any(weight > 0 for weight in config.strategy_weights.values()):
        raise ValueError("at least one strategy weight must be positive")
    for name, cap in (
        ("instrument_cap", config.instrument_cap),
        ("sector_gross_cap", config.sector_gross_cap),
        ("chain_gross_cap", config.chain_gross_cap),
    ):
        if cap is not None and (not np.isfinite(cap) or cap <= 0):
            raise ValueError(f"{name} must be None or a positive finite number")


def _normalize_factors(frame: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(set(FACTOR_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"factor_table is missing fields: {missing}")
    if frame.attrs.get("signal_is_position") is True:
        raise ValueError("Phase 3 signal cannot be marked as a position")
    if frame.attrs.get("signal_available_at") not in (
        None,
        "after_close_of_trading_date",
    ):
        raise ValueError("factor signal availability conflicts with Phase 3")
    if frame.attrs.get("earliest_trade_at") not in (
        None,
        "next_trading_session",
    ):
        raise ValueError("factor earliest trade time conflicts with Phase 3")
    factors = frame.loc[:, FACTOR_COLUMNS].copy()
    factors["trading_date"] = pd.to_datetime(
        factors["trading_date"], errors="raise"
    ).dt.normalize()
    factors["instrument"] = (
        factors["instrument"].astype("string").str.strip().str.upper()
    )
    factors["factor_name"] = (
        factors["factor_name"].astype("string").str.strip()
    )
    for column in ("raw_factor", "signal"):
        factors[column] = pd.to_numeric(factors[column], errors="coerce")
        if np.isinf(factors[column].dropna()).any():
            raise ValueError(f"{column} cannot contain infinity")
    if factors.duplicated(
        ["trading_date", "instrument", "factor_name"]
    ).any():
        raise ValueError("factor_table contains duplicate date/instrument/factor rows")
    return factors.sort_values(
        ["trading_date", "instrument", "factor_name"]
    ).reset_index(drop=True)


def _normalize_universe(frame: pd.DataFrame) -> pd.DataFrame:
    required = ("trading_date", "instrument", "eligible")
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"universe is missing fields: {missing}")
    result = frame.loc[:, required].copy()
    result["trading_date"] = pd.to_datetime(
        result["trading_date"], errors="raise"
    ).dt.normalize()
    result["instrument"] = (
        result["instrument"].astype("string").str.strip().str.upper()
    )
    result["eligible"] = result["eligible"].eq(True)
    if result.duplicated(["trading_date", "instrument"]).any():
        raise ValueError("universe contains duplicate date/instrument rows")
    return result.sort_values(["trading_date", "instrument"]).reset_index(drop=True)


def _normalize_market_data(frame: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(set(PORTFOLIO_MARKET_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"portfolio_market_data is missing fields: {missing}")
    result = frame.loc[:, PORTFOLIO_MARKET_COLUMNS].copy()
    for column in ("signal_date", "target_effective_date"):
        result[column] = pd.to_datetime(result[column], errors="coerce").dt.normalize()
    for column in ("instrument", "order_book_id"):
        result[column] = result[column].astype("string").str.strip().str.upper()
    result["price_field"] = result["price_field"].astype("string").str.strip().str.lower()
    result["market_data_reason"] = (
        result["market_data_reason"].astype("string").str.strip()
    )
    for column in (
        "trade_contract_rule",
        "trade_contract_rank",
        "trade_price",
        "contract_multiplier",
        "long_margin_ratio",
        "short_margin_ratio",
        "daily_volume",
        "open_interest",
    ):
        result[column] = pd.to_numeric(result[column], errors="coerce")
        if np.isinf(result[column].dropna()).any():
            raise ValueError(f"portfolio_market_data {column} cannot be infinite")
    if result.duplicated(["signal_date", "instrument"]).any():
        raise ValueError("portfolio_market_data contains duplicate date/instrument rows")
    return result.sort_values(["signal_date", "instrument"]).reset_index(drop=True)


def _normalize_classifications(frame: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(set(CLASSIFICATION_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"classifications is missing fields: {missing}")
    result = frame.loc[:, CLASSIFICATION_COLUMNS].copy()
    result["instrument"] = (
        result["instrument"].astype("string").str.strip().str.upper()
    )
    for column in ("sector", "industrial_chain"):
        result[column] = result[column].astype("string").str.strip()
        result[column] = result[column].replace("", pd.NA)
    if result["instrument"].eq("").any() or result["instrument"].isna().any():
        raise ValueError("classifications contains a missing instrument")
    if result.duplicated(["instrument"]).any():
        raise ValueError("classifications contains duplicate instruments")
    return result.sort_values("instrument").reset_index(drop=True)


def _availability_reason(row: pd.Series, config: PortfolioConfig) -> str:
    if not bool(row["has_signal"]):
        return "signal_unavailable"
    if pd.isna(row["vol_forecast"]) or row["vol_forecast"] <= 0:
        return "volatility_unavailable"
    market_reason = row.get("market_data_reason")
    if pd.isna(market_reason) or str(market_reason) != "available":
        return str(market_reason) if pd.notna(market_reason) else "market_data_unavailable"
    if pd.isna(row["target_effective_date"]) or row["target_effective_date"] <= row["signal_date"]:
        return "invalid_target_effective_date"
    if pd.isna(row["order_book_id"]) or not str(row["order_book_id"]).strip():
        return "dominant_contract_unavailable"
    if row["trade_contract_rule"] != config.trade_contract_rule:
        return "trade_contract_rule_mismatch"
    if row["trade_contract_rank"] != config.trade_contract_rank:
        return "trade_contract_rank_mismatch"
    if str(row["price_field"]) != config.trade_price_field:
        return "trade_price_field_mismatch"
    if pd.isna(row["trade_price"]) or row["trade_price"] <= 0:
        return "trade_price_unavailable"
    if pd.isna(row["contract_multiplier"]) or row["contract_multiplier"] <= 0:
        return "contract_multiplier_unavailable"
    if config.sector_gross_cap is not None and pd.isna(row["sector"]):
        return "sector_classification_unavailable"
    if config.chain_gross_cap is not None and pd.isna(row["industrial_chain"]):
        return "chain_classification_unavailable"
    risk = row["aggregated_risk"]
    if pd.isna(risk):
        return "risk_exposure_unavailable"
    if risk > 0 and (pd.isna(row["long_margin_ratio"]) or row["long_margin_ratio"] <= 0):
        return "long_margin_ratio_unavailable"
    if risk < 0 and (pd.isna(row["short_margin_ratio"]) or row["short_margin_ratio"] <= 0):
        return "short_margin_ratio_unavailable"
    return "available"


def _apply_group_gross_cap(
    frame: pd.DataFrame,
    *,
    input_column: str,
    group_column: str,
    cap: float | None,
    prefix: str,
) -> None:
    pre_column = f"pre_{prefix}_cap"
    post_column = f"post_{prefix}_cap"
    gross_pre_column = f"{prefix}_gross_pre_cap"
    scale_column = f"{prefix}_scale"
    gross_post_column = f"{prefix}_gross_post_cap"
    frame[pre_column] = frame[input_column]
    frame[gross_pre_column] = np.nan
    grouped_rows = frame[input_column].notna() & frame[group_column].notna()
    if grouped_rows.any():
        gross = frame.loc[grouped_rows].groupby(
            [frame.loc[grouped_rows, "signal_date"], frame.loc[grouped_rows, group_column]],
            sort=True,
        )[input_column].transform(lambda values: values.abs().sum())
        frame.loc[grouped_rows, gross_pre_column] = gross.to_numpy()
    frame[scale_column] = 1.0
    if cap is not None:
        frame.loc[grouped_rows, scale_column] = (
            cap / frame.loc[grouped_rows, gross_pre_column]
        ).clip(upper=1.0)
    frame[post_column] = frame[pre_column] * frame[scale_column]
    frame[gross_post_column] = (
        frame[gross_pre_column] * frame[scale_column]
    )


def _config_metadata(config: PortfolioConfig) -> dict[str, object]:
    return {
        "initial_capital": float(config.initial_capital),
        "portfolio_vol_target": float(config.portfolio_vol_target),
        "volatility_method": config.volatility_method,
        "volatility_lookback": config.volatility_lookback,
        "minimum_volatility_observations": config.minimum_volatility_observations,
        "annualization_factor": config.annualization_factor,
        "volatility_floor": float(config.volatility_floor),
        "strategy_weights": {
            name: float(weight)
            for name, weight in sorted(config.strategy_weights.items())
        },
        "instrument_cap": config.instrument_cap,
        "sector_gross_cap": config.sector_gross_cap,
        "chain_gross_cap": config.chain_gross_cap,
        "risk_estimator": config.risk_estimator,
        "max_margin_fraction": float(config.max_margin_fraction),
        "target_lag_sessions": config.target_lag_sessions,
        "trade_contract_rule": config.trade_contract_rule,
        "trade_contract_rank": config.trade_contract_rank,
        "trade_price_field": config.trade_price_field,
        "rounding_rule": config.rounding_rule,
        "source_tag": config.source_tag,
    }


def _frame_sha256(frame: pd.DataFrame) -> str:
    normalized = frame.copy()
    header = json.dumps(
        {
            "columns": list(normalized.columns),
            "dtypes": [str(dtype) for dtype in normalized.dtypes],
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    row_hashes = pd.util.hash_pandas_object(normalized, index=False).to_numpy()
    digest = hashlib.sha256(header)
    digest.update(row_hashes.tobytes())
    return digest.hexdigest()
