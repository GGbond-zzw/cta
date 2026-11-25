from __future__ import annotations

import json
from pathlib import Path

import pytest

from china_cta.runtime_paths import (
    DEFAULT_RESEARCH_INPUT_DIR,
    get_research_input_dir,
    get_rqalpha_bundle_path,
    get_results_dir,
    require_rqalpha_bundle_path,
)


@pytest.fixture(autouse=True)
def _no_local_config(monkeypatch) -> None:
    monkeypatch.setenv("CTA_LOCAL_CONFIG", str(Path(__file__).parent / "no-such-local.json"))


def test_research_input_dir_defaults_to_project_data(monkeypatch) -> None:
    monkeypatch.delenv("CTA_RESEARCH_INPUT_DIR", raising=False)

    assert get_research_input_dir() == DEFAULT_RESEARCH_INPUT_DIR


def test_environment_variable_wins(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CTA_RESEARCH_INPUT_DIR", str(tmp_path / "inputs"))

    assert get_research_input_dir() == tmp_path / "inputs"


def test_local_config_override(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("CTA_RESEARCH_INPUT_DIR", raising=False)
    config = tmp_path / "local.json"
    config.write_text(json.dumps({"research_inputs": str(tmp_path / "from-json")}), encoding="utf-8")
    monkeypatch.setenv("CTA_LOCAL_CONFIG", str(config))

    assert get_research_input_dir() == tmp_path / "from-json"
    assert get_results_dir("tuning") == get_results_dir() / "tuning"


def test_bundle_is_optional_but_required_explicitly(monkeypatch) -> None:
    monkeypatch.delenv("CTA_RQALPHA_BUNDLE_PATH", raising=False)

    assert get_rqalpha_bundle_path() is None
    with pytest.raises(RuntimeError) as error:
        require_rqalpha_bundle_path("stage 70")
    assert "CTA_RQALPHA_BUNDLE_PATH" in str(error.value)


def test_bundle_override(monkeypatch, tmp_path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "futures.h5").write_bytes(b"")
    monkeypatch.setenv("CTA_RQALPHA_BUNDLE_PATH", str(bundle))

    assert get_rqalpha_bundle_path() == bundle
    assert require_rqalpha_bundle_path("stage 70") == bundle
