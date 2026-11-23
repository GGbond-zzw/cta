"""The cleaned tree exposes eleven individually packaged factors."""
from pathlib import Path
import importlib,json
from china_cta.factors.qualified import BUILDERS
from china_cta.factors import classification

def test_all_eleven_have_individual_packages() -> None:
    assert len(BUILDERS)==11
    assert classification.QUALIFIED_SLEEVE_COUNT==11
    root=Path(__file__).resolve().parents[1]
    layout=json.loads((root/'docs/eleven_factor_layout.json').read_text(encoding='utf8'))
    assert {r['name'] for r in layout}==set(BUILDERS)
    for row in layout:
        folder=root/'china_cta/factors/qualified'/row['folder']
        assert (folder/'factor.py').is_file()
        assert (folder/'parameters.json').is_file()
        assert callable(importlib.import_module('china_cta.factors.qualified.'+row['folder']).build)
    assert not (root/'china_cta/factors/unqualified').exists()
