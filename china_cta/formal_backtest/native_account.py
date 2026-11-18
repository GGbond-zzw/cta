"""Native RQAlpha futures account that replays the four-factor book.

The research pipeline answers *what signal the book holds on date T*.  The
native account answers *what a 50m futures account actually owns after integer
lots, exchange margin, a previous-session volume cap, one tick of slippage and
the exchange's own commission*.  Signals are produced upstream; this module only
sizes them into contract-level target lots and replays them into RQAlpha on
T+1's open auction.
"""

from __future__ import annotations

import re

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Collection, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from china_cta.data.rqalpha_bundle import (
    load_future_info,
    load_instruments,
    load_trading_bars,
)

TARGET_COLUMNS: tuple[str, ...] = (
    "trading_date",
    "order_book_id",
    "product",
    "target_quantity",
    "exposure",
    "quantity_before_margin_scale",
    "margin_used",
)

TARGET_EXPOSURE_COLUMNS: tuple[str, ...] = (
    "trading_date",
    "order_book_id",
    "product",
    "capital_units",
    "price",
    "multiplier",
    "margin_rate",
    "source_tag",
)


@dataclass(frozen=True, slots=True)
class NativeAccountConfig:
    """Explicit settings of the native futures account."""

    start_date: str
    end_date: str
    bundle_path: str | Path
    output_dir: str | Path
    initial_capital: float = 50_000_000.0
    margin_budget: float = 0.50
    slippage_ticks: float = 1.0
    volume_percent: float = 0.25
    price_limit: bool = True
    inactive_limit: bool = True
    futures_commission_multiplier: float = 1.0
    margin_multiplier: float = 1.0
    futures_settlement_price_type: str = "close"
    log_level: str = "warning"
    strategy_name: str = "china_cta_native_4f_vol20"
    margin_basis: str = "live_equity"


def load_market(
    bundle_path: str | Path,
    products: Sequence[str] | None = None,
    cache_dir: str | Path | None = None,
) -> dict[str, pd.DataFrame]:
    """Return ``bars``, ``instruments`` and ``terms`` for the native account."""

    bundle = Path(bundle_path)
    products = list(products) if products is not None else None
    cache_root = Path(cache_dir) if cache_dir is not None else bundle.parent
    tag = "all" if products is None else f"{len(products)}"
    cache_root.mkdir(parents=True, exist_ok=True)
    bars_path = cache_root / f"native_bars_{tag}.parquet"
    instruments_path = cache_root / f"native_instruments_{tag}.parquet"

    instruments = load_instruments(bundle, products).rename(
        columns={"underlying_symbol": "product"}
    )
    cached_instruments = None
    if bars_path.exists() and instruments_path.exists():
        bars = pd.read_parquet(bars_path)
        cached_instruments = pd.read_parquet(instruments_path)
    if (
        cached_instruments is not None
        and len(cached_instruments) == len(instruments)
        and "contract_multiplier" in cached_instruments.columns
        and "trading_hours" in cached_instruments.columns
    ):
        instruments = cached_instruments
    else:
        bars = load_trading_bars(bundle, products)
        bars.to_parquet(bars_path, index=False)
        instruments.to_parquet(instruments_path, index=False)

    terms = load_future_info(bundle)
    if products is not None:
        terms = terms.loc[terms["product"].isin(products)].reset_index(drop=True)
    return {"bars": bars, "instruments": instruments, "terms": terms}


def combine_sleeves(
    sleeve_signals: pd.DataFrame,
    weights: Mapping[str, float],
    *,
    capital_share: float = 1.0,
) -> pd.DataFrame:
    """Turn per-sleeve signals into one signed capital exposure per product.

    A sleeve holds ``signal`` units of notional per instrument, spread evenly
    across the instruments it trades that day; the sleeve itself gets ``weight``
    of capital.  This mirrors the research engine's "mean of instrument returns"
    convention, which is what keeps the two layers comparable.
    """

    frame = sleeve_signals.loc[sleeve_signals["signal"].ne(0)].copy()
    if frame.empty:
        return pd.DataFrame(columns=["trading_date", "product", "exposure"])
    counts = (
        frame.groupby(["trading_date", "sleeve"], observed=True)["signal"]
        .size()
        .rename("sleeve_size")
        .reset_index()
    )
    frame = frame.merge(counts, on=["trading_date", "sleeve"], how="left")
    frame["weight"] = (
        frame["sleeve"].map(dict(weights)).fillna(0.0).astype(float)
        * capital_share
        * frame["signal"].astype(float)
        / frame["sleeve_size"].astype(float)
    )
    return (
        frame.groupby(["trading_date", "product"], observed=True)["weight"]
        .sum()
        .rename("exposure")
        .reset_index()
    )


