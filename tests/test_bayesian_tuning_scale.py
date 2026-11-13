"""Contracts for the scale-tuned search space written to ``results/tuning/scale_tuned``."""

from __future__ import annotations

from typing import Any

from china_cta.research import bayesian_tuning as bt


class _RecordingTrial:
    """Minimal stand-in for ``optuna.Trial`` that records the search space."""

    def __init__(self) -> None:
        self.suggested: dict[str, Any] = {}
        self.user_attrs: dict[str, Any] = {}

    def suggest_int(self, name: str, low: int, high: int, *, step: int = 1, log: bool = False) -> int:
        self.suggested[name] = ("int", low, high)
        return int(low)

    def suggest_float(self, name: str, low: float, high: float, *, step: float | None = None, log: bool = False) -> float:
        self.suggested[name] = ("float", low, high)
        return float(low)

    def suggest_categorical(self, name: str, choices: list[Any]) -> Any:
        self.suggested[name] = ("categorical", tuple(choices))
        return choices[0]

    def set_user_attr(self, key: str, value: Any) -> None:
        self.user_attrs[key] = value


def test_scale_tuned_specs_search_the_historical_range() -> None:
    assert set(bt.SCALE_TUNED_SPECS) == set(bt.TUNING_SPECS)
    for name, spec in bt.SCALE_TUNED_SPECS.items():
        assert spec.fixed == {}, name
        assert spec.scale_range == bt.SCALE_RANGES[name], name
        trial = _RecordingTrial()
        params = {**spec.suggest(trial), **bt._suggest_scale(trial, spec)}
        assert trial.suggested["signal_scale"] == ("float", *spec.scale_range), name
        assert set(params) == set(spec.baseline), name


def test_pinned_specs_do_not_suggest_the_scale() -> None:
    for name, spec in bt.TUNING_SPECS.items():
        trial = _RecordingTrial()
        assert bt._suggest_scale(trial, spec) == {}, name
        assert trial.suggested == {}, name


def test_tunable_baseline_keeps_or_drops_the_scale() -> None:
    for name in bt.TUNING_SPECS:
        tuned = bt._tunable_baseline(bt.SCALE_TUNED_SPECS[name])
        pinned = bt._tunable_baseline(bt.TUNING_SPECS[name])
        assert tuned["signal_scale"] == bt.TUNING_SPECS[name].baseline["signal_scale"], name
        assert "signal_scale" not in pinned, name


def test_validated_spec_selects_the_requested_set() -> None:
    for name in bt.TUNING_SPECS:
        assert bt._validated_spec(name) is bt.TUNING_SPECS[name]
        assert bt._validated_spec(name, tune_scale=True) is bt.SCALE_TUNED_SPECS[name]


def test_objective_forwards_the_tuned_scale(monkeypatch: Any) -> None:
    seen: dict[str, Any] = {}

    def fake_evaluate(name: str, params: dict[str, Any], inputs: Any, start: str, end: str) -> dict[str, Any]:
        seen.update(params)
        return {
            "observations": 20_000,
            "sharpe": 1.0,
            "annualized_net": 0.1,
            "annualized_vol": 0.1,
            "max_drawdown": -0.1,
            "turnover": 0.1,
            "ic": 0.01,
            "rank_ic": 0.01,
        }

    monkeypatch.setattr(bt, "evaluate_params", fake_evaluate)
    trial = _RecordingTrial()
    assert bt.objective(trial, "xsmom_252_21", {}, tune_scale=True) == 1.0
    assert seen["signal_scale"] == 0.5
    assert trial.user_attrs["constraint_ok"] is True
