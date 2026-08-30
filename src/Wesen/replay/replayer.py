"""Validated checkpoint-and-delta replay playback without simulation logic."""

from __future__ import annotations

import hmac
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeGuard

from .events import ObjectPatch, ObjectState, ReplayDelta
from .hash import GENESIS_HASH, replay_event_hash, state_hash
from .recorder import SCHEMA_VERSION

if TYPE_CHECKING:
    from Wesen.world import World


class ReplayError(Exception):
    """Raised for malformed, unsupported, inconsistent, or exhausted replay data."""


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Summarize replay verification success or the first mismatch."""

    ok: bool
    frames: int
    turn: int | None = None
    expected: str | None = None
    actual: str | None = None
    message: str = ""


class Replayer:
    """Apply recorded state transitions directly to an inert restored world."""

    path: Path
    events: list[dict[str, Any]]
    header: dict[str, Any]
    initial_checkpoint: dict[str, Any]
    footer: dict[str, Any]
    transitions: list[dict[str, Any]]
    frames: list[dict[str, Any]]
    checkpoints: dict[int, dict[str, Any]]
    index: int

    def __init__(self, path: Path | str) -> None:
        """Load and structurally validate the replay event stream at ``path``."""
        self.path = Path(path)
        self.events = self._read_events()
        self._validate_common_fields()
        self._validate_hash_chain()
        self.header = self.events[0]
        self._validate_header()
        self.initial_checkpoint = self.events[1]
        self._validate_checkpoint(self.initial_checkpoint, initial=True)
        self.footer = self.events[-1]
        self._validate_footer()
        self.transitions = self.events[2:-1]
        self.frames = self.transitions
        self._validate_state_sequence()
        self.checkpoints = {
            event["turn"]: event
            for event in self.events
            if event["event"] == "checkpoint"
        }
        self.index = 0

    def _read_events(self) -> list[dict[str, Any]]:
        """Parse nonempty JSON object lines from the configured replay path."""
        events: list[dict[str, Any]] = []
        try:
            with self.path.open(encoding="utf-8") as replay_file:
                for line_number, line in enumerate(replay_file, 1):
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError as error:
                        message = f"invalid JSON on line {line_number}: {error.msg}"
                        raise ReplayError(message) from error
                    if not isinstance(event, dict):
                        raise ReplayError(
                            f"replay line {line_number} is not an object"
                        )
                    events.append(event)
        except OSError as error:
            message = f"cannot read replay {self.path}: {error}"
            raise ReplayError(message) from error
        if not events:
            raise ReplayError("replay file is empty")
        return events

    def _validate_common_fields(self) -> None:
        """Validate schema, run identity, event names, and contiguous sequence."""
        if self.events[0].get("schema") != SCHEMA_VERSION:
            raise ReplayError(
                f"unsupported replay schema: {self.events[0].get('schema')!r}"
            )
        sequences = [event.get("seq") for event in self.events]
        if not all(_is_int(sequence) for sequence in sequences) or sequences != list(
            range(1, len(self.events) + 1)
        ):
            raise ReplayError("replay event sequence is not contiguous")
        run_ids = {event.get("run_id") for event in self.events}
        if len(run_ids) != 1 or not all(
            isinstance(run_id, str) and run_id for run_id in run_ids
        ):
            raise ReplayError("replay events do not share one run_id")
        if any(event.get("schema") != SCHEMA_VERSION for event in self.events):
            raise ReplayError("replay events do not share a supported schema")
        if any(not isinstance(event.get("event"), str) for event in self.events):
            raise ReplayError("every replay event must have a string event name")

    def _validate_hash_chain(self) -> None:
        """Reject modified, reordered, inserted, or removed replay events."""
        previous_hash = GENESIS_HASH
        for event in self.events:
            recorded_hash = event.get("chain_hash")
            if not isinstance(recorded_hash, str):
                raise ReplayError(
                    f"replay event {event['seq']} has no valid chain_hash"
                )
            payload = {
                key: value for key, value in event.items() if key != "chain_hash"
            }
            expected_hash = replay_event_hash(previous_hash, payload)
            if not hmac.compare_digest(recorded_hash, expected_hash):
                raise ReplayError(
                    f"replay integrity failed at sequence {event['seq']}"
                )
            previous_hash = recorded_hash

    def _validate_header(self) -> None:
        """Validate the v2 checkpoint-and-delta replay header."""
        if self.header.get("event") != "replay_header":
            raise ReplayError("first replay event must be replay_header")
        if self.header.get("mode") != "checkpoint_delta":
            raise ReplayError(
                f"unsupported replay mode: {self.header.get('mode')!r}"
            )
        interval = self.header.get("checkpoint_interval")
        if not _is_int(interval) or interval <= 0:
            raise ReplayError("checkpoint_interval must be a positive integer")
        initial_turn = self.header.get("initial_turn")
        if not _is_int(initial_turn) or initial_turn < 0:
            raise ReplayError("initial_turn must be a non-negative integer")
        if len(self.events) < 3:
            raise ReplayError("replay has no complete initial checkpoint")
        if not isinstance(self.header.get("metadata"), dict):
            raise ReplayError("replay metadata must be an object")

    def _validate_footer(self) -> None:
        """Require a terminal event so truncating the replay is detectable."""
        if self.footer.get("event") != "replay_end":
            raise ReplayError("last replay event must be replay_end")
        final_turn = self.footer.get("final_turn")
        turns_recorded = self.footer.get("turns_recorded")
        if not _is_int(final_turn) or not _is_int(turns_recorded):
            raise ReplayError("replay_end has invalid turn information")
        if turns_recorded < 0:
            raise ReplayError("replay_end has a negative turn count")

    def _validate_checkpoint(
        self, event: dict[str, Any], *, initial: bool = False
    ) -> None:
        """Validate the structure and full-state hash of one checkpoint."""
        label = "initial checkpoint" if initial else "checkpoint"
        if event.get("event") != "checkpoint":
            raise ReplayError(f"{label} event is missing")
        turn = event.get("turn")
        state = event.get("state")
        expected_hash = event.get("state_hash")
        if not _is_int(turn) or turn < 0:
            raise ReplayError(f"{label} has an invalid turn")
        if not isinstance(state, dict):
            raise ReplayError(f"{label} has no state object")
        if state.get("turns") != turn:
            raise ReplayError(f"{label} turn does not match its state")
        for field in ("world", "wesen", "range", "time", "food", "stats"):
            if not isinstance(state.get(field), dict):
                raise ReplayError(f"{label} state has invalid {field!r} data")
        objects = state.get("objects")
        if not isinstance(objects, list):
            raise ReplayError(f"{label} state has no object list")
        for object_state in objects:
            _validate_object_state(object_state, label)
        length = state["world"].get("length")
        if not _is_positive_id(length):
            raise ReplayError(f"{label} has an invalid world length")
        if any(
            not all(
                0 <= coordinate < length for coordinate in object_state["position"]
            )
            for object_state in objects
        ):
            raise ReplayError(f"{label} contains an out-of-bounds object")
        object_ids = [object_state["sim_id"] for object_state in objects]
        if len(object_ids) != len(set(object_ids)):
            raise ReplayError(f"{label} repeats a simulation object ID")
        next_sim_id = state.get("next_sim_id")
        if not _is_positive_id(next_sim_id) or next_sim_id <= max(
            object_ids, default=0
        ):
            raise ReplayError(f"{label} has an invalid next_sim_id")
        if not isinstance(expected_hash, str):
            raise ReplayError(f"{label} has no state_hash")
        actual_hash = state_hash(state)
        if not hmac.compare_digest(expected_hash, actual_hash):
            raise ReplayError(f"{label} state hash failed at turn {turn}")

    def _validate_state_sequence(self) -> None:
        """Require exactly one correctly typed state transition per next turn."""
        initial_turn = self.header["initial_turn"]
        if self.initial_checkpoint["turn"] != initial_turn:
            raise ReplayError("initial checkpoint turn does not match replay header")
        interval = self.header["checkpoint_interval"]
        previous_turn = initial_turn
        for event in self.transitions:
            turn = event.get("turn")
            if not _is_int(turn) or turn != previous_turn + 1:
                raise ReplayError("replay turns must increase one turn at a time")
            checkpoint_due = (turn - initial_turn) % interval == 0
            expected_type = "checkpoint" if checkpoint_due else "turn_delta"
            if event.get("event") != expected_type:
                raise ReplayError(f"turn {turn} must be recorded as {expected_type}")
            if checkpoint_due:
                self._validate_checkpoint(event)
            else:
                delta = self._decode_delta(event)
                if delta.previous_turn != previous_turn:
                    raise ReplayError(
                        f"turn {turn} has invalid previous_turn information"
                    )
            previous_turn = turn
        if self.footer["final_turn"] != previous_turn:
            raise ReplayError("replay_end final_turn does not match replay state")
        if self.footer["turns_recorded"] != len(self.transitions):
            raise ReplayError("replay_end turn count does not match replay state")

    def _decode_delta(self, event: dict[str, Any]) -> ReplayDelta:
        """Validate and convert one JSON turn delta to typed integer IDs."""
        turn = event.get("turn")
        previous_turn = event.get("previous_turn")
        world = event.get("world")
        changed_json = event.get("changed")
        created_json = event.get("created")
        removed_json = event.get("removed")
        if not _is_int(turn) or not _is_int(previous_turn):
            raise ReplayError("turn_delta has invalid turn information")
        if not isinstance(world, dict):
            raise ReplayError(f"turn_delta at turn {turn} has no world patch")
        allowed_world_fields = {
            "world",
            "wesen",
            "range",
            "time",
            "food",
            "turns",
            "next_sim_id",
            "stats",
        }
        if set(world) - allowed_world_fields:
            raise ReplayError(f"turn_delta at turn {turn} has unknown world fields")
        if world.get("turns") != turn:
            raise ReplayError(
                f"turn_delta at turn {turn} has no matching world turn"
            )
        for field in ("world", "wesen", "range", "time", "food", "stats"):
            if field in world and not isinstance(world[field], dict):
                raise ReplayError(
                    f"turn_delta at turn {turn} has invalid {field!r} data"
                )
        if "next_sim_id" in world and not _is_positive_id(world["next_sim_id"]):
            raise ReplayError(f"turn_delta at turn {turn} has invalid next_sim_id")
        if not isinstance(changed_json, dict):
            raise ReplayError(f"turn_delta at turn {turn} has invalid changes")
        if not isinstance(created_json, list) or not all(
            isinstance(state, dict) for state in created_json
        ):
            raise ReplayError(f"turn_delta at turn {turn} has invalid creations")
        if not isinstance(removed_json, list) or not all(
            _is_positive_id(sim_id) for sim_id in removed_json
        ):
            raise ReplayError(f"turn_delta at turn {turn} has invalid removals")

        changed: dict[int, ObjectPatch] = {}
        for raw_id, patch in changed_json.items():
            if not isinstance(raw_id, str) or not raw_id.isdecimal():
                raise ReplayError(f"turn_delta at turn {turn} has invalid object ID")
            sim_id = int(raw_id)
            if not _is_positive_id(sim_id) or not isinstance(patch, dict):
                raise ReplayError(f"turn_delta at turn {turn} has invalid changes")
            if "sim_id" in patch or "type" in patch:
                raise ReplayError("object patches may not change stable identity")
            changed[sim_id] = patch

        created: list[ObjectState] = list(created_json)
        for state in created:
            _validate_object_state(state, f"turn_delta at turn {turn}")
        created_ids = [state.get("sim_id") for state in created]
        if not all(_is_positive_id(sim_id) for sim_id in created_ids):
            raise ReplayError(f"turn_delta at turn {turn} has invalid creations")
        removed = list(removed_json)
        if len(created_ids) != len(set(created_ids)):
            raise ReplayError(f"turn_delta at turn {turn} repeats a created object")
        if len(removed) != len(set(removed)):
            raise ReplayError(f"turn_delta at turn {turn} repeats a removed object")
        changed_ids = set(changed)
        if changed_ids & set(created_ids) or changed_ids & set(removed):
            raise ReplayError(
                "changed, created, and removed object IDs must be disjoint"
            )
        if set(created_ids) & set(removed):
            raise ReplayError("created and removed object IDs must be disjoint")
        return ReplayDelta(
            turn=turn,
            previous_turn=previous_turn,
            world=world,
            changed=changed,
            created=created,
            removed=removed,
        )

    def create_world(self) -> World:
        """Restore the initial checkpoint using inert source placeholders."""
        from ..world import World

        state = self.initial_checkpoint["state"]
        world = World(state, createObjects=False, load_sources=False)
        world.restore(state)
        if world.persist() != state:
            raise ReplayError("initial checkpoint did not restore exactly")
        return world

    def reset(self) -> None:
        """Reset playback to the first transition after the initial checkpoint."""
        self.index = 0

    def step(self, world: World) -> bool:
        """Apply the next checkpoint or delta, returning ``False`` at EOF."""
        if self.index >= len(self.transitions):
            return False
        event = self.transitions[self.index]
        try:
            if event["event"] == "checkpoint":
                world.apply_state(event["state"])
            else:
                delta = self._decode_delta(event)
                self._validate_delta_against_world(delta, world)
                world.apply_delta(delta)
        except (IndexError, KeyError, TypeError, ValueError) as error:
            raise ReplayError(
                f"cannot apply replay state at turn {event['turn']}: {error}"
            ) from error
        self.index += 1
        return True

    def _validate_delta_against_world(
        self, delta: ReplayDelta, world: World
    ) -> None:
        """Ensure delta object operations are valid for the current world."""
        if delta.previous_turn != world.turns or delta.turn != world.turns + 1:
            raise ReplayError("turn_delta does not follow the current world turn")
        existing_ids = set(world.objects)
        created_ids = {int(state["sim_id"]) for state in delta.created}
        if not set(delta.changed) <= existing_ids:
            raise ReplayError("turn_delta changes an object that does not exist")
        if not set(delta.removed) <= existing_ids:
            raise ReplayError("turn_delta removes an object that does not exist")
        if created_ids & existing_ids:
            raise ReplayError("turn_delta creates an object that already exists")

    def verify(self) -> VerificationResult:
        """Restore all recorded state and validate exact checkpoint round trips."""
        self.reset()
        try:
            world = self.create_world()
            checked = 0
            while self.index < len(self.transitions):
                event = self.transitions[self.index]
                self.step(world)
                checked += 1
                if (
                    event["event"] == "checkpoint"
                    and world.persist() != event["state"]
                ):
                    turn = event["turn"]
                    return VerificationResult(
                        False,
                        checked,
                        turn=turn,
                        message=f"checkpoint restoration failed at turn {turn}",
                    )
        except ReplayError as error:
            return VerificationResult(False, self.index, message=str(error))
        checkpoints = 1 + sum(
            event["event"] == "checkpoint" for event in self.transitions
        )
        return VerificationResult(
            True,
            checked,
            message=(
                f"replay verified successfully ({checked} turns, "
                f"{checkpoints} checkpoints)"
            ),
        )


def _is_int(value: object) -> TypeGuard[int]:
    """Return whether ``value`` is an integer but not a Boolean."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_positive_id(value: object) -> TypeGuard[int]:
    """Return whether ``value`` is a valid positive stable simulation ID."""
    return _is_int(value) and value > 0


def _validate_object_state(state: object, label: str) -> None:
    """Validate identity and constructor fields in a persisted object state."""
    if not isinstance(state, dict):
        raise ReplayError(f"{label} contains a non-object state")
    if not _is_positive_id(state.get("sim_id")):
        raise ReplayError(f"{label} contains an invalid simulation object ID")
    if state.get("type") not in {"wesen", "food"}:
        raise ReplayError(f"{label} contains an invalid object type")
    required = {"energy", "age", "position", "source", "time"}
    if not required <= set(state):
        raise ReplayError(f"{label} contains an incomplete object state")
    position = state["position"]
    if not (
        isinstance(position, list)
        and len(position) == 2
        and all(_is_int(coordinate) for coordinate in position)
    ):
        raise ReplayError(f"{label} contains an invalid object position")
    object_type = state["type"]
    type_fields = (
        {"seedrate", "growrate", "rangeseed", "maxamount", "maxage"}
        if object_type == "food"
        else {"maxage", "wesensource"}
    )
    if not type_fields <= set(state):
        raise ReplayError(f"{label} contains incomplete {object_type} state")
