"""Focused tests for the minimal Wesen lab workflow."""

from __future__ import annotations

import json
from configparser import ConfigParser
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from Wesen.defaults import CONFIG_DEFAULTS
from Wesen.gui.text import format_probability_bars
from Wesen.lab import (
    LabInstrumentation,
    SourceMetric,
    WinProbabilityWeights,
    energy_crossings,
    estimate_win_probabilities,
    load_experiment,
    load_simulation_config,
    main,
    summarize_run,
)
from Wesen.replay.recorder import ReplayRecorder
from Wesen.world import World


def write_wesen_config(path: Path, sources: str = "WindlePoons") -> None:
    """Write a small non-GUI config using the existing INI structure."""
    values = deepcopy(CONFIG_DEFAULTS)
    values["gui"]["enable"] = False
    values["world"]["length"] = 12
    values["wesen"].update(
        {"sources": sources, "count": 1, "energy": 100, "maxage": 100}
    )
    values["food"]["count"] = 0
    parser = ConfigParser()
    for section, section_values in values.items():
        parser[section] = {
            name: str(value) for name, value in section_values.items()
        }
    with path.open("w", encoding="utf-8") as stream:
        parser.write(stream)


def write_experiment(
    path: Path,
    config_path: Path,
    *,
    weights: str | None = None,
) -> None:
    """Write a minimal experiment YAML with optional custom weight fields."""
    weight_lines = (
        weights
        or """\
      energy: 1.0
      food_distance: -0.5
      enemy_count: -0.4
      enemy_strength: -0.8"""
    )
    path.write_text(
        f"""\
name: test-run
simulation:
  config_file: {config_path.name}
  max_turns: 1
win_probability:
  weights:
{weight_lines}
""",
        encoding="utf-8",
    )


def metric(
    source: str,
    *,
    energy: float = 0.0,
    food_distance: float = 0.0,
    enemy_count: int = 0,
    enemy_strength: float = 0.0,
) -> SourceMetric:
    """Build one active synthetic source metric for estimator tests."""
    return {
        "turn": 1,
        "source": source,
        "population": 1,
        "energy": energy,
        "food_distance": food_distance,
        "enemy_count": enemy_count,
        "enemy_strength": enemy_strength,
        "probability": 0.0,
    }


def test_experiment_yaml_is_validated_with_required_weights(tmp_path: Path) -> None:
    """Accept valid YAML and reject missing, nonnumeric, or missing-file data."""
    config_path = tmp_path / "wesen.conf"
    experiment_path = tmp_path / "experiment.yaml"
    write_wesen_config(config_path)
    write_experiment(experiment_path, config_path)

    experiment = load_experiment(experiment_path)

    assert experiment.name == "test-run"
    assert experiment.simulation.config_file == config_path
    assert experiment.win_probability.weights.energy == 1.0

    write_experiment(
        experiment_path,
        config_path,
        weights="""\
      energy: 1.0
      food_distance: -0.5
      enemy_count: -0.4""",
    )
    with pytest.raises(ValidationError, match="enemy_strength"):
        load_experiment(experiment_path)

    write_experiment(
        experiment_path,
        config_path,
        weights="""\
      energy: wrong
      food_distance: -0.5
      enemy_count: -0.4
      enemy_strength: -0.8""",
    )
    with pytest.raises(ValidationError, match="weights must be numbers"):
        load_experiment(experiment_path)

    config_path.unlink()
    with pytest.raises(ValidationError, match="Path does not point to a file"):
        load_experiment(experiment_path)


def test_existing_simulation_config_rejects_values_that_cannot_start(
    tmp_path: Path,
) -> None:
    """Reject a parsed existing config with no initial Wesen population."""
    config_path = tmp_path / "wesen.conf"
    write_wesen_config(config_path)
    text = config_path.read_text(encoding="utf-8")
    config_path.write_text(text.replace("count = 1", "count = 0", 1))

    with pytest.raises(ValueError, match="positive Wesen count"):
        load_simulation_config(config_path)


