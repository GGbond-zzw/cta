"""Unit tests for the rolling volatility calibration in `scripts/70_native_backtest.py`."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "70_native_backtest.py"


@pytest.fixture(scope="module")
def stage70():
    spec = importlib.util.spec_from_file_location("stage70_calibration", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _equity(returns: np.ndarray, start: str = "2020-01-01") -> pd.Series:
    index = pd.bdate_range(start, periods=len(returns) + 1)
    values = 50_000_000.0 * np.cumprod(np.concatenate([[1.0], 1.0 + returns]))
    return pd.Series(values, index=index)


def test_warmup_rows_are_neutral(stage70) -> None:
    rng = np.random.default_rng(7)
    equity = _equity(rng.normal(0.0, 0.01, 400))

    factor = stage70._calibration_path(equity, target=0.20, window=60, cap=3.0, min_periods=20)

    assert factor.iloc[:20].eq(1.0).all()
    assert factor.iloc[25:].ne(1.0).any()


def test_factor_matches_target_over_realised(stage70) -> None:
    rng = np.random.default_rng(11)
    returns = rng.normal(0.0, 0.0105, 800)
    equity = _equity(returns)

    factor = stage70._calibration_path(equity, target=0.20, window=60, cap=3.0, min_periods=20)

    realised = pd.Series(returns).rolling(60, min_periods=20).std(ddof=1).shift(1) * np.sqrt(252)
    expected = (0.20 / realised).clip(upper=3.0).fillna(1.0)
    # the equity series carries one extra leading row (the pct_change base)
    assert np.allclose(factor.to_numpy()[101:], expected.to_numpy()[100:])


def test_no_lookahead(stage70) -> None:
    rng = np.random.default_rng(3)
    returns = rng.normal(0.0, 0.012, 300)
    equity = _equity(returns)
    base = stage70._calibration_path(equity, target=0.20, window=60, cap=3.0, min_periods=20)

    perturbed = equity.copy()
    perturbed.iloc[-1] *= 1.5
    bumped = stage70._calibration_path(
        perturbed, target=0.20, window=60, cap=3.0, min_periods=20
    )

    assert np.allclose(base.to_numpy()[:-1], bumped.to_numpy()[:-1])
    assert base.iloc[-1] == pytest.approx(bumped.iloc[-1])


def test_cap_is_enforced(stage70) -> None:
    returns = np.full(400, 0.0001)
    returns[300:] = 0.000001  # volatility collapses
    equity = _equity(returns)

    factor = stage70._calibration_path(equity, target=0.20, window=60, cap=1.5, min_periods=20)

    assert factor.max() <= 1.5
