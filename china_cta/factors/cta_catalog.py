"""Only the eleven retained builders are available in this catalog."""
from dataclasses import dataclass,asdict
import pandas as pd
from .qualified import BUILDERS
from .cta_common import FactorDataUnavailable
@dataclass(frozen=True)
class FactorSpec:
    name: str
    available: bool=True
FACTOR_SPECS=tuple(FactorSpec(n) for n in BUILDERS)
AVAILABLE_FACTORS=tuple(BUILDERS)
UNAVAILABLE_FACTORS=()
UNAVAILABLE_REASONS={}
def spec_table() -> pd.DataFrame:
    return pd.DataFrame([asdict(s) for s in FACTOR_SPECS])
def build_all(**inputs: pd.DataFrame) -> tuple[dict[str,pd.DataFrame],dict[str,str]]:
    return {n:b(inputs) for n,b in BUILDERS.items()},{}
