"""Factor qualification registry used to route code, results and tests.

From 2026-11 the qualified set is the nine sleeves of the live book: four written
in this package and five mined sleeves exported as frozen signals.  All nine are
validated with next-open execution, next-open fills and the native-account result
layer on the fixed-30 pool.

Four package sleeves (:data:`QUALIFIED_FACTORS`):

* ``fixed_maturity_carry_90_180d``
* ``historical_skewness_252d``
* ``oi_participation_trend_60d``
* ``xsmom_252_21``

Five exported sleeves (:data:`QUALIFIED_EXPORTED_SLEEVES` in
:mod:`china_cta.factors.exported`):

* ``crowded_trend_reversal_60d``
* ``volume_burst_vol_reversal_60d``
* ``turnover_surprise_channel_ratio``
* ``inverse_oi_turnover_surprise_ratio``
* ``volume_variability_weighted_reversal``

Everything else lives in :mod:`china_cta.factors.unqualified`: factors that
scored Sharpe <= 0.65 on the fixed-30 pool, designs whose provider data is
missing, and the superseded ``breakout_55`` / ``carry_ann`` /
``vol_scaled_carry`` / ``historical_skewness_252d_cs_rank`` variants.  Two
exported sleeves are retired but kept for reproducibility:
``volume_oi_coflow_10d`` (negative out-of-sample Sharpe) and
``volume_channel_price_oi_volatility`` (0.72 correlated with
``turnover_surprise_channel_ratio``).
"""

from __future__ import annotations

from pathlib import Path

from .exported import (
    QUALIFIED_EXPORTED_SLEEVES,
    RETIRED_EXPORTED_SLEEVES,
    qualified_sleeves as _qualified_exported,
)


QUALIFIED_FACTORS: frozenset[str] = frozenset(
    {
        "fixed_maturity_carry_90_180d",
        "historical_skewness_252d",
        "oi_participation_trend_60d",
        "xsmom_252_21",
    }
)

#: Names of the exported sleeves that the live book uses.
QUALIFIED_EXPORTED: tuple[str, ...] = QUALIFIED_EXPORTED_SLEEVES
#: Exported sleeves that are kept for reproducibility but no longer traded.
RETIRED_EXPORTED: tuple[str, ...] = RETIRED_EXPORTED_SLEEVES
#: The nine sleeve names of the live book, package sleeves first.
QUALIFIED_SLEEVES: tuple[str, ...] = (
    "fixed_maturity_carry_90_180d",
    "historical_skewness_252d",
    "oi_participation_trend_60d",
    "xsmom_252_21",
) + QUALIFIED_EXPORTED
QUALIFIED_SLEEVE_COUNT: int = len(QUALIFIED_SLEEVES)


def classification(factor_name: str) -> str:
    """Return ``qualified``, ``retired`` or ``unqualified`` for a sleeve name."""

    if factor_name in QUALIFIED_FACTORS or factor_name in QUALIFIED_EXPORTED:
        return "qualified"
    if factor_name in RETIRED_EXPORTED:
        return "retired"
    return "unqualified"


def qualified_sleeve_names() -> tuple[str, ...]:
    """The nine sleeve names of the live book, in book order."""

    exported = tuple(sleeve.name for sleeve in _qualified_exported())
    return QUALIFIED_SLEEVES[: len(QUALIFIED_FACTORS)] + tuple(
        name for name in exported if name not in QUALIFIED_FACTORS
    )


def result_root(factor_name: str, *, base: str | Path = "results") -> Path:
    """Return the classification-specific result directory for a factor."""

    return Path(base) / classification(factor_name)
