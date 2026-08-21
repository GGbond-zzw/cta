from __future__ import annotations

import importlib
import importlib.metadata
import sys

import pytest


REQUIRED_PACKAGES = {
    "numpy": "numpy",
    "pandas": "pandas",
    "scipy": "scipy",
    "matplotlib": "matplotlib",
    "pyarrow": "pyarrow",
    "PyYAML": "yaml",
    "pytest": "pytest",
    "rqdatac": "rqdatac",
    "rqsdk": "rqsdk",
    "rqalpha-plus": "rqalpha_plus",
    "rqfactor": "rqfactor",
}


def test_project_runs_on_python_311() -> None:
    assert sys.version_info[:2] == (3, 11)


@pytest.mark.parametrize(("distribution", "module"), REQUIRED_PACKAGES.items())
def test_required_package_is_installed(distribution: str, module: str) -> None:
    imported = importlib.import_module(module)
    assert imported is not None
    assert importlib.metadata.version(distribution)
