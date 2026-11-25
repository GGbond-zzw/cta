"""Resolve machine-local paths used by command-line entry points and tests.

Resolution order, first hit wins:

1. an explicit command-line flag (every script owns its own flag);
2. the environment variable listed below;
3. ``config/local.json`` -- git-ignored, machine specific;
4. the project default.

Environment variables
---------------------
``CTA_RESEARCH_INPUT_DIR``   research inputs, default ``data/research_inputs/cta_alpha22``
``CTA_RESULTS_DIR``          results root, default ``results``
``CTA_RQALPHA_BUNDLE_PATH``  RQAlpha bundle, no default (stages 12/14/20/70 need it)
``CTA_RQDATA_CACHE_DIR``     RQData response cache, default ``data/cache/rqdata``
``CTA_LOCAL_CONFIG``         local config file, default ``config/local.json``
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESEARCH_INPUT_DIR = PROJECT_ROOT / "data" / "research_inputs" / "cta_alpha22"
DEFAULT_RESULTS_DIR = PROJECT_ROOT / "results"
DEFAULT_RQDATA_CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "rqdata"
DEFAULT_LOCAL_CONFIG = PROJECT_ROOT / "config" / "local.json"

_BUNDLE_HELP = (
    "Set CTA_RQALPHA_BUNDLE_PATH (or rqalpha_bundle in config/local.json) to a"
    " directory that holds futures.h5 and instruments.pk, or pass the matching"
    " command-line flag."
)


def local_config_path() -> Path:
    """Return the local, git-ignored configuration file path."""

    configured = os.getenv("CTA_LOCAL_CONFIG")
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_LOCAL_CONFIG


def load_local_config() -> dict[str, Any]:
    """Return ``config/local.json`` as a dict (empty when the file is absent)."""

    path = local_config_path()
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # pragma: no cover - operator error path
        raise RuntimeError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path} must contain a JSON object")
    return payload


def _setting(env_name: str, key: str) -> str | None:
    from_env = os.getenv(env_name)
    if from_env:
        return from_env
    value = load_local_config().get(key)
    if value in (None, ""):
        return None
    return str(value)


def _resolve(env_name: str, key: str, default: Path | None) -> Path | None:
    raw = _setting(env_name, key)
    if raw:
        return Path(raw).expanduser()
    return default


def get_research_input_dir() -> Path:
    """Directory holding continuous_prices/contract_snapshots/universe/..."""

    resolved = _resolve("CTA_RESEARCH_INPUT_DIR", "research_inputs", DEFAULT_RESEARCH_INPUT_DIR)
    assert resolved is not None
    return resolved


def get_results_dir(*parts: str) -> Path:
    """Results root (optionally joined with ``parts``); never written by the repo."""

    root = _resolve("CTA_RESULTS_DIR", "results", DEFAULT_RESULTS_DIR)
    assert root is not None
    return root.joinpath(*parts) if parts else root


def get_rqdata_cache_dir() -> Path:
    """Local cache of raw RQData responses."""

    resolved = _resolve("CTA_RQDATA_CACHE_DIR", "rqdata_cache", DEFAULT_RQDATA_CACHE_DIR)
    assert resolved is not None
    return resolved


def get_rqalpha_bundle_path() -> Path | None:
    """Configured RQAlpha bundle, or ``None`` when this machine has none."""

    return _resolve("CTA_RQALPHA_BUNDLE_PATH", "rqalpha_bundle", None)


def require_rqalpha_bundle_path(purpose: str) -> Path:
    """Return the bundle path or raise an actionable error."""

    bundle = get_rqalpha_bundle_path()
    if bundle is None:
        raise RuntimeError(f"{purpose} needs an RQAlpha bundle. {_BUNDLE_HELP}")
    if not (bundle / "futures.h5").is_file():
        raise RuntimeError(f"{bundle} does not contain futures.h5. {_BUNDLE_HELP}")
    return bundle


def describe_paths() -> dict[str, str]:
    """Human readable snapshot used by ``scripts/00_doctor.py``."""

    bundle = get_rqalpha_bundle_path()
    return {
        "project": str(PROJECT_ROOT),
        "research_inputs": str(get_research_input_dir()),
        "results": str(get_results_dir()),
        "rqdata_cache": str(get_rqdata_cache_dir()),
        "rqalpha_bundle": str(bundle) if bundle is not None else "",
        "local_config": str(local_config_path()),
    }