def trading_days(bars: pd.DataFrame) -> np.ndarray:
    return np.sort(bars["trading_date"].unique())


def next_trading_day(dates: Iterable[object], calendar: np.ndarray) -> dict[pd.Timestamp, pd.Timestamp]:
    """Map each signal date to the session its orders are executed in."""

    mapping: dict[pd.Timestamp, pd.Timestamp] = {}
    for date in pd.to_datetime(sorted(set(dates))):
        index = int(np.searchsorted(calendar, np.datetime64(date), side="right"))
        if index >= len(calendar):
            continue
        mapping[pd.Timestamp(date)] = pd.Timestamp(calendar[index])
    return mapping


def build_target_quantities(
    exposure: pd.DataFrame,
    dominant: pd.DataFrame,
    market: Mapping[str, pd.DataFrame],
    leverage: pd.Series | None,
    config: NativeAccountConfig,
    *,
    source_tag: str = "four_factor_book",
) -> pd.DataFrame:
    """Size the exposures into integer lots under a margin budget."""

    bars = market["bars"]
    instruments = market["instruments"].set_index("order_book_id")
    terms = market["terms"].set_index("product")
    calendar = trading_days(bars)
    execution_dates = next_trading_day(exposure["trading_date"].unique(), calendar)

    settlement = (
        bars.loc[:, ["order_book_id", "trading_date", "settlement", "close"]]
        .assign(
            settlement=lambda frame: frame["settlement"].where(
                frame["settlement"].gt(0), frame["close"]
            )
        )
        .set_index(["trading_date", "order_book_id"])["settlement"]
    )
    contract_of = dominant.set_index(["trading_date", "product"])["dominant_order_book_id"]

    rows: list[dict[str, Any]] = []
    for date, group in exposure.groupby("trading_date", observed=True):
        stamp = pd.Timestamp(date)
        execution = execution_dates.get(stamp)
        if execution is None:
            continue
        lev = 1.0
        if leverage is not None and len(leverage):
            value = leverage.get(stamp)
            if value is not None and math.isfinite(float(value)):
                lev = float(value)
        sized: list[dict[str, Any]] = []
        for record in group.itertuples(index=False):
            product = str(record.product)
            exposure_value = float(record.exposure)
            if exposure_value == 0.0:
                continue
            try:
                contract = str(contract_of.loc[(stamp, product)])
            except KeyError:
                continue
            try:
                price = float(settlement.loc[(stamp, contract)])
            except KeyError:
                continue
            if not math.isfinite(price) or price <= 0:
                continue
            if contract not in instruments.index:
                continue
            multiplier = float(instruments.at[contract, "contract_multiplier"])
            if not math.isfinite(multiplier) or multiplier <= 0:
                multiplier = 1.0
            margin_rate = 0.10
            if product in terms.index:
                candidate = float(terms.at[product, "margin_rate"])
                if math.isfinite(candidate) and candidate > 0:
                    margin_rate = candidate
            notional = config.initial_capital * lev * exposure_value
            lots = float(math.trunc(notional / (price * multiplier)))
            sized.append(
                {
                    "product": product,
                    "order_book_id": contract,
                    "exposure": exposure_value,
                    "quantity_before_margin_scale": int(lots),
                    "price": price,
                    "multiplier": multiplier,
                    "margin_rate": margin_rate,
                    "margin": abs(lots) * price * multiplier * margin_rate,
                }
            )
        if not sized:
            continue
        total_margin = sum(item["margin"] for item in sized)
        budget = config.margin_budget * config.initial_capital
        scale = 1.0 if total_margin <= budget or total_margin <= 0 else budget / total_margin
        for item in sized:
            quantity = int(math.trunc(item["quantity_before_margin_scale"] * scale))
            if quantity == 0:
                # A zero target is only useful for closing an existing position,
                # which the replay does for every contract that drops out of the
                # snapshot.  Sending it explicitly would just log a rejection.
                continue
            rows.append(
                {
                    "trading_date": execution,
                    "order_book_id": item["order_book_id"],
                    "product": item["product"],
                    "target_quantity": quantity,
                    "exposure": item["exposure"],
                    "quantity_before_margin_scale": item["quantity_before_margin_scale"],
                    "margin_used": item["margin"] * scale,
                    "source_tag": source_tag,
                }
            )
    if not rows:
        return pd.DataFrame(columns=list(TARGET_COLUMNS) + ["source_tag"])
    frame = pd.DataFrame(rows)
    return frame.loc[:, list(TARGET_COLUMNS) + ["source_tag"]].sort_values(
        ["trading_date", "order_book_id"]
    ).reset_index(drop=True)