def test_each_required_metric_affects_estimator_score() -> None:
    """Give each required metric sole weight and observe its ranking effect."""
    metric_values: dict[str, int | float] = {
        "energy": 10.0,
        "food_distance": 4.0,
        "enemy_count": 3,
        "enemy_strength": 8.0,
    }
    for name, value in metric_values.items():
        first = metric("A")
        second = metric("B")
        first[name] = value  # type: ignore[literal-required]
        weights = dict.fromkeys(metric_values, 0.0)
        weights[name] = 1.0

        probabilities = estimate_win_probabilities(
            {"A": first, "B": second}, weights
        )

        assert probabilities["A"] > probabilities["B"]


def test_estimator_is_bounded_normalized_ranked_and_degenerate_safe() -> None:
    """Rank an obvious source and safely normalize tied metric inputs."""
    weights = {
        "energy": 1.0,
        "food_distance": -1.0,
        "enemy_count": -1.0,
        "enemy_strength": -1.0,
    }
    stronger = metric(
        "strong",
        energy=100,
        food_distance=1,
        enemy_count=1,
        enemy_strength=10,
    )
    weaker = metric(
        "weak",
        energy=10,
        food_distance=10,
        enemy_count=8,
        enemy_strength=100,
    )

    probabilities = estimate_win_probabilities(
        {"strong": stronger, "weak": weaker}, weights
    )
    tied = estimate_win_probabilities({"A": metric("A"), "B": metric("B")}, weights)

    assert probabilities["strong"] > probabilities["weak"]
    assert all(0.0 <= value <= 1.0 for value in probabilities.values())
    assert sum(probabilities.values()) == pytest.approx(1.0)
    assert tied == pytest.approx({"A": 0.5, "B": 0.5})


def world_info() -> dict[str, object]:
    """Return a small two-source world config for instrumentation tests."""
    config: dict[str, object] = deepcopy(CONFIG_DEFAULTS)
    config["world"] = {"length": 12}
    config["wesen"] = {
        "sources": ["Dwarf", "WindlePoons"],
        "count": 0,
        "energy": 100,
        "maxage": 100,
    }
    config["food"] = {
        "count": 0,
        "energy": 10,
        "maxamount": 1000,
        "maxage": 100,
        "growrate": 0.0,
        "seedrate": 0.0,
    }
    return config


