"""Current eleven-factor registry; directory inclusion is not statistical proof."""
from pathlib import Path
from .qualified import BUILDERS
from .exported import QUALIFIED_EXPORTED_SLEEVES
QUALIFIED_FACTORS=frozenset(BUILDERS)
QUALIFIED_EXPORTED=QUALIFIED_EXPORTED_SLEEVES
RETIRED_EXPORTED=()
QUALIFIED_SLEEVES=tuple(BUILDERS)
QUALIFIED_SLEEVE_COUNT=len(BUILDERS)
def classification(factor_name: str) -> str:
    return 'qualified' if factor_name in BUILDERS else 'unqualified'
def qualified_sleeve_names() -> tuple[str,...]:
    return QUALIFIED_SLEEVES
def result_root(factor_name: str,*,base: str|Path='results') -> Path:
    return Path(base)/classification(factor_name)
