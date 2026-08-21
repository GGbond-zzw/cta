"""Fast vectorized research and diagnostics without account simulation."""

from china_cta.research.fast_backtest import (
    DETAIL_COLUMNS,
    METRIC_COLUMNS,
    run_fast_research_backtest,
    run_parameter_surface,
    save_research_run,
)

__all__ = [
    "DETAIL_COLUMNS",
    "METRIC_COLUMNS",
    "run_fast_research_backtest",
    "run_parameter_surface",
    "save_research_run",
]