def build_target_exposures(
    exposure: pd.DataFrame,
    dominant: pd.DataFrame,
    market: Mapping[str, pd.DataFrame],
    leverage: pd.Series | None,
    config: NativeAccountConfig,
    *,
    source_tag: str = "four_factor_book",
) -> pd.DataFrame:
    """Resolve per-product exposure into per-contract notional targets.

    Nothing is truncated here.  Quantities depend on the account equity of the
    session, so they are produced inside the replay by :func:`plan_day_targets`.
    ``capital_units`` is the signed notional as a fraction of that equity.
    """

    bars = market["bars"]
    instruments = market["instruments"].set_index("order_book_id")
    terms = market["terms"].set_index("product")
    calendar = trading_days(bars)
    execution_dates = next_trading_day(exposure["trading_date"].unique(), calendar)

    settlement = (
        bars.loc[:, ["order_book_id", "trading_date", "settlement", "close"]]
        .assign(
            settlement=lambda frame: frame["settlement"].where(
                frame["settlement"].gt(0), frame["close"]
            )
        )
        .set_index(["trading_date", "order_book_id"])["settlement"]
    )
    contract_of = dominant.set_index(["trading_date", "product"])["dominant_order_book_id"]

    rows: list[dict[str, Any]] = []
    for date, group in exposure.groupby("trading_date", observed=True):
        stamp = pd.Timestamp(date)
        execution = execution_dates.get(stamp)
        if execution is None:
            continue
        lev = 1.0
        if leverage is not None and len(leverage):
            value = leverage.get(stamp)
            if value is not None and math.isfinite(float(value)):
                lev = float(value)
        for record in group.itertuples(index=False):
            product = str(record.product)
            exposure_value = float(record.exposure)
            if exposure_value == 0.0:
                continue
            try:
                contract = str(contract_of.loc[(stamp, product)])
            except KeyError:
                continue
            try:
                price = float(settlement.loc[(stamp, contract)])
            except KeyError:
                continue
            if not math.isfinite(price) or price <= 0:
                continue
            if contract not in instruments.index:
                continue
            multiplier = float(instruments.at[contract, "contract_multiplier"])
            if not math.isfinite(multiplier) or multiplier <= 0:
                multiplier = 1.0
            margin_rate = 0.10
            if product in terms.index:
                candidate = float(terms.at[product, "margin_rate"])
                if math.isfinite(candidate) and candidate > 0:
                    margin_rate = candidate
            rows.append(
                {
                    "trading_date": execution,
                    "order_book_id": contract,
                    "product": product,
                    "capital_units": lev * exposure_value,
                    "price": price,
                    "multiplier": multiplier,
                    "margin_rate": margin_rate,
                    "source_tag": source_tag,
                }
            )
    if not rows:
        return pd.DataFrame(columns=list(TARGET_EXPOSURE_COLUMNS))
    return pd.DataFrame(rows).loc[:, list(TARGET_EXPOSURE_COLUMNS)].sort_values(
        ["trading_date", "order_book_id"]
    ).reset_index(drop=True)


def plan_day_targets(
    rows: pd.DataFrame, equity: float, config: NativeAccountConfig
) -> pd.DataFrame:
    """Integer lots for one session, sized off that session's account equity."""

    empty = pd.DataFrame(columns=list(TARGET_COLUMNS) + ["source_tag"])
    if rows is None or len(rows) == 0 or equity <= 0:
        return empty
    budget = float(config.margin_budget) * float(equity)
    sized: list[tuple[Any, float, float]] = []
    for record in rows.itertuples(index=False):
        notional = float(equity) * float(record.capital_units)
        price = float(record.price)
        multiplier = float(record.multiplier)
        lots = float(math.trunc(notional / (price * multiplier)))
        if lots == 0:
            continue
        margin = abs(lots) * price * multiplier * float(record.margin_rate)
        sized.append((record, lots, margin))
    if not sized:
        return empty
    total_margin = sum(item[2] for item in sized)
    scale = 1.0 if total_margin <= budget or total_margin <= 0 else budget / total_margin
    records: list[dict[str, Any]] = []
    for record, lots, margin in sized:
        quantity = int(math.trunc(lots * scale))
        if quantity == 0:
            continue
        records.append(
            {
                "trading_date": record.trading_date,
                "order_book_id": record.order_book_id,
                "product": record.product,
                "target_quantity": quantity,
                "exposure": float(record.capital_units),
                "quantity_before_margin_scale": int(lots),
                "margin_used": float(margin * scale),
                "source_tag": str(record.source_tag),
            }
        )
    return pd.DataFrame(records, columns=list(TARGET_COLUMNS) + ["source_tag"])


