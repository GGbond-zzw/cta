from __future__ import annotations

from pathlib import Path

from china_cta.runtime_paths import (
    DEFAULT_RQALPHA_BUNDLE_PATH,
    get_rqalpha_bundle_path,
)


def test_rqalpha_bundle_path_defaults_to_project_data(monkeypatch) -> None:
    monkeypatch.delenv("CTA_RQALPHA_BUNDLE_PATH", raising=False)

    assert get_rqalpha_bundle_path() == DEFAULT_RQALPHA_BUNDLE_PATH


def test_rqalpha_bundle_path_accepts_machine_local_override(monkeypatch) -> None:
    configured = Path("C:/market-data/.rqalpha/bundle")
    monkeypatch.setenv("CTA_RQALPHA_BUNDLE_PATH", str(configured))

    assert get_rqalpha_bundle_path() == configured
