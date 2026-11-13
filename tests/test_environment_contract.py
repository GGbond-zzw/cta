from __future__ import annotations

import importlib
import importlib.metadata
import sys

import pytest


# Packages the analysis pipeline always needs.
CORE_PACKAGES = {
    "numpy": "numpy",
    "pandas": "pandas",
    "scipy": "scipy",
    "matplotlib": "matplotlib",
    "pyarrow": "pyarrow",
    "PyYAML": "yaml",
    "pytest": "pytest",
}

# Vendor SDKs: needed only for data acquisition (stage 0) and the legacy
# RQAlpha Plus adapter, and they are unavailable on some locked-down hosts
# (Smart App Control blocks their native modules), so they are optional here.
VENDOR_PACKAGES = {
    "rqdatac": "rqdatac",
    "rqsdk": "rqsdk",
    "rqalpha-plus": "rqalpha_plus",
    "rqfactor": "rqfactor",
}


def test_project_runs_on_python_311_or_newer() -> None:
    assert sys.version_info[:2] >= (3, 11)


@pytest.mark.parametrize(("distribution", "module"), CORE_PACKAGES.items())
def test_core_package_is_installed(distribution: str, module: str) -> None:
    imported = importlib.import_module(module)
    assert imported is not None
    assert importlib.metadata.version(distribution)


@pytest.mark.parametrize(("distribution", "module"), VENDOR_PACKAGES.items())
def test_vendor_package_is_installed(distribution: str, module: str) -> None:
    pytest.importorskip(
        module,
        reason=f"{distribution} is only needed for data acquisition / the legacy adapter",
    )
    assert importlib.metadata.version(distribution)