EXECUTION_TIME_COLUMN: str = "execution_time"
NIGHT_SESSION_OPEN: str = "21:00:00"
DAY_SESSION_OPEN: str = "09:00:00"


def product_of(order_book_id: str) -> str:
    """Return the product prefix of a futures contract (``AG1606`` -> ``AG``)."""

    match = re.match(r"^([A-Za-z]+)", str(order_book_id))
    return match.group(1).upper() if match else str(order_book_id).upper()


def night_products(instruments: pd.DataFrame) -> set[str]:
    """Products whose first trading slot is the 21:00 night session."""

    if instruments is None or instruments.empty:
        return set()
    frame = instruments.copy()
    if "product" not in frame.columns and "underlying_symbol" in frame.columns:
        frame = frame.rename(columns={"underlying_symbol": "product"})
    hours = frame.get("trading_hours")
    if hours is None:
        return set()
    first_slot = hours.astype(str).str.split(",").str[0].str.strip()
    frame = frame.assign(_night=first_slot.str.startswith("21:"))
    return set(frame.loc[frame["_night"], "product"].astype(str).unique())


def annotate_execution_time(
    trades: Any,
    calendar: Iterable[Any],
    night: Collection[str] | None = None,
) -> Any:
    """Stamp each fill with the wall-clock instant it effectively happened.

    RQAlpha labels a daily-bar fill with ``00:00`` of the trading date.  A night-session
    contract actually fills at the 21:00 open of the previous session, so that label hides
    the fact that the fill happened the evening the signal was generated.
    """

    if trades is None:
        return trades
    frame = trades.copy() if isinstance(trades, pd.DataFrame) else pd.DataFrame(trades)
    if frame.empty:
        return frame
    sessions = pd.DatetimeIndex(sorted({pd.Timestamp(value).normalize() for value in calendar}))
    if sessions.empty:
        return frame
    position = {date: index for index, date in enumerate(sessions)}
    column = "trading_datetime" if "trading_datetime" in frame.columns else "datetime"
    trading_date = pd.to_datetime(frame[column]).dt.normalize()
    previous = trading_date.map(
        lambda date: sessions[position[date] - 1] if position.get(date, 0) > 0 else date
    )
    night_contracts = {
        str(value).upper() for value in (night or set())
    }
    is_night = frame["order_book_id"].astype(str).map(lambda value: product_of(value) in night_contracts)
    fill_date = previous.where(is_night, trading_date)
    offset = pd.to_timedelta(is_night.map({True: NIGHT_SESSION_OPEN, False: DAY_SESSION_OPEN}))
    frame["product"] = frame["order_book_id"].astype(str).map(product_of)
    frame["night_session"] = is_night.to_numpy()
    frame[EXECUTION_TIME_COLUMN] = (fill_date + offset).dt.strftime("%Y-%m-%d %H:%M:%S")
    return frame


