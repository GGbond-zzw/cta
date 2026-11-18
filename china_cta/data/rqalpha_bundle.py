"""Read the local RQAlpha futures bundle into a contract-level price frame.

The bundle is the only local source of futures bars outside the cached RQData
research inputs.  ``instruments.pk`` holds the static contract metadata and
``futures.h5`` holds one structured dataset per contract::

    datetime, open, close, high, low, prev_close, limit_up, limit_down,
    volume, total_turnover, settlement, prev_settlement, open_interest

``open`` is the first print of the trading day, which for night-session products
is the previous evening's 21:00 open -- the same convention RQData uses for
daily futures bars.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import h5py
import numpy as np
import pandas as pd


BAR_COLUMNS: tuple[str, ...] = (
    "order_book_id",
    "trading_date",
    "open",
    "high",
    "low",
    "close",
    "prev_close",
    "volume",
    "open_interest",
)


def load_instruments(bundle_dir: str | Path, products: list[str] | tuple[str, ...] | None = None) -> pd.DataFrame:
    """Return the ``Future`` instruments of the bundle, optionally pooled by product."""

    path = Path(bundle_dir)
    with open(path / "instruments.pk", "rb") as handle:
        rows = pickle.load(handle)
    frame = pd.DataFrame([row for row in rows if isinstance(row, dict)])
    frame = frame.loc[frame["type"].eq("Future")].copy()
    if "trading_hours" not in frame.columns:
        frame["trading_hours"] = None
    if products is not None:
        frame = frame.loc[frame["underlying_symbol"].isin(list(products))]
    frame = frame.loc[
        :,
        [
            "order_book_id",
            "underlying_symbol",
            "contract_multiplier",
            "trading_hours",
            "maturity_date",
            "listed_date",
            "de_listed_date",
        ],
    ]
    for column in ("maturity_date", "listed_date", "de_listed_date"):
        frame[column] = pd.to_datetime(frame[column], errors="coerce")
    return frame.reset_index(drop=True)


def load_bars(bundle_dir: str | Path, instruments: pd.DataFrame) -> pd.DataFrame:
    """Return the daily bars of ``instruments`` from ``futures.h5``."""

    path = Path(bundle_dir)
    frames: list[pd.DataFrame] = []
    with h5py.File(path / "futures.h5", "r") as handle:
        for order_book_id in instruments["order_book_id"]:
            key = str(order_book_id)
            if key not in handle:
                continue
            dataset = handle[key]
            raw = dataset["datetime"][:].astype(np.int64)
            frames.append(
                pd.DataFrame(
                    {
                        "order_book_id": key,
                        "trading_date": pd.to_datetime(pd.Series(raw).astype(str).str[:8]),
                        "open": dataset["open"][:].astype(float),
                        "high": dataset["high"][:].astype(float),
                        "low": dataset["low"][:].astype(float),
                        "close": dataset["close"][:].astype(float),
                        "prev_close": dataset["prev_close"][:].astype(float),
                        "volume": dataset["volume"][:].astype(float),
                        "open_interest": dataset["open_interest"][:].astype(float),
                    }
                )
            )
    if not frames:
        return pd.DataFrame(columns=BAR_COLUMNS)
    frame = pd.concat(frames, ignore_index=True)
    frame["order_book_id"] = frame["order_book_id"].astype("string")
    return frame.loc[:, list(BAR_COLUMNS)]


def load_contract_bars(
    bundle_dir: str | Path,
    products: list[str] | tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Return bars joined with contract metadata (maturity, listing, delisting)."""

    instruments = load_instruments(bundle_dir, products)
    bars = load_bars(bundle_dir, instruments)
    if bars.empty:
        return bars
    return bars.merge(instruments, on="order_book_id", how="left", validate="many_to_one")


TRADING_COLUMNS: tuple[str, ...] = (
    "order_book_id",
    "trading_date",
    "open",
    "high",
    "low",
    "close",
    "prev_close",
    "settlement",
    "prev_settlement",
    "limit_up",
    "limit_down",
    "volume",
    "total_turnover",
    "open_interest",
)


def load_trading_bars(
    bundle_dir: str | Path,
    products: list[str] | tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Return the bars a native account needs (settlement and limit prices included)."""

    path = Path(bundle_dir)
    instruments = load_instruments(path, products)
    frames: list[pd.DataFrame] = []
    with h5py.File(path / "futures.h5", "r") as handle:
        for order_book_id in instruments["order_book_id"]:
            key = str(order_book_id)
            if key not in handle:
                continue
            dataset = handle[key]
            raw = dataset["datetime"][:].astype(np.int64)
            frames.append(
                pd.DataFrame(
                    {
                        "order_book_id": key,
                        "trading_date": pd.to_datetime(pd.Series(raw).astype(str).str[:8]),
                        "open": dataset["open"][:].astype(float),
                        "high": dataset["high"][:].astype(float),
                        "low": dataset["low"][:].astype(float),
                        "close": dataset["close"][:].astype(float),
                        "prev_close": dataset["prev_close"][:].astype(float),
                        "settlement": dataset["settlement"][:].astype(float),
                        "prev_settlement": dataset["prev_settlement"][:].astype(float),
                        "limit_up": dataset["limit_up"][:].astype(float),
                        "limit_down": dataset["limit_down"][:].astype(float),
                        "volume": dataset["volume"][:].astype(float),
                        "total_turnover": dataset["total_turnover"][:].astype(float),
                        "open_interest": dataset["open_interest"][:].astype(float),
                    }
                )
            )
    if not frames:
        return pd.DataFrame(columns=TRADING_COLUMNS)
    frame = pd.concat(frames, ignore_index=True)
    frame["order_book_id"] = frame["order_book_id"].astype("string")
    return frame.loc[:, list(TRADING_COLUMNS)]


def load_future_info(bundle_dir: str | Path) -> pd.DataFrame:
    """Return product-level contract terms (commission, margin, tick size)."""

    path = Path(bundle_dir) / "future_info.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    frame = pd.DataFrame([row for row in rows if isinstance(row, dict)])
    columns = [
        "underlying_symbol",
        "commission_type",
        "open_commission_ratio",
        "close_commission_ratio",
        "close_commission_today_ratio",
        "margin_rate",
        "tick_size",
    ]
    frame = frame.loc[:, columns].drop_duplicates(subset=["underlying_symbol"], keep="last")
    return frame.rename(columns={"underlying_symbol": "product"}).reset_index(drop=True)
