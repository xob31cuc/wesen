"""Run one configured Wesen experiment and summarize its compact lab data."""

from __future__ import annotations

import json
import math
import shutil
import sys
from argparse import ArgumentParser
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from configparser import Error as ConfigError
from copy import deepcopy
from pathlib import Path
from statistics import fmean
from typing import IO, Literal, TypedDict, cast

import deal
import yaml
from numpy.random import seed as set_random_seed
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FilePath,
    ValidationError,
    field_validator,
)

from .configed import ConfigEd
from .defaults import CONFIG_DEFAULTS, ConfigValue
from .loader import _enableCustomSourcesFolder
from .wesend import Wesend
from .world import World

type EstimatorMetric = Literal[
    "energy", "food_distance", "enemy_count", "enemy_strength"
]

REQUIRED_METRICS: tuple[EstimatorMetric, ...] = (
    "energy",
    "food_distance",
    "enemy_count",
    "enemy_strength",
)


class WinProbabilityWeights(BaseModel):
    """Hold the four finite manual weights required by the estimator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    energy: float
    food_distance: float
    enemy_count: float
    enemy_strength: float

    @field_validator("*", mode="before")
    @classmethod
    def weights_are_numbers(cls, value: object) -> object:
        """Reject strings and booleans instead of coercing them to weights."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("weights must be numbers")
        if not math.isfinite(float(value)):
            raise ValueError("weights must be finite")
        return value

    def values_by_metric(self) -> dict[str, float]:
        """Return weights keyed by the corresponding source metric."""
        return {
            "energy": self.energy,
            "food_distance": self.food_distance,
            "enemy_count": self.enemy_count,
            "enemy_strength": self.enemy_strength,
        }


class WinProbabilityConfig(BaseModel):
    """Configure the manual source win-probability estimator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    weights: WinProbabilityWeights


class SimulationExperiment(BaseModel):
    """Reference an existing Wesen config and bound the experiment duration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    config_file: FilePath
    max_turns: int = Field(default=10_000, gt=0, strict=True)
    random_seed: int | None = Field(
        default=None,
        ge=0,
        le=2**32 - 1,
        strict=True,
    )


class ExperimentConfig(BaseModel):
    """Describe one named, finite Wesen lab run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$",
    )
    simulation: SimulationExperiment
    win_probability: WinProbabilityConfig


class SourceMetric(TypedDict):
    """Store one turn's compact aggregate measurements for one source."""

    turn: int
    source: str
    population: int
    energy: float
    food_distance: float
    enemy_count: int
    enemy_strength: float
    probability: float