def run_native_account_dynamic(
    exposures: pd.DataFrame,
    config: NativeAccountConfig,
    *,
    tick_sizes: Mapping[str, float] | None = None,
    night_products: Collection[str] | None = None,
    session_calendar: Iterable[Any] | None = None,
) -> dict[str, Any]:
    """Replay capital-unit exposures, re-sizing every session off live equity."""

    from rqalpha import run_func
    from rqalpha.apis import order_to, update_universe

    schedule = {
        pd.Timestamp(date): group.sort_values("order_book_id")
        for date, group in exposures.groupby("trading_date", observed=True)
    }
    contract_ids = sorted(exposures["order_book_id"].unique().tolist())
    processed: set[pd.Timestamp] = set()
    snapshots: list[dict[str, Any]] = []
    filled: list[pd.DataFrame] = []
    sizing: list[dict[str, Any]] = []

    tick_map = {str(key): float(value) for key, value in (tick_sizes or {}).items()}

    def init(context: Any) -> None:
        _install_opening_slippage(config.slippage_ticks, tick_map)
        if contract_ids:
            update_universe(contract_ids)
        context._native_schedule = schedule
        context._native_processed = processed
        context._native_filled = filled
        context._native_sizing = sizing

    def open_auction(context: Any, bar_dict: Any) -> None:
        del bar_dict
        raw = getattr(context, "trading_dt", None)
        today = pd.Timestamp(raw if raw is not None else context.now).normalize()
        if today not in schedule or today in processed:
            return
        equity = float(context.portfolio.total_value)
        planned = plan_day_targets(schedule[today], equity, config)
        wanted = {
            str(record.order_book_id): int(record.target_quantity)
            for record in planned.itertuples(index=False)
        }
        sizing.append({"trading_date": today, "equity": equity, "planned_contracts": len(wanted)})
        held = {
            position.order_book_id
            for position in context.portfolio.get_positions()
            if position.quantity != 0
        }
        for contract in sorted(held - set(wanted)):
            order_to(contract, 0)
        for contract, quantity in wanted.items():
            order_to(contract, quantity)
        if not planned.empty:
            filled.append(planned)
        processed.add(today)

    def handle_bar(context: Any, bar_dict: Any) -> None:
        del bar_dict
        raw = getattr(context, "trading_dt", None)
        today = pd.Timestamp(raw if raw is not None else context.now).normalize()
        for position in context.portfolio.get_positions():
            if position.quantity == 0:
                continue
            direction = str(getattr(position, "direction", "LONG")).upper()
            sign = -1 if "SHORT" in direction else 1
            snapshots.append(
                {
                    "trading_date": today,
                    "order_book_id": str(position.order_book_id),
                    "quantity": sign * int(position.quantity),
                }
            )

    rqalpha_config = build_rqalpha_config(config)
    result = run_func(
        config=rqalpha_config, init=init, open_auction=open_auction, handle_bar=handle_bar
    )

    targets = (
        pd.concat(filled, ignore_index=True)
        if filled
        else pd.DataFrame(columns=list(TARGET_COLUMNS) + ["source_tag"])
    )
    unprocessed = sorted(set(schedule) - processed)
    analyser = result.get("sys_analyser", {})
    return {
        "portfolio": analyser.get("portfolio"),
        "trades": annotate_execution_time(
            analyser.get("trades"), session_calendar or schedule, night_products
        ),
        "summary": analyser.get("summary", {}),
        "unprocessed_dates": [date.date().isoformat() for date in unprocessed],
        "rqalpha_config": rqalpha_config,
        "positions": pd.DataFrame(snapshots, columns=list(POSITION_COLUMNS)),
        "targets": targets,
        "sizing": pd.DataFrame(sizing),
    }


def _install_opening_slippage(ticks: float, tick_sizes: dict[str, float]) -> None:
    """Make the open-auction fill pay ``ticks`` ticks; rqalpha does not do this itself."""

    if ticks <= 0:
        return

    from rqalpha.const import SIDE
    from rqalpha.mod.rqalpha_mod_sys_simulation.matcher.bar_matcher import DefaultBarMatcher

    if getattr(DefaultBarMatcher, "_china_cta_slippage_ticks", None) == ticks:
        return

    original = DefaultBarMatcher._open_auction_deal_price_decider

    def decider(self: Any, order_book_id: str, side: Any) -> float:
        price = float(original(self, order_book_id, side) or 0.0)
        if price <= 0:
            return price
        tick_size = float(tick_sizes.get(str(order_book_id), 0.0) or 0.0)
        if tick_size <= 0:
            return price
        offset = tick_size * float(ticks)
        return price + offset if side == SIDE.BUY else price - offset

    DefaultBarMatcher._open_auction_deal_price_decider = decider
    DefaultBarMatcher._china_cta_slippage_ticks = ticks


