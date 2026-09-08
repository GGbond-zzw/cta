"""Resolve machine-local paths used by command-line entry points and tests."""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RQALPHA_BUNDLE_PATH = (
    PROJECT_ROOT / "data" / "rqalpha_bundle_futures_smoke" / "bundle"
)


def get_rqalpha_bundle_path() -> Path:
    """Return the configured RQAlpha bundle without hard-coding a user path."""

    configured = os.getenv("CTA_RQALPHA_BUNDLE_PATH")
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_RQALPHA_BUNDLE_PATH
