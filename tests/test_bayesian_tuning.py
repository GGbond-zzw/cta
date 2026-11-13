"""Contracts for the Bayesian tuning search spaces."""

from __future__ import annotations

from typing import Any

from china_cta.research.bayesian_tuning import TUNING_SPECS


class _RecordingTrial:
    """Minimal stand-in for ``optuna.Trial`` that records the search space."""

    def __init__(self) -> None:
        self.suggested: dict[str, Any] = {}

    def suggest_int(self, name: str, low: int, high: int, *, step: int = 1, log: bool = False) -> int:
        self.suggested[name] = ("int", low, high)
        return int(low)

    def suggest_float(self, name: str, low: float, high: float, *, step: float | None = None, log: bool = False) -> float:
        self.suggested[name] = ("float", low, high)
        return float(low)

    def suggest_categorical(self, name: str, choices: list[Any]) -> Any:
        self.suggested[name] = ("categorical", tuple(choices))
        return choices[0]


def test_signal_scale_is_never_searched() -> None:
    for name, spec in TUNING_SPECS.items():
        trial = _RecordingTrial()
        spec.suggest(trial)
        assert "signal_scale" not in trial.suggested, name
        assert spec.fixed["signal_scale"] == spec.baseline["signal_scale"], name


def test_fixed_params_are_disjoint_and_cover_the_baseline() -> None:
    for name, spec in TUNING_SPECS.items():
        trial = _RecordingTrial()
        searched = set(spec.suggest(trial))
        assert not searched & set(spec.fixed), name
        assert searched | set(spec.fixed) == set(spec.baseline), name


def test_resolved_params_keep_the_baseline_scale() -> None:
    for name, spec in TUNING_SPECS.items():
        trial = _RecordingTrial()
        params = spec.resolve({**spec.suggest(trial), **spec.fixed})
        assert params["signal_scale"] == spec.baseline["signal_scale"], name
