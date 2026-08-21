"""Verify the local CTA runtime without reading or printing credentials."""

from __future__ import annotations

import importlib
import importlib.metadata
import sys


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


def main() -> int:
    print(f"Python: {sys.version.split()[0]}")
    print(f"Executable: {sys.executable}")
    if sys.version_info[:2] != (3, 11):
        print("Environment check failed: this project requires Python 3.11.")
        return 1

    failures: list[str] = []
    for distribution, module in REQUIRED_PACKAGES.items():
        try:
            importlib.import_module(module)
            installed_version = importlib.metadata.version(distribution)
        except (ImportError, importlib.metadata.PackageNotFoundError) as exc:
            failures.append(f"{distribution}: {exc}")
        else:
            print(f"{distribution}={installed_version}")

    if failures:
        print("Environment check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("CTA environment check succeeded!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
