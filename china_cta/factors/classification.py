"""Factor qualification registry used to route code, results and tests.

From 2026-11 the only qualified factors are the four sleeves of the live book,
all validated with next-open execution and next-open fills on the fixed-30 pool:

* ``fixed_maturity_carry_90_180d``
* ``historical_skewness_252d``
* ``oi_participation_trend_60d``
* ``xsmom_252_21``

Everything else lives in :mod:`china_cta.factors.unqualified`: factors that
scored Sharpe <= 0.65 on the fixed-30 pool, designs whose provider data is
missing, and the superseded ``breakout_55`` / ``carry_ann`` /
``vol_scaled_carry`` / ``historical_skewness_252d_cs_rank`` variants.
"""

from __future__ import annotations

from pathlib import Path


QUALIFIED_FACTORS: frozenset[str] = frozenset(
    {
        "fixed_maturity_carry_90_180d",
        "historical_skewness_252d",
        "oi_participation_trend_60d",
        "xsmom_252_21",
    }
)


def classification(factor_name: str) -> str:
    """Return ``qualified`` or ``unqualified`` for a factor name."""

    return "qualified" if factor_name in QUALIFIED_FACTORS else "unqualified"


def result_root(factor_name: str, *, base: str | Path = "results") -> Path:
    """Return the classification-specific result directory for a factor."""

    return Path(base) / classification(factor_name)