def run_native_account(
    targets: pd.DataFrame,
    config: NativeAccountConfig,
    *,
    tick_sizes: Mapping[str, float] | None = None,
    night_products: Collection[str] | None = None,
    session_calendar: Iterable[Any] | None = None,
) -> dict[str, Any]:
    """Replay ``targets`` into an RQAlpha futures account and return its output."""

    from rqalpha import run_func
    from rqalpha.apis import order_to, update_universe

    schedule = {
        pd.Timestamp(date): group.sort_values("order_book_id")
        for date, group in targets.groupby("trading_date", observed=True)
    }
    contract_ids = sorted(targets["order_book_id"].unique().tolist())
    processed: set[pd.Timestamp] = set()

    snapshots: list[dict[str, Any]] = []

    tick_map = {str(key): float(value) for key, value in (tick_sizes or {}).items()}

    def init(context: Any) -> None:
        _install_opening_slippage(config.slippage_ticks, tick_map)
        if contract_ids:
            update_universe(contract_ids)
        context._native_schedule = schedule
        context._native_processed = processed
        context._native_snapshots = snapshots

    def open_auction(context: Any, bar_dict: Any) -> None:
        del bar_dict
        raw = getattr(context, "trading_dt", None)
        today = pd.Timestamp(raw if raw is not None else context.now).normalize()
        if today not in schedule or today in processed:
            return
        held = {
            position.order_book_id
            for position in context.portfolio.get_positions()
            if position.quantity != 0
        }
        group = schedule[today]
        wanted = {
            str(record.order_book_id): int(record.target_quantity)
            for record in group.itertuples(index=False)
        }
        for contract in sorted(held - set(wanted)):
            order_to(contract, 0)
        for contract, quantity in wanted.items():
            order_to(contract, quantity)
        processed.add(today)

    def handle_bar(context: Any, bar_dict: Any) -> None:
        del bar_dict
        raw = getattr(context, "trading_dt", None)
        today = pd.Timestamp(raw if raw is not None else context.now).normalize()
        for position in context.portfolio.get_positions():
            if position.quantity == 0:
                continue
            direction = str(getattr(position, "direction", "LONG")).upper()
            sign = -1 if "SHORT" in direction else 1
            snapshots.append(
                {
                    "trading_date": today,
                    "order_book_id": str(position.order_book_id),
                    "quantity": sign * int(position.quantity),
                }
            )

    rqalpha_config = build_rqalpha_config(config)
    result = run_func(
        config=rqalpha_config, init=init, open_auction=open_auction, handle_bar=handle_bar
    )

    unprocessed = sorted(set(schedule) - processed)
    analyser = result.get("sys_analyser", {})
    return {
        "portfolio": analyser.get("portfolio"),
        "trades": annotate_execution_time(
            analyser.get("trades"), session_calendar or schedule, night_products
        ),
        "summary": analyser.get("summary", {}),
        "unprocessed_dates": [date.date().isoformat() for date in unprocessed],
        "rqalpha_config": rqalpha_config,
        "positions": pd.DataFrame(snapshots, columns=list(POSITION_COLUMNS)),
    }


def build_rqalpha_config(config: NativeAccountConfig) -> dict[str, Any]:
    return {
        "base": {
            "start_date": config.start_date,
            "end_date": config.end_date,
            "frequency": "1d",
            "data_bundle_path": str(config.bundle_path),
            "accounts": {"future": float(config.initial_capital)},
            "capital_gain_tax_rate": 0.0,
            "margin_multiplier": float(config.margin_multiplier),
            "strategy_name": config.strategy_name,
            "run_type": "b",
        },
        "mod": {
            "sys_analyser": {"enabled": True, "plot": False},
            "sys_progress": {"enabled": False},
            "sys_transaction_cost": {
                "futures_commission_multiplier": float(config.futures_commission_multiplier),
            },
            "sys_simulation": {
                "enabled": True,
                "matching_type": "current_bar",
                "slippage_model": "TickSizeSlippage",
                "slippage": float(config.slippage_ticks),
                "volume_limit": True,
                "volume_percent": float(config.volume_percent),
                "price_limit": bool(config.price_limit),
                "inactive_limit": bool(config.inactive_limit),
                "futures_settlement_price_type": config.futures_settlement_price_type,
            },
        },
        "extra": {"log_level": config.log_level},
    }


def daily_equity(result: Mapping[str, Any]) -> pd.Series:
    portfolio = result.get("portfolio")
    if portfolio is None:
        raise RuntimeError("RQAlpha returned no portfolio series")
    frame = pd.DataFrame(portfolio)
    if "total_value" not in frame.columns:
        raise RuntimeError(f"portfolio columns: {list(frame.columns)}")
    frame.index = pd.to_datetime(frame.index)
    return frame["total_value"].astype(float).sort_index()


def performance_metrics(equity: pd.Series, *, annualization: int = 252) -> dict[str, float]:
    returns = equity.pct_change().dropna()
    if returns.empty:
        return {}
    periods = len(returns)
    total = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    deviation = float(returns.std(ddof=1))
    volatility = float(deviation * math.sqrt(annualization))
    sharpe = float(returns.mean() / deviation * math.sqrt(annualization)) if deviation > 0 else 0.0
    drawdown = equity / equity.cummax() - 1.0
    return {
        "periods": float(periods),
        "total_return": total,
        "annualized_return": float((1.0 + total) ** (annualization / periods) - 1.0),
        "annualized_volatility": volatility,
        "sharpe": sharpe,
        "max_drawdown": float(drawdown.min()),
    }


