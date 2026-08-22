"""RQAlpha Plus integration for formal trading simulation."""

from china_cta.formal_backtest.adapter import (
    ORDER_COLUMNS,
    TARGET_EXECUTION_COLUMNS,
    TARGET_POSITION_COLUMNS,
    FormalBacktestConfig,
    run_formal_backtest,
)
from china_cta.formal_backtest.results import load_formal_result

__all__ = [
    "ORDER_COLUMNS",
    "TARGET_EXECUTION_COLUMNS",
    "TARGET_POSITION_COLUMNS",
    "FormalBacktestConfig",
    "load_formal_result",
    "run_formal_backtest",
]