def load_experiment(path: Path | str) -> ExperimentConfig:
    """Load YAML at ``path`` and validate its minimal experiment schema."""
    experiment_path = Path(path)
    raw = yaml.safe_load(experiment_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("experiment YAML must contain a mapping")
    data = cast(dict[str, object], raw)
    simulation = data.get("simulation")
    if isinstance(simulation, dict):
        simulation_data = cast(dict[str, object], simulation).copy()
        config_file = simulation_data.get("config_file")
        if isinstance(config_file, str):
            config_path = Path(config_file)
            if not config_path.is_absolute():
                config_path = experiment_path.parent / config_path
            simulation_data["config_file"] = config_path.resolve()
        data = data.copy()
        data["simulation"] = simulation_data
    return ExperimentConfig.model_validate(data)


def _normalization_values(values: Mapping[str, float]) -> dict[str, float]:
    """Min-max normalize values, using 0.5 when every value is equal."""
    low = min(values.values())
    high = max(values.values())
    if high == low:
        return dict.fromkeys(values, 0.5)
    scale = high - low
    return {source: (value - low) / scale for source, value in values.items()}


def _estimator_input_is_valid(
    metrics: Mapping[str, SourceMetric], weights: Mapping[str, float]
) -> bool:
    """Return whether estimator input has all finite required values."""
    return (
        bool(metrics)
        and set(weights) == set(REQUIRED_METRICS)
        and all(math.isfinite(value) for value in weights.values())
        and all(
            math.isfinite(float(metric[name]))
            for metric in metrics.values()
            for name in REQUIRED_METRICS
        )
    )


def _probabilities_are_valid(result: Mapping[str, float]) -> bool:
    """Return whether probabilities are finite, bounded, and normalized."""
    return (
        bool(result)
        and all(
            math.isfinite(value) and 0.0 <= value <= 1.0 for value in result.values()
        )
        and math.isclose(sum(result.values()), 1.0, abs_tol=1e-9)
    )


@deal.pre(_estimator_input_is_valid)
@deal.post(_probabilities_are_valid)
def estimate_win_probabilities(
    metrics: Mapping[str, SourceMetric], weights: Mapping[str, float]
) -> dict[str, float]:
    """Estimate normalized source win probabilities from current metrics.

    Each metric is min-max normalized across active sources. A tied metric is
    assigned 0.5 for every source. Manual weighted scores are converted with a
    numerically stable softmax.
    """
    normalized = {
        name: _normalization_values(
            {source: float(metric[name]) for source, metric in metrics.items()}
        )
        for name in REQUIRED_METRICS
    }
    scores = {
        source: sum(
            weights[name] * normalized[name][source] for name in REQUIRED_METRICS
        )
        for source in metrics
    }
    maximum = max(scores.values())
    exponentials = {
        source: math.exp(score - maximum) for source, score in scores.items()
    }
    total = sum(exponentials.values())
    return {source: value / total for source, value in exponentials.items()}


def _source_config_is_valid(config: Mapping[str, object]) -> bool:
    """Return whether essential existing Wesen config values can start a run."""
    world = config.get("world")
    wesen = config.get("wesen")
    if not isinstance(world, dict) or not isinstance(wesen, dict):
        return False
    sources = wesen.get("sources")
    source_names = (
        [entry.strip() for entry in sources.split(",")]
        if isinstance(sources, str)
        else sources
    )
    return (
        isinstance(world.get("length"), int)
        and world["length"] > 0
        and isinstance(wesen.get("count"), int)
        and wesen["count"] > 0
        and isinstance(source_names, list)
        and bool(source_names)
        and all(isinstance(source, str) and source for source in source_names)
    )


def load_simulation_config(path: Path) -> dict[str, object]:
    """Load an existing Wesen INI config and fill its standard defaults."""
    try:
        configured = ConfigEd(str(path)).getConfig()
    except (ConfigError, ValueError) as error:
        raise ValueError(f"invalid simulation config {path}: {error}") from error
    config = cast(dict[str, object], deepcopy(CONFIG_DEFAULTS))
    for section, values in configured.items():
        section_values = cast(dict[str, ConfigValue], config[section])
        section_values.update(values)
    if not _source_config_is_valid(config):
        raise ValueError(
            "simulation config needs a positive world length, positive Wesen "
            "count, and at least one source"
        )
    config.update(
        {
            "resume": False,
            "record_replay": None,
            "replay": None,
            "verify_replay": None,
        }
    )
    return config


def _chebyshev_distance(first: list[int], second: list[int]) -> int:
    """Return the maximum-axis distance used by Wesen range checks."""
    return max(abs(first[0] - second[0]), abs(first[1] - second[1]))


class LabInstrumentation:
    """Persist required semantic events, source metrics, and final metadata."""

    def __init__(
        self,
        run_dir: Path,
        sources: Sequence[str],
        weights: WinProbabilityWeights,
        max_turns: int,
    ) -> None:
        """Open compact run outputs for one configured experiment."""
        self.run_dir = run_dir
        self.sources = tuple(sorted(sources))
        self.weights = weights.values_by_metric()
        self.max_turns = max_turns
        self.finished = False
        self.closed = False
        self._events: IO[str] = (run_dir / "events.jsonl").open(
            "w", encoding="utf-8", buffering=1
        )
        self._metrics: IO[str] = (run_dir / "metrics.jsonl").open(
            "w", encoding="utf-8", buffering=1
        )

    def event(self, event_type: str, **data: object) -> None:
        """Write only attacks, deaths, and terminal run meaning as JSON Lines."""
        if event_type not in {"attack", "death", "run_end"}:
            return
        turn = data.get("turn")
        if not isinstance(turn, int) or turn < 0:
            raise ValueError("semantic event turns must be non-negative integers")
        record = {"event": event_type, **data}
        self._events.write(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        )

    def record_metrics(self, world: World) -> None:
        """Record source-level aggregate metrics for the current world turn.

        Energy is total living-source energy. Food distance is the mean nearest
        food Chebyshev distance for living members. Enemy count and strength are
        the total population and total energy of all other living sources.
        """
        wesens = [obj for obj in world.objects.values() if obj.objectType == "wesen"]
        foods = [obj for obj in world.objects.values() if obj.objectType == "food"]
        members = {
            source: [obj for obj in wesens if obj.source == source]
            for source in self.sources
        }
        total_population = len(wesens)
        total_energy = sum(float(obj.energy) for obj in wesens)
        records: dict[str, SourceMetric] = {}
        for source in self.sources:
            source_members = members[source]
            population = len(source_members)
            energy = sum(float(obj.energy) for obj in source_members)
            if not source_members:
                food_distance = 0.0
            elif not foods:
                food_distance = float(world.infoAllWorld["world"]["length"])
            else:
                food_distance = fmean(
                    min(
                        _chebyshev_distance(member.position, food.position)
                        for food in foods
                    )
                    for member in source_members
                )
            records[source] = {
                "turn": world.turns,
                "source": source,
                "population": population,
                "energy": energy,
                "food_distance": food_distance,
                "enemy_count": total_population - population,
                "enemy_strength": total_energy - energy,
                "probability": 0.0,
            }
        active = {
            source: record
            for source, record in records.items()
            if record["population"] > 0
        }
        probabilities = (
            estimate_win_probabilities(active, self.weights) if active else {}
        )
        for source, record in records.items():
            record["probability"] = probabilities.get(source, 0.0)
            if record["population"] < 0 or record["turn"] < 0:
                raise ValueError("metric turns and populations must be non-negative")
            self._metrics.write(
                json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            )
        world.win_probabilities = probabilities

    def should_stop(self, world: World) -> bool:
        """Stop at the turn limit or once at most one source remains alive."""
        active_sources = {
            obj.source for obj in world.objects.values() if obj.objectType == "wesen"
        }
        return world.turns >= self.max_turns or len(active_sources) <= 1

    def _final_source_values(self, world: World) -> dict[str, tuple[int, float]]:
        """Return final population and energy keyed by configured source."""
        values = {source: (0, 0.0) for source in self.sources}
        populations: Counter[str] = Counter()
        energies: Counter[str] = Counter()
        for obj in world.objects.values():
            if obj.objectType == "wesen":
                populations[obj.source] += 1
                energies[obj.source] += obj.energy
        for source in self.sources:
            values[source] = (populations[source], float(energies[source]))
        return values

    def finish(self, world: World) -> None:
        """Write winner, survivors, and terminal semantic event exactly once."""
        if self.finished:
            return
        final_values = self._final_source_values(world)
        survivors = sorted(
            source
            for source, (population, _energy) in final_values.items()
            if population > 0
        )
        if not survivors:
            winner: str | None = None
        else:
            winner = min(
                survivors,
                key=lambda source: (
                    -final_values[source][0],
                    -final_values[source][1],
                    source,
                ),
            )
        self.event(
            "run_end",
            turn=world.turns,
            winner=winner,
            surviving_sources=survivors,
        )
        result = {
            "winner": winner,
            "surviving_sources": survivors,
            "total_turns": world.turns,
        }
        (self.run_dir / "result.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.finished = True

    def close(self) -> None:
        """Close event and metric streams exactly once."""
        if not self.closed:
            self._events.close()
            self._metrics.close()
            self.closed = True


def _configured_sources(config: Mapping[str, object]) -> list[str]:
    """Return source names from a validated existing simulation config."""
    wesen = cast(dict[str, object], config["wesen"])
    sources = wesen["sources"]
    if isinstance(sources, str):
        return [source.strip() for source in sources.split(",")]
    return cast(list[str], sources).copy()


def run_experiment(
    experiment_path: Path | str, runs_root: Path | str = "runs"
) -> Path:
    """Run one validated experiment and return its newly created run directory."""
    path = Path(experiment_path)
    experiment = load_experiment(path)
    run_dir = Path(runs_root) / experiment.name
    if run_dir.exists():
        raise ValueError(f"run directory already exists: {run_dir}")
    run_dir.mkdir(parents=True)
    shutil.copyfile(path, run_dir / "experiment.yaml")
    config = load_simulation_config(experiment.simulation.config_file)
    replay_path = run_dir / "replay.jsonl"
    config["record_replay"] = str(replay_path)
    instrumentation = LabInstrumentation(
        run_dir=run_dir,
        sources=_configured_sources(config),
        weights=experiment.win_probability.weights,
        max_turns=experiment.simulation.max_turns,
    )
    _enableCustomSourcesFolder()
    if experiment.simulation.random_seed is not None:
        set_random_seed(experiment.simulation.random_seed)
    try:
        runner = Wesend(config, lab=instrumentation)
        runner.start()
    except BaseException:
        instrumentation.close()
        raise
    return run_dir


def _read_json_object(path: Path) -> dict[str, object]:
    """Read and validate one JSON object from ``path``."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return cast(dict[str, object], value)


def _read_json_lines(path: Path) -> list[dict[str, object]]:
    """Read JSON object records from a JSON Lines file."""
    records: list[dict[str, object]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number} must contain a JSON object")
        records.append(cast(dict[str, object], value))
    return records


def _integer_field(record: Mapping[str, object], name: str) -> int:
    """Read one required non-Boolean integer JSON field."""
    value = record.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"field {name!r} must be an integer")
    return value


def _number_field(record: Mapping[str, object], name: str) -> float:
    """Read one required finite non-Boolean numeric JSON field."""
    value = record.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"field {name!r} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"field {name!r} must be finite")
    return result


def _string_field(record: Mapping[str, object], name: str) -> str:
    """Read one required nonempty string JSON field."""
    value = record.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"field {name!r} must be a nonempty string")
    return value


def _source_metric_records(path: Path) -> list[SourceMetric]:
    """Read typed source metric records needed by the textual summary."""
    result: list[SourceMetric] = []
    for record in _read_json_lines(path):
        try:
            metric: SourceMetric = {
                "turn": _integer_field(record, "turn"),
                "source": _string_field(record, "source"),
                "population": _integer_field(record, "population"),
                "energy": _number_field(record, "energy"),
                "food_distance": _number_field(record, "food_distance"),
                "enemy_count": _integer_field(record, "enemy_count"),
                "enemy_strength": _number_field(record, "enemy_strength"),
                "probability": _number_field(record, "probability"),
            }
        except ValueError as error:
            raise ValueError(f"invalid source metric in {path}: {error}") from error
        if metric["turn"] < 0 or metric["population"] < 0 or not metric["source"]:
            raise ValueError(f"invalid source metric in {path}")
        result.append(metric)
    return result


def _crossing_input_is_valid(
    winner: Mapping[int, float], other: Mapping[int, float]
) -> bool:
    """Return whether energy-series turns and values are valid."""
    return (
        all(turn >= 0 for turn in winner)
        and all(turn >= 0 for turn in other)
        and all(
            math.isfinite(value) for value in (*winner.values(), *other.values())
        )
    )


@deal.pre(_crossing_input_is_valid)
def energy_crossings(
    winner: Mapping[int, float], other: Mapping[int, float]
) -> list[int]:
    """Return recorded turns where two energy-series differences change sign."""
    turns = sorted(set(winner) & set(other))
    crossings: list[int] = []
    for before_turn, after_turn in zip(turns, turns[1:], strict=False):
        before = winner[before_turn] - other[before_turn]
        after = winner[after_turn] - other[after_turn]
        if before < 0 <= after or before > 0 >= after:
            crossings.append(after_turn)
    return crossings


def _phase(turn: int, total_turns: int) -> tuple[str, int, int]:
    """Return the fixed-third phase name and inclusive turn range."""
    first_end = max(1, total_turns // 3)
    middle_end = max(first_end, (2 * total_turns) // 3)
    if turn <= first_end:
        return ("early", 1, first_end)
    if turn <= middle_end:
        return ("middle", first_end + 1, middle_end)
    return ("late", middle_end + 1, total_turns)


def _notable_results(
    winner: str | None,
    deaths: Sequence[dict[str, object]],
    total_turns: int,
) -> list[str]:
    """Build deterministic source-kill and dominant-phase observations."""
    attributed = [
        event for event in deaths if isinstance(event.get("killer_source"), str)
    ]
    if not attributed:
        return ["No deaths were attributed to a source."]
    kills = Counter(str(event["killer_source"]) for event in attributed)
    leader = min(kills, key=lambda source: (-kills[source], source))
    subject = f"The winning source {leader}" if leader == winner else leader
    lines = [
        f"{subject} caused {kills[leader]} enemy deaths, more than any other source."
    ]
    leader_deaths = [
        event for event in attributed if event["killer_source"] == leader
    ]
    phase_counts = Counter(
        _phase(_integer_field(event, "turn"), total_turns)[0]
        for event in leader_deaths
    )
    dominant = min(
        phase_counts,
        key=lambda name: (
            -phase_counts[name],
            ("early", "middle", "late").index(name),
        ),
    )
    representative_turn = next(
        _integer_field(event, "turn")
        for event in leader_deaths
        if _phase(_integer_field(event, "turn"), total_turns)[0] == dominant
    )
    _name, start, end = _phase(representative_turn, total_turns)
    lines.append(
        f"Most of {leader}'s kills occurred in the {dominant} phase, between "
        f"turns {start} and {end}."
    )
    return lines


def summarize_run(run_dir: Path | str) -> str:
    """Summarize saved events, source metrics, and result metadata as text."""
    directory = Path(run_dir)
    result = _read_json_object(directory / "result.json")
    events = _read_json_lines(directory / "events.jsonl")
    metrics = _source_metric_records(directory / "metrics.jsonl")
    winner_value = result.get("winner")
    winner = winner_value if isinstance(winner_value, str) else None
    survivors_value = result.get("surviving_sources")
    survivors = (
        [str(source) for source in survivors_value]
        if isinstance(survivors_value, list)
        else []
    )
    total_turns = _integer_field(result, "total_turns")
    attacks = [event for event in events if event.get("event") == "attack"]
    deaths = [event for event in events if event.get("event") == "death"]
    attack_counts = Counter(
        _string_field(event, "attacker_source") for event in attacks
    )
    death_counts = Counter(_string_field(event, "dead_source") for event in deaths)
    kill_counts = Counter(
        str(event["killer_source"])
        for event in deaths
        if isinstance(event.get("killer_source"), str)
    )
    by_source: dict[str, list[SourceMetric]] = defaultdict(list)
    for metric in metrics:
        by_source[metric["source"]].append(metric)
    sources = sorted(
        set(by_source) | set(attack_counts) | set(death_counts) | set(kill_counts)
    )

    lines = [
        f"Winner: {winner or 'None'}",
        f"Surviving sources: {', '.join(survivors) if survivors else 'None'}",
        f"Total turns: {total_turns}",
        f"Deaths: {len(deaths)}",
    ]
    if death_counts:
        lines.append(
            "Deaths by source: "
            + ", ".join(
                f"{source} {death_counts[source]}" for source in sorted(death_counts)
            )
        )
    lines.append(f"Attacks: {len(attacks)}")
    if attack_counts:
        lines.append(
            "Attacks by source: "
            + ", ".join(
                f"{source} {attack_counts[source]}"
                for source in sorted(attack_counts)
            )
        )

    lines.extend(["", "Population development:"])
    for source in sources:
        records = sorted(by_source.get(source, []), key=lambda item: item["turn"])
        if records:
            populations = [record["population"] for record in records]
            lines.append(
                f"  {source}: {populations[0]} -> {max(populations)} -> "
                f"{populations[-1]} (start -> peak -> final)"
            )

    lines.extend(["", "Grouped source statistics:"])
    for source in sources:
        records = by_source.get(source, [])
        final_population = records[-1]["population"] if records else 0
        mean_energy = (
            fmean(record["energy"] for record in records) if records else 0.0
        )
        peak_population = max(
            (record["population"] for record in records), default=0
        )
        lines.append(
            f"  {source}: attacks={attack_counts[source]}, "
            f"kills={kill_counts[source]}, "
            f"deaths={death_counts[source]}, final_population={final_population}, "
            f"peak_population={peak_population}, mean_total_energy={mean_energy:.2f}"
        )

    lines.extend(["", "Notable events:"])
    if deaths:
        first_death = min(deaths, key=lambda event: _integer_field(event, "turn"))
        lines.append(
            f"  First death: {_string_field(first_death, 'dead_source')} "
            f"at turn {_integer_field(first_death, 'turn')}."
        )
    else:
        lines.append("  No deaths were recorded.")
    lines.extend(
        f"  {line}" for line in _notable_results(winner, deaths, total_turns)
    )

    lines.extend(["", "Energy crossings:"])
    if winner is None or winner not in by_source:
        lines.append("  No winner energy curve is available.")
    else:
        winner_energy = {
            record["turn"]: record["energy"] for record in by_source[winner]
        }
        crossing_found = False
        for source in sources:
            if source == winner or source not in by_source:
                continue
            other_energy = {
                record["turn"]: record["energy"] for record in by_source[source]
            }
            crossings = energy_crossings(winner_energy, other_energy)
            if crossings:
                crossing_found = True
                turn_label = "turn" if len(crossings) == 1 else "turns"
                lines.append(
                    f"  {winner} / {source}: {turn_label} "
                    + ", ".join(str(turn) for turn in crossings)
                )
        if not crossing_found:
            lines.append("  No energy crossings were recorded.")
    return "\n".join(lines)


def _parser() -> ArgumentParser:
    """Build the two-command ``wesen-lab`` argument parser."""
    parser = ArgumentParser(prog="wesen-lab")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run one YAML experiment")
    run.add_argument("experiment", type=Path)
    summary = commands.add_parser("summary", help="summarize one run directory")
    summary.add_argument("run_directory", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Execute exactly the required ``run`` or ``summary`` lab command."""
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "run":
            run_dir = run_experiment(arguments.experiment)
            print(f"Run saved to {run_dir}")
        else:
            print(summarize_run(arguments.run_directory))
    except (
        ImportError,
        OSError,
        ValueError,
        ValidationError,
        yaml.YAMLError,
    ) as error:
        print(f"wesen-lab: error: {error}", file=sys.stderr)
        return 2
    return 0