def write_outputs(
    result: Mapping[str, Any],
    config: NativeAccountConfig,
    *,
    targets: pd.DataFrame,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Path]:
    """Persist equity, trades, targets and a config snapshot."""

    output = Path(config.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    equity = daily_equity(result)
    equity.rename("total_value").to_frame().to_csv(
        output / "daily_equity.csv", float_format="%.17g"
    )
    metrics = performance_metrics(equity)
    pd.Series(metrics, name="native").to_csv(output / "overall.csv", float_format="%.17g")
    trades = result.get("trades")
    if trades is not None:
        frame = pd.DataFrame(trades)
        if not frame.empty:
            frame.to_csv(output / "trades.csv", index=False, float_format="%.17g")
    targets.to_csv(output / "target_positions.csv", index=False, float_format="%.17g")
    payload = {
        "config": {
            key: str(value) if isinstance(value, Path) else value
            for key, value in asdict(config).items()
        },
        "performance": metrics,
        "unprocessed_dates": result.get("unprocessed_dates", []),
        "rqalpha_config": result.get("rqalpha_config", {}),
    }
    if extra:
        payload.update(dict(extra))
    (output / "config.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return {"output": output, "equity": output / "daily_equity.csv"}


POSITION_COLUMNS: Final[tuple[str, ...]] = ("trading_date", "order_book_id", "quantity")

SEGMENTS: Final[tuple[tuple[str, str, str], ...]] = (
    ("train_2016_2021", "2016-01-04", "2021-12-31"),
    ("validation_2022_2024", "2022-01-01", "2024-12-31"),
    ("test_2025_2026", "2025-01-01", "2026-12-31"),
)


def segment_metrics(equity: pd.Series, *, annualization: int = 252) -> pd.DataFrame:
    """Sharpe and friends for the three research segments plus the full sample."""

    equity = equity.dropna().sort_index()
    rows: list[dict[str, Any]] = []
    spans = [*SEGMENTS, ("overall", str(equity.index[0].date()), str(equity.index[-1].date()))]
    for name, start, end in spans:
        window = equity.loc[
            (equity.index >= pd.Timestamp(start)) & (equity.index <= pd.Timestamp(end))
        ]
        record: dict[str, Any] = {
            "segment": name,
            "start": str(window.index[0].date()) if len(window) else None,
            "end": str(window.index[-1].date()) if len(window) else None,
            "days": int(max(len(window) - 1, 0)),
        }
        if len(window) > 2:
            record.update(performance_metrics(window, annualization=annualization))
        rows.append(record)
    return pd.DataFrame(rows)


def attribute_pnl(
    positions: pd.DataFrame,
    trades: pd.DataFrame | None,
    market: Mapping[str, Any],
) -> pd.DataFrame:
    """Per day / contract P&L decomposition of the native futures account.

    ``quantity_prev * multiplier * (settlement_t - settlement_{t-1})``
    + ``quantity_delta * multiplier * (settlement_t - open_t)``
    - commission - one-tick slippage on the traded quantity.
    """

    bars = market["bars"].loc[
        :, ["order_book_id", "trading_date", "open", "close"]
    ].copy()
    bars = bars.sort_values(["order_book_id", "trading_date"])
    bars["prev_close"] = bars.groupby("order_book_id")["close"].shift(1)

    instruments = market["instruments"]
    terms = market["terms"].set_index("product")
    contract_ids = sorted(set(positions["order_book_id"].astype(str)))
    product_of = pd.Series(
        {contract: re.match(r"^([A-Za-z]+)", contract).group(1).upper() for contract in contract_ids}
    )
    if "contract_multiplier" in instruments.columns:
        multiplier = instruments.set_index("order_book_id")["contract_multiplier"]
    else:
        multiplier = product_of.map(terms["contract_multiplier"])
    tick_size = terms["tick_size"].astype(float)

    if positions is None or positions.empty:
        return pd.DataFrame()

    pivoted = positions.pivot_table(
        index="trading_date", columns="order_book_id", values="quantity", aggfunc="sum"
    ).fillna(0.0).sort_index()
    previous = pivoted.shift(1).fillna(0.0)
    delta = pivoted - previous

    panel = pd.concat(
        [previous.stack().rename("quantity_prev"), delta.stack().rename("quantity_delta")],
        axis=1,
    ).reset_index()
    panel.columns = ["trading_date", "order_book_id", "quantity_prev", "quantity_delta"]
    panel["order_book_id"] = panel["order_book_id"].astype(str)
    panel = panel.merge(bars, on=["order_book_id", "trading_date"], how="left")
    panel["product"] = panel["order_book_id"].map(product_of)
    panel["multiplier"] = panel["order_book_id"].map(multiplier).astype(float)
    panel["tick"] = panel["product"].map(tick_size).fillna(0.0)
    panel["pnl_carry"] = panel["quantity_prev"] * panel["multiplier"] * (
        panel["close"] - panel["prev_close"]
    )
    # fill price = open +/- one tick, so the trade leg carries its own slippage
    panel["pnl_trade"] = panel["quantity_delta"] * panel["multiplier"] * (
        panel["close"] - panel["open"]
    ) - panel["quantity_delta"].abs() * panel["multiplier"] * panel["tick"]

    if trades is not None and len(trades):
        trade_frame = pd.DataFrame(trades).copy()
        trade_frame["trading_date"] = pd.to_datetime(trade_frame["datetime"]).dt.normalize()
        trade_frame["order_book_id"] = trade_frame["order_book_id"].astype(str)
        trade_frame["commission"] = pd.to_numeric(
            trade_frame["commission"], errors="coerce"
        ).fillna(0.0)
        trade_frame["traded"] = (
            pd.to_numeric(trade_frame["last_quantity"], errors="coerce").fillna(0.0).abs()
        )
        grouped = (
            trade_frame.groupby(["trading_date", "order_book_id"], observed=True)
            .agg(commission=("commission", "sum"), traded=("traded", "sum"))
            .reset_index()
        )
        panel = panel.merge(
            grouped.loc[:, ["trading_date", "order_book_id", "commission"]],
            on=["trading_date", "order_book_id"],
            how="left",
        )
    else:
        panel["commission"] = 0.0
    panel["commission"] = panel["commission"].fillna(0.0)
    panel["slippage"] = panel["quantity_delta"].abs() * panel["multiplier"] * panel["tick"]
    panel["pnl_gross"] = panel["pnl_carry"].fillna(0.0) + panel["pnl_trade"].fillna(0.0) + panel["slippage"]
    panel["pnl_net"] = panel["pnl_gross"] - panel["commission"] - panel["slippage"]
    return panel.loc[
        :,
        [
            "trading_date",
            "order_book_id",
            "product",
            "quantity_prev",
            "quantity_delta",
            "pnl_carry",
            "pnl_trade",
            "pnl_gross",
            "commission",
            "slippage",
            "pnl_net",
        ],
    ]


def write_attribution(
    panel: pd.DataFrame,
    equity: pd.Series,
    capital: float,
    output: str | Path,
    *,
    label: str,
) -> dict[str, Any]:
    """Write segment / year / instrument tables and reconcile them with the equity."""

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    frame = panel.copy()
    if len(frame):
        frame["year"] = pd.to_datetime(frame["trading_date"]).dt.year
        by_year = (
            frame.groupby("year", observed=True)
            .agg(
                gross_pnl=("pnl_gross", "sum"),
                commission=("commission", "sum"),
                slippage=("slippage", "sum"),
                net_pnl=("pnl_net", "sum"),
                contracts=("order_book_id", "nunique"),
                days=("trading_date", "nunique"),
            )
            .reset_index()
        )
        by_instrument = (
            frame.groupby("product", observed=True)
            .agg(
                gross_pnl=("pnl_gross", "sum"),
                commission=("commission", "sum"),
                slippage=("slippage", "sum"),
                net_pnl=("pnl_net", "sum"),
                days=("trading_date", "nunique"),
            )
            .reset_index()
            .sort_values("net_pnl", ascending=False)
        )
        for table in (by_year, by_instrument):
            for column in ("gross_pnl", "commission", "slippage", "net_pnl"):
                table[f"{column}_pct_of_capital"] = table[column] / capital
    else:
        by_year = pd.DataFrame()
        by_instrument = pd.DataFrame()
    by_year.to_csv(output / "by_year.csv", index=False, float_format="%.17g")
    by_instrument.to_csv(output / "by_instrument.csv", index=False, float_format="%.17g")

    segments = segment_metrics(equity)
    segments.to_csv(output / "segments.csv", index=False, float_format="%.17g")

    equity_change = float(equity.iloc[-1] - equity.iloc[0])
    attributed = float(frame["pnl_net"].sum()) if len(frame) else 0.0
    reconciliation = {
        "label": label,
        "equity_change": equity_change,
        "attributed_net_pnl": attributed,
        "residual": equity_change - attributed,
        "residual_pct_of_capital": (equity_change - attributed) / capital,
        "gross_pnl": float(frame["pnl_gross"].sum()) if len(frame) else 0.0,
        "commission": float(frame["commission"].sum()) if len(frame) else 0.0,
        "slippage": float(frame["slippage"].sum()) if len(frame) else 0.0,
        "commission_pct_of_capital": float(frame["commission"].sum()) / capital if len(frame) else 0.0,
        "slippage_pct_of_capital": float(frame["slippage"].sum()) / capital if len(frame) else 0.0,
    }
    pd.Series(reconciliation).to_csv(output / "attribution_reconciliation.csv", float_format="%.17g")
    return {"segments": segments, "by_year": by_year, "by_instrument": by_instrument, "reconciliation": reconciliation}
