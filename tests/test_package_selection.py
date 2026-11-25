"""`--package-factors all` must skip packages that cannot run here."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "70_native_backtest.py"


def _module():
    spec = importlib.util.spec_from_file_location("stage70", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_all_skips_unavailable_packages() -> None:
    stage70 = _module()
    names = stage70._package_selection("all", [])
    assert "our_reg35_transformer" not in names
    assert len(names) == 10

    explicit = stage70._package_selection("qualified", [])
    assert explicit == names

    with pytest.raises(SystemExit):
        stage70._package_selection("our_reg35_transformer", [])


def test_already_selected_sleeves_are_not_duplicated() -> None:
    stage70 = _module()
    names = stage70._package_selection("all", ["xsmom_252_21"])
    assert "xsmom_252_21" not in names
    assert len(names) == 9