def test_semantic_attacks_deaths_and_source_metrics_are_recorded(
    tmp_path: Path,
) -> None:
    """Capture an attributed attack/death and compact aggregate metrics."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    world = World(world_info())
    lab = LabInstrumentation(
        run_dir,
        ["Dwarf", "WindlePoons"],
        WinProbabilityWeights(
            energy=1.0,
            food_distance=-0.5,
            enemy_count=-0.4,
            enemy_strength=-0.8,
        ),
        max_turns=10,
    )
    recorder = ReplayRecorder(run_dir / "replay.jsonl", semantic_sink=lab)
    world.setRecorder(recorder)
    recorder.start(world)
    info = world.infoAllWorld["wesen"].copy()
    info.update({"position": [2, 2], "source": "Dwarf", "energy": 100})
    attacker = world.AddObject(info)
    info.update({"source": "WindlePoons", "energy": 10})
    target = world.AddObject(info)
    attacker.time = 100
    world.turns = 1

    assert attacker.Attack(target.sim_id)
    lab.record_metrics(world)
    lab.finish(world)
    recorder.close()
    lab.close()

    events = [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text().splitlines()
    ]
    metrics = [
        json.loads(line)
        for line in (run_dir / "metrics.jsonl").read_text().splitlines()
    ]
    assert events[0] == {
        "attacker_source": "Dwarf",
        "event": "attack",
        "target_source": "WindlePoons",
        "turn": 1,
    }
    assert events[1]["dead_source"] == "WindlePoons"
    assert events[1]["killer_source"] == "Dwarf"
    dwarf = next(record for record in metrics if record["source"] == "Dwarf")
    rabbit = next(record for record in metrics if record["source"] == "WindlePoons")
    assert dwarf["population"] == 1
    assert dwarf["energy"] == 95.0
    assert rabbit["population"] == 0
    assert rabbit["energy"] == 0.0


def write_summary_run(run_dir: Path) -> None:
    """Write compact synthetic run data that exercises required summary text."""
    run_dir.mkdir()
    (run_dir / "result.json").write_text(
        json.dumps(
            {
                "winner": "Dwarf",
                "surviving_sources": ["Dwarf"],
                "total_turns": 9,
            }
        )
    )
    events = [
        {
            "event": "attack",
            "turn": 4,
            "attacker_source": "Dwarf",
            "target_source": "Rabbit",
        },
        {
            "event": "attack",
            "turn": 5,
            "attacker_source": "Dwarf",
            "target_source": "Rabbit",
        },
        {
            "event": "death",
            "turn": 4,
            "dead_source": "Rabbit",
            "killer_source": "Dwarf",
        },
        {
            "event": "death",
            "turn": 5,
            "dead_source": "Rabbit",
            "killer_source": "Dwarf",
        },
    ]
    (run_dir / "events.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events)
    )
    records = []
    for turn, dwarf_energy, rabbit_energy, rabbit_population in (
        (0, 10, 30, 2),
        (1, 20, 20, 1),
        (2, 30, 10, 0),
    ):
        records.extend(
            [
                metric_record(turn, "Dwarf", 2, dwarf_energy),
                metric_record(turn, "Rabbit", rabbit_population, rabbit_energy),
            ]
        )
    (run_dir / "metrics.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records)
    )


def metric_record(
    turn: int, source: str, population: int, energy: float
) -> dict[str, object]:
    """Build one complete JSON metric record for summary tests."""
    return {
        "turn": turn,
        "source": source,
        "population": population,
        "energy": energy,
        "food_distance": 1.0,
        "enemy_count": 1,
        "enemy_strength": 10.0,
        "probability": 0.5,
    }


def test_summary_reports_results_groups_phase_and_energy_crossings(
    tmp_path: Path,
) -> None:
    """Summarize without replaying state and include every required result."""
    run_dir = tmp_path / "summary-run"
    write_summary_run(run_dir)

    summary = summarize_run(run_dir)

    assert "Winner: Dwarf" in summary
    assert "Surviving sources: Dwarf" in summary
    assert "Deaths: 2" in summary
    assert "Attacks: 2" in summary
    assert "Dwarf: attacks=2, kills=2, deaths=0" in summary
    assert "Rabbit: 2 -> 2 -> 0" in summary
    assert "more than any other source" in summary
    assert "middle phase, between turns 4 and 6" in summary
    assert "Dwarf / Rabbit: turn 1" in summary


def test_crossings_and_gui_bar_preparation() -> None:
    """Handle equality crossings consistently and prepare visible GUI bars."""
    assert energy_crossings({0: 1, 1: 2, 2: 3}, {0: 3, 1: 2, 2: 1}) == [1]
    bars = format_probability_bars({"Dwarf": 0.6, "Rabbit": 0.4}, width=10)
    assert "Dwarf" in bars and "60%" in bars and "######" in bars
    assert "Rabbit" in bars and "40%" in bars and "####" in bars


def test_cli_run_invalid_config_and_existing_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Exercise valid run, clear invalid-config failure, and summary commands."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    config_path = tmp_path / "wesen.conf"
    experiment_path = tmp_path / "experiment.yaml"
    write_wesen_config(config_path)
    write_experiment(experiment_path, config_path)

    assert main(["run", str(experiment_path)]) == 0
    assert (tmp_path / "runs/test-run/replay.jsonl").is_file()
    assert (tmp_path / "runs/test-run/result.json").is_file()
    assert "Run saved to runs/test-run" in capsys.readouterr().out

    summary_dir = tmp_path / "existing"
    write_summary_run(summary_dir)
    assert main(["summary", str(summary_dir)]) == 0
    assert "Winner: Dwarf" in capsys.readouterr().out

    invalid_path = tmp_path / "invalid.yaml"
    write_experiment(
        invalid_path,
        config_path,
        weights="""\
      energy: 1.0""",
    )
    assert main(["run", str(invalid_path)]) == 2
    captured = capsys.readouterr()
    assert "enemy_strength" in captured.err
    assert "wesen-lab: error:" in captured.err
