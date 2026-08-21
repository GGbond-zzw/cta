"""Thin, cacheable RQData boundary for domestic futures research."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Final, TypeAlias

import pandas as pd
import rqdatac

from china_cta.data.cache import read_frame, write_frame


DateLike: TypeAlias = str | date | datetime | pd.Timestamp

INSTRUMENT_MASTER_COLUMNS: Final[tuple[str, ...]] = (
    "order_book_id",
    "underlying_symbol",
    "exchange",
    "listed_date",
    "de_listed_date",
    "maturity_date",
    "contract_multiplier",
    "product",
)
INSTRUMENT_DETAIL_COLUMNS: Final[tuple[str, ...]] = (
    *INSTRUMENT_MASTER_COLUMNS,
    "margin_rate",
    "tick_size",
)
DEFAULT_DAILY_FIELDS: Final[tuple[str, ...]] = (
    "open",
    "high",
    "low",
    "close",
    "settlement",
    "volume",
    "open_interest",
)
DEFAULT_MINUTE_FIELDS: Final[tuple[str, ...]] = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "open_interest",
)
NUMERIC_BAR_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "open",
        "high",
        "low",
        "close",
        "settlement",
        "prev_settlement",
        "volume",
        "open_interest",
        "total_turnover",
        "limit_up",
        "limit_down",
    }
)
DEFAULT_CACHE_DIR: Final[Path] = Path("data/cache/rqdata")


class RQDataAdapterError(RuntimeError):
    """Raised when RQData cannot be initialized or queried."""


class DataValidationError(ValueError):
    """Raised when provider data cannot satisfy the Phase 1 contract."""


@dataclass(frozen=True, slots=True)
class RQDataConfig:
    """Local connection and cache settings; credentials are never persisted."""

    uri: str | None = None
    market: str = "cn"
    cache_dir: Path | None = DEFAULT_CACHE_DIR

    @classmethod
    def from_environment(cls) -> "RQDataConfig":
        """Read process-local settings without changing global PATH."""

        cache_value = os.getenv("CTA_RQDATA_CACHE_DIR")
        cache_dir = Path(cache_value) if cache_value else DEFAULT_CACHE_DIR
        return cls(
            uri=os.getenv("RQDATAC2_CONF") or os.getenv("RQDATAC_CONF"),
            market=os.getenv("RQDATA_MARKET", "cn"),
            cache_dir=cache_dir,
        )


class RQDataAdapter:
    """Expose the small set of RQData queries required by the current phases."""

    def __init__(self, config: RQDataConfig | None = None) -> None:
        self.config = config or RQDataConfig.from_environment()
        self._initialized = False

    def connect(self, *, lazy: bool = True, force: bool = False) -> None:
        """Initialize rqdatac without printing or storing credentials."""

        if rqdatac.initialized() and not force:
            self._initialized = True
            return

        try:
            if self.config.uri:
                rqdatac.init(uri=self.config.uri, lazy=lazy)
            else:
                rqdatac.init(lazy=lazy)
        except Exception as exc:
            raise RQDataAdapterError(
                "RQData initialization failed. Configure RQDATAC2_CONF or "
                "RQDATAC_CONF locally; never commit its value."
            ) from exc
        self._initialized = True

    def get_trading_calendar(
        self,
        start_date: DateLike,
        end_date: DateLike,
    ) -> pd.DatetimeIndex:
        """Return the official RQData trading calendar for the date range."""

        request_params = {
            "start_date": start_date,
            "end_date": end_date,
            "market": self.config.market,
        }

        def fetch() -> pd.DataFrame:
            self._ensure_initialized()
            try:
                values = rqdatac.get_trading_dates(
                    start_date,
                    end_date,
                    market=self.config.market,
                )
            except Exception as exc:
                raise RQDataAdapterError("RQData trading-calendar query failed") from exc
            return pd.DataFrame(
                {"trading_date": pd.to_datetime(values, errors="raise")}
            )

        frame = self._cached_frame("trading_calendar", request_params, fetch)
        dates = pd.DatetimeIndex(frame["trading_date"], name="trading_date")
        return dates.sort_values().unique()

    def get_future_instruments(self, date: DateLike | None = None) -> pd.DataFrame:
        """Return the Phase 1 instrument master from ``all_instruments``."""

        request_params = {
            "date": date,
            "type": "Future",
            "market": self.config.market,
        }

        def fetch() -> pd.DataFrame:
            self._ensure_initialized()
            try:
                raw = rqdatac.all_instruments(
                    type="Future",
                    date=date,
                    market=self.config.market,
                )
            except Exception as exc:
                raise RQDataAdapterError("RQData future-instruments query failed") from exc
            return self._standardize_instruments(pd.DataFrame(raw))

        return self._cached_frame("future_instruments", request_params, fetch)

    def get_future_contracts(
        self,
        underlying_symbol: str,
        date: DateLike,
    ) -> tuple[str, ...]:
        """Return RQData's real, tradable contracts for one product and date."""

        symbol = self._normalize_ids(underlying_symbol, "underlying_symbol")[0]
        request_params = {
            "underlying_symbol": symbol,
            "date": date,
            "market": self.config.market,
        }

        def fetch() -> pd.DataFrame:
            self._ensure_initialized()
            try:
                result = rqdatac.futures.get_contracts(
                    symbol,
                    date=date,
                    market=self.config.market,
                )
            except Exception as exc:
                raise RQDataAdapterError(
                    f"RQData future-contracts query failed for {symbol}"
                ) from exc
            contracts = self._normalize_ids(
                () if result is None else result, "future contracts"
            )
            frame = pd.DataFrame({"order_book_id": contracts})
            self._validate_unique(frame, ["order_book_id"], "future contracts")
            return frame

        frame = self._cached_frame("future_contracts", request_params, fetch)
        if frame.columns.tolist() != ["order_book_id"]:
            raise DataValidationError(
                "Future-contract cache must contain only order_book_id"
            )
        return tuple(frame["order_book_id"].astype(str))

    def get_instrument_details(
        self,
        order_book_ids: str | Sequence[str],
    ) -> pd.DataFrame:
        """Return required futures attributes, including ``tick_size()``."""

        ids = self._normalize_ids(order_book_ids, "order_book_ids")
        request_params = {"order_book_ids": ids, "market": self.config.market}

        def fetch() -> pd.DataFrame:
            self._ensure_initialized()
            query_ids: str | list[str] = ids[0] if len(ids) == 1 else list(ids)
            try:
                result = rqdatac.instruments(query_ids, market=self.config.market)
            except Exception as exc:
                raise RQDataAdapterError(
                    f"RQData instrument-details query failed for {', '.join(ids)}"
                ) from exc

            instruments = result if isinstance(result, (list, tuple)) else [result]
            rows: list[dict[str, object]] = []
            for instrument in instruments:
                tick_size = getattr(instrument, "tick_size", None)
                rows.append(
                    {
                        column: (
                            tick_size()
                            if column == "tick_size" and callable(tick_size)
                            else tick_size
                            if column == "tick_size"
                            else getattr(instrument, column, None)
                        )
                        for column in INSTRUMENT_DETAIL_COLUMNS
                    }
                )
            frame = self._standardize_instruments(
                pd.DataFrame(rows), include_tick_size=True
            )
            returned_ids = set(frame["order_book_id"].astype(str))
            missing = sorted(set(ids) - returned_ids)
            if missing:
                raise DataValidationError(
                    f"RQData returned no instrument details for: {missing}"
                )
            return frame

        return self._cached_frame("instrument_details", request_params, fetch)

    def get_bars(
        self,
        order_book_ids: str | Sequence[str],
        start_date: DateLike,
        end_date: DateLike,
        *,
        frequency: str = "1d",
        fields: str | Sequence[str] | None = None,
    ) -> pd.DataFrame:
        """Return unadjusted real-contract daily or minute bars.

        Daily output starts with ``trading_date, order_book_id``.  Minute
        output starts with ``datetime, trading_date, order_book_id`` so a
        night-session timestamp is never mistaken for its futures trading day.
        """

        ids = self._normalize_ids(order_book_ids, "order_book_ids")
        normalized_frequency = frequency.strip().lower()
        is_daily = normalized_frequency == "1d"
        is_minute = re.fullmatch(r"[1-9][0-9]*m", normalized_frequency) is not None
        if not is_daily and not is_minute:
            raise ValueError("Phase 1 get_bars supports daily and minute frequencies")

        default_fields = DEFAULT_DAILY_FIELDS if is_daily else DEFAULT_MINUTE_FIELDS
        requested_fields = self._normalize_fields(
            default_fields if fields is None else fields
        )
        provider_fields = list(requested_fields)
        if is_minute and "trading_date" not in provider_fields:
            provider_fields.append("trading_date")

        request_params = {
            "order_book_ids": ids,
            "start_date": start_date,
            "end_date": end_date,
            "frequency": normalized_frequency,
            "fields": requested_fields,
            "adjust_type": "none",
            "market": self.config.market,
        }

        def fetch() -> pd.DataFrame:
            self._ensure_initialized()
            query_ids: str | list[str] = ids[0] if len(ids) == 1 else list(ids)
            try:
                result = rqdatac.get_price(
                    query_ids,
                    start_date=start_date,
                    end_date=end_date,
                    frequency=normalized_frequency,
                    fields=provider_fields,
                    adjust_type="none",
                    expect_df=True,
                    market=self.config.market,
                )
            except Exception as exc:
                raise RQDataAdapterError(
                    f"RQData bars query failed for {', '.join(ids)}"
                ) from exc
            if result is None or len(result) == 0:
                raise RQDataAdapterError(
                    f"RQData returned no bars for {', '.join(ids)} between "
                    f"{start_date} and {end_date}"
                )
            raw = result.to_frame() if isinstance(result, pd.Series) else result
            return self._standardize_bars(
                pd.DataFrame(raw), ids, requested_fields, is_daily=is_daily
            )

        return self._cached_frame("bars", request_params, fetch)

    def get_dominant_map(
        self,
        underlying_symbols: str | Sequence[str],
        start_date: DateLike,
        end_date: DateLike,
        *,
        rule: int = 0,
        rank: int = 1,
    ) -> pd.DataFrame:
        """Return RQData's point-in-time dominant real-contract mapping."""

        symbols = self._normalize_ids(underlying_symbols, "underlying_symbols")
        if rule not in (0, 1, 2, 3):
            raise ValueError("rule must be one of 0, 1, 2, or 3")
        if rank not in (1, 2, 3):
            raise ValueError("rank must be one of 1, 2, or 3")
        request_params = {
            "underlying_symbols": symbols,
            "start_date": start_date,
            "end_date": end_date,
            "rule": rule,
            "rank": rank,
            "market": self.config.market,
        }

        def fetch() -> pd.DataFrame:
            self._ensure_initialized()
            frames: list[pd.DataFrame] = []
            for symbol in symbols:
                try:
                    result = rqdatac.futures.get_dominant(
                        symbol,
                        start_date=start_date,
                        end_date=end_date,
                        rule=rule,
                        rank=rank,
                        market=self.config.market,
                    )
                except Exception as exc:
                    raise RQDataAdapterError(
                        f"RQData dominant-contract query failed for {symbol}"
                    ) from exc
                if result is None or len(result) == 0:
                    raise RQDataAdapterError(
                        f"RQData returned no dominant contracts for {symbol}"
                    )

                if isinstance(result, pd.Series):
                    frame = result.rename("dominant_order_book_id").reset_index()
                else:
                    frame = pd.DataFrame(result).reset_index()
                    value_columns = [
                        column
                        for column in frame.columns
                        if column not in ("date", "datetime", "index")
                    ]
                    if len(value_columns) != 1:
                        raise DataValidationError(
                            "Dominant result must contain exactly one value column"
                        )
                    frame = frame.rename(
                        columns={value_columns[0]: "dominant_order_book_id"}
                    )
                date_column = self._first_column(
                    frame, ("date", "datetime", "index")
                )
                if date_column is None:
                    raise DataValidationError("Dominant result has no date column")
                frame = frame.rename(columns={date_column: "trading_date"})
                frame.insert(1, "underlying_symbol", symbol)
                frames.append(
                    frame.loc[
                        :,
                        [
                            "trading_date",
                            "underlying_symbol",
                            "dominant_order_book_id",
                        ],
                    ]
                )

            combined = pd.concat(frames, ignore_index=True)
            combined["trading_date"] = pd.to_datetime(
                combined["trading_date"], errors="raise"
            ).dt.normalize()
            for column in ("underlying_symbol", "dominant_order_book_id"):
                combined[column] = (
                    combined[column].astype("string").str.strip().str.upper()
                )
            if combined["dominant_order_book_id"].isna().any() or combined[
                "dominant_order_book_id"
            ].eq("").any():
                raise DataValidationError("Dominant result contains missing IDs")
            self._validate_unique(
                combined, ["trading_date", "underlying_symbol"], "dominant map"
            )
            return combined.sort_values(
                ["trading_date", "underlying_symbol"]
            ).reset_index(drop=True)

        return self._cached_frame("dominant_map", request_params, fetch)

    def get_dominant_price(
        self,
        underlying_symbols: str | Sequence[str],
        start_date: DateLike,
        end_date: DateLike,
        *,
        fields: str | Sequence[str] | None = None,
        adjust_type: str = "pre",
        adjust_method: str = "prev_close_spread",
        rule: int = 0,
        rank: int = 1,
    ) -> pd.DataFrame:
        """Return RQData continuous prices for signal/research use only.

        These adjusted prices must never be used to calculate cash P&L.
        """

        symbols = self._normalize_ids(underlying_symbols, "underlying_symbols")
        if adjust_type not in ("none", "pre", "post"):
            raise ValueError("adjust_type must be 'none', 'pre', or 'post'")
        if adjust_method not in (
            "prev_close_spread",
            "open_spread",
            "prev_close_ratio",
            "open_ratio",
        ):
            raise ValueError("unsupported RQData dominant-price adjustment method")
        if rule not in (0, 1, 2, 3):
            raise ValueError("rule must be one of 0, 1, 2, or 3")
        if rank not in (1, 2, 3):
            raise ValueError("rank must be one of 1, 2, or 3")

        requested_fields = self._normalize_fields(
            DEFAULT_DAILY_FIELDS if fields is None else fields
        )
        request_params = {
            "underlying_symbols": symbols,
            "start_date": start_date,
            "end_date": end_date,
            "frequency": "1d",
            "fields": requested_fields,
            "adjust_type": adjust_type,
            "adjust_method": adjust_method,
            "rule": rule,
            "rank": rank,
        }

        def fetch() -> pd.DataFrame:
            self._ensure_initialized()
            query_symbols: str | list[str] = (
                symbols[0] if len(symbols) == 1 else list(symbols)
            )
            try:
                result = rqdatac.futures.get_dominant_price(
                    query_symbols,
                    start_date=start_date,
                    end_date=end_date,
                    frequency="1d",
                    fields=list(requested_fields),
                    adjust_type=adjust_type,
                    adjust_method=adjust_method,
                    rule=rule,
                    rank=rank,
                )
            except Exception as exc:
                raise RQDataAdapterError(
                    "RQData dominant-price query failed for " + ", ".join(symbols)
                ) from exc
            if result is None or len(result) == 0:
                raise RQDataAdapterError(
                    "RQData returned no dominant prices for " + ", ".join(symbols)
                )
            raw = result.to_frame() if isinstance(result, pd.Series) else result
            return self._standardize_dominant_prices(
                pd.DataFrame(raw),
                symbols,
                requested_fields,
            )

        return self._cached_frame("dominant_price", request_params, fetch)

    def get_trading_parameters(
        self,
        order_book_ids: str | Sequence[str],
        start_date: DateLike,
        end_date: DateLike,
    ) -> pd.DataFrame:
        """Return historical RQData fields without changing units or meaning."""

        ids = self._normalize_ids(order_book_ids, "order_book_ids")
        request_params = {
            "order_book_ids": ids,
            "start_date": start_date,
            "end_date": end_date,
            "market": self.config.market,
        }

        def fetch() -> pd.DataFrame:
            self._ensure_initialized()
            query_ids: str | list[str] = ids[0] if len(ids) == 1 else list(ids)
            try:
                result = rqdatac.futures.get_trading_parameters(
                    query_ids,
                    start_date=start_date,
                    end_date=end_date,
                    market=self.config.market,
                )
            except Exception as exc:
                raise RQDataAdapterError(
                    f"RQData trading-parameters query failed for {', '.join(ids)}"
                ) from exc
            if result is None or len(result) == 0:
                raise RQDataAdapterError(
                    f"RQData returned no trading parameters for {', '.join(ids)}"
                )
            return self._standardize_trading_parameters(pd.DataFrame(result), ids)

        return self._cached_frame("trading_parameters", request_params, fetch)

    def _cached_frame(
        self,
        operation: str,
        request_params: dict[str, object],
        fetch: Callable[[], pd.DataFrame],
    ) -> pd.DataFrame:
        cache_dir = self.config.cache_dir
        if cache_dir is None:
            return fetch()
        cache_path = Path(cache_dir)
        cached = read_frame(cache_path, operation, request_params)
        if cached is not None:
            return cached

        fresh = fetch()
        write_frame(
            cache_path,
            operation,
            request_params,
            fresh,
            rqdatac_version=version("rqdatac"),
        )
        canonical = read_frame(cache_path, operation, request_params)
        if canonical is None:  # pragma: no cover - guarded by write_frame
            raise RuntimeError("Cache write completed without a readable entry")
        return canonical

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            self.connect()

    @staticmethod
    def _normalize_ids(values: str | Sequence[str], name: str) -> tuple[str, ...]:
        items = (values,) if isinstance(values, str) else tuple(values)
        if any(not isinstance(item, str) for item in items):
            raise TypeError(f"{name} must contain strings only")
        normalized = tuple(
            dict.fromkeys(item.strip().upper() for item in items if item.strip())
        )
        if not normalized:
            raise ValueError(f"{name} must contain at least one value")
        return normalized

    @staticmethod
    def _normalize_fields(fields: str | Sequence[str]) -> tuple[str, ...]:
        items = (fields,) if isinstance(fields, str) else tuple(fields)
        if any(not isinstance(field, str) for field in items):
            raise TypeError("fields must contain strings only")
        normalized = tuple(
            dict.fromkeys(field.strip() for field in items if field.strip())
        )
        if not normalized:
            raise ValueError("fields must contain at least one field")
        return normalized

    @staticmethod
    def _standardize_instruments(
        frame: pd.DataFrame,
        *,
        include_tick_size: bool = False,
    ) -> pd.DataFrame:
        columns = (
            INSTRUMENT_DETAIL_COLUMNS
            if include_tick_size
            else INSTRUMENT_MASTER_COLUMNS
        )
        missing = [column for column in columns if column not in frame.columns]
        if missing:
            raise DataValidationError(f"Instrument data is missing fields: {missing}")
        standardized = frame.loc[:, columns].copy()
        for column in ("order_book_id", "underlying_symbol", "exchange", "product"):
            standardized[column] = standardized[column].astype("string").str.strip()
        standardized["order_book_id"] = standardized["order_book_id"].str.upper()
        standardized["underlying_symbol"] = standardized[
            "underlying_symbol"
        ].str.upper()
        for column in ("listed_date", "de_listed_date", "maturity_date"):
            standardized[column] = pd.to_datetime(
                standardized[column], errors="coerce"
            ).dt.normalize()
        numeric_columns = ["contract_multiplier"]
        if include_tick_size:
            numeric_columns.extend(("margin_rate", "tick_size"))
        for column in numeric_columns:
            standardized[column] = pd.to_numeric(
                standardized[column], errors="coerce"
            )
        if standardized["order_book_id"].isna().any() or standardized[
            "order_book_id"
        ].eq("").any():
            raise DataValidationError("Instrument data contains missing IDs")
        RQDataAdapter._validate_unique(
            standardized, ["order_book_id"], "instrument data"
        )
        return standardized.sort_values("order_book_id").reset_index(drop=True)

    @staticmethod
    def _standardize_bars(
        raw: pd.DataFrame,
        requested_ids: tuple[str, ...],
        requested_fields: tuple[str, ...],
        *,
        is_daily: bool,
    ) -> pd.DataFrame:
        frame = raw.copy().reset_index()
        if "order_book_id" not in frame.columns:
            if len(requested_ids) != 1:
                raise DataValidationError(
                    "Bars lost order_book_id for a multi-contract query"
                )
            frame.insert(0, "order_book_id", requested_ids[0])

        if is_daily:
            if "trading_date" not in frame.columns:
                date_column = RQDataAdapter._first_column(
                    frame, ("date", "datetime", "index")
                )
                if date_column is None:
                    raise DataValidationError("Daily bars have no date column")
                frame = frame.rename(columns={date_column: "trading_date"})
        else:
            if "datetime" not in frame.columns:
                datetime_column = RQDataAdapter._first_column(
                    frame, ("date", "index")
                )
                if datetime_column is None:
                    raise DataValidationError("Minute bars have no datetime column")
                frame = frame.rename(columns={datetime_column: "datetime"})
            if "trading_date" not in frame.columns:
                raise DataValidationError(
                    "Minute futures bars must retain RQData trading_date"
                )

        data_fields = [
            field
            for field in requested_fields
            if field not in ("datetime", "trading_date", "order_book_id")
        ]
        missing = [field for field in data_fields if field not in frame.columns]
        if missing:
            raise DataValidationError(f"Bars are missing fields: {missing}")

        frame["order_book_id"] = (
            frame["order_book_id"].astype("string").str.strip().str.upper()
        )
        frame["trading_date"] = pd.to_datetime(
            frame["trading_date"], errors="raise"
        ).dt.normalize()
        if not is_daily:
            frame["datetime"] = pd.to_datetime(frame["datetime"], errors="raise")
        for field in set(data_fields).intersection(NUMERIC_BAR_FIELDS):
            frame[field] = pd.to_numeric(frame[field], errors="coerce")

        key = ["order_book_id", "trading_date"] if is_daily else [
            "order_book_id",
            "datetime",
        ]
        RQDataAdapter._validate_unique(frame, key, "bars")
        if {"high", "low"}.issubset(frame.columns) and (
            frame["high"] < frame["low"]
        ).any():
            raise DataValidationError("Bars contain high values below low values")
        for field in ("volume", "open_interest", "total_turnover"):
            if field in frame.columns and frame[field].lt(0).any():
                raise DataValidationError(f"Bars contain negative {field}")

        leading = (
            ["trading_date", "order_book_id"]
            if is_daily
            else ["datetime", "trading_date", "order_book_id"]
        )
        sort_columns = (
            ["order_book_id", "trading_date"]
            if is_daily
            else ["order_book_id", "datetime"]
        )
        return (
            frame.loc[:, [*leading, *data_fields]]
            .sort_values(sort_columns)
            .reset_index(drop=True)
        )

    @staticmethod
    def _standardize_trading_parameters(
        raw: pd.DataFrame,
        requested_ids: tuple[str, ...],
    ) -> pd.DataFrame:
        frame = raw.copy().reset_index()
        if "order_book_ids" in frame.columns and "order_book_id" not in frame.columns:
            frame = frame.rename(columns={"order_book_ids": "order_book_id"})
        if "order_book_id" not in frame.columns:
            if len(requested_ids) != 1:
                raise DataValidationError(
                    "Trading parameters lost order_book_id for multiple contracts"
                )
            frame.insert(0, "order_book_id", requested_ids[0])
        if "trading_date" not in frame.columns:
            date_column = RQDataAdapter._first_column(frame, ("date", "index"))
            if date_column is None:
                raise DataValidationError("Trading parameters have no trading date")
            frame = frame.rename(columns={date_column: "trading_date"})

        frame["order_book_id"] = (
            frame["order_book_id"].astype("string").str.strip().str.upper()
        )
        frame["trading_date"] = pd.to_datetime(
            frame["trading_date"], errors="raise"
        ).dt.normalize()
        RQDataAdapter._validate_unique(
            frame, ["trading_date", "order_book_id"], "trading parameters"
        )
        remaining = [
            column
            for column in frame.columns
            if column not in ("trading_date", "order_book_id")
        ]
        return (
            frame.loc[:, ["trading_date", "order_book_id", *remaining]]
            .sort_values(["trading_date", "order_book_id"])
            .reset_index(drop=True)
        )

    @staticmethod
    def _standardize_dominant_prices(
        raw: pd.DataFrame,
        requested_symbols: tuple[str, ...],
        requested_fields: tuple[str, ...],
    ) -> pd.DataFrame:
        frame = raw.copy().reset_index()
        if "underlying_symbol" not in frame.columns:
            if len(requested_symbols) != 1:
                raise DataValidationError(
                    "Dominant prices lost underlying_symbol for multiple products"
                )
            frame.insert(0, "underlying_symbol", requested_symbols[0])

        if "trading_date" not in frame.columns:
            date_column = RQDataAdapter._first_column(
                frame, ("date", "datetime", "index")
            )
            if date_column is None:
                raise DataValidationError("Daily dominant prices have no date")
            frame = frame.rename(columns={date_column: "trading_date"})

        data_fields = [
            field
            for field in requested_fields
            if field not in ("trading_date", "underlying_symbol")
        ]
        missing = [field for field in data_fields if field not in frame.columns]
        if missing:
            raise DataValidationError(
                f"Dominant prices are missing fields: {missing}"
            )

        frame["underlying_symbol"] = (
            frame["underlying_symbol"].astype("string").str.strip().str.upper()
        )
        frame["trading_date"] = pd.to_datetime(
            frame["trading_date"], errors="raise"
        ).dt.normalize()
        for field in data_fields:
            if field in NUMERIC_BAR_FIELDS:
                frame[field] = pd.to_numeric(frame[field], errors="coerce")
        if "volume" in frame.columns and frame["volume"].dropna().lt(0).any():
            raise DataValidationError("Dominant prices contain negative volume")
        if (
            "open_interest" in frame.columns
            and frame["open_interest"].dropna().lt(0).any()
        ):
            raise DataValidationError(
                "Dominant prices contain negative open_interest"
            )

        leading = ["trading_date", "underlying_symbol"]
        key = ["trading_date", "underlying_symbol"]
        RQDataAdapter._validate_unique(frame, key, "dominant prices")
        return (
            frame.loc[:, [*leading, *data_fields]]
            .sort_values(key)
            .reset_index(drop=True)
        )

    @staticmethod
    def _first_column(frame: pd.DataFrame, candidates: Sequence[str]) -> str | None:
        return next((column for column in candidates if column in frame.columns), None)

    @staticmethod
    def _validate_unique(
        frame: pd.DataFrame,
        key: list[str],
        label: str,
    ) -> None:
        if frame.duplicated(key).any():
            duplicates = frame.loc[frame.duplicated(key, keep=False), key]
            raise DataValidationError(
                f"Duplicate {label} rows: "
                f"{duplicates.head().to_dict(orient='records')}"
            )
