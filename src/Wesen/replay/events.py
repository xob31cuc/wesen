"""Typed state-delta helpers shared by replay recording and playback."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from Wesen.objects.base import WorldObject

type ObjectState = dict[str, Any]
type ObjectPatch = dict[str, Any]
type WorldState = dict[str, Any]
type WorldPatch = dict[str, Any]


@dataclass(frozen=True, slots=True)
class ReplayDelta:
    """Describe one recorded turn as changes from the previous turn."""

    turn: int
    previous_turn: int
    world: WorldPatch
    changed: dict[int, ObjectPatch]
    created: list[ObjectState]
    removed: list[int]

    def event_data(self) -> dict[str, Any]:
        """Return the JSON event fields for this delta."""
        return {
            "turn": self.turn,
            "previous_turn": self.previous_turn,
            "world": self.world,
            "changed": {
                str(sim_id): patch for sim_id, patch in sorted(self.changed.items())
            },
            "created": sorted(self.created, key=lambda state: state["sim_id"]),
            "removed": sorted(self.removed),
        }


def json_value(value: Any) -> Any:
    """Normalize persistence data to deterministic JSON-compatible values."""
    if isinstance(value, Mapping):
        return {_json_key(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if isinstance(value, set):
        return sorted((json_value(item) for item in value), key=repr)
    if hasattr(value, "item"):
        return value.item()
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    value_type = type(value)
    type_name = f"{value_type.__module__}.{value_type.__qualname__}"
    return f"<unsupported:{type_name}>"


def _json_key(key: Any) -> str:
    """Convert a supported JSON key to a deterministic string."""
    if key is None or isinstance(key, (bool, int, float, str)):
        return str(key)
    key_type = type(key)
    return f"<unsupported:{key_type.__module__}.{key_type.__qualname__}>"


def object_state(obj: WorldObject) -> ObjectState:
    """Return an independent snapshot of one object's persisted state."""
    return deepcopy(obj.persist())


def object_states(objects: Mapping[int, WorldObject]) -> dict[int, ObjectState]:
    """Snapshot an object mapping once, keyed by stable simulation ID."""
    return {sim_id: object_state(obj) for sim_id, obj in objects.items()}


def state_changes(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> dict[str, Any]:
    """Return fields whose values are new or changed in ``after``."""
    return {
        key: deepcopy(value)
        for key, value in after.items()
        if key not in before or before[key] != value
    }


def replay_delta(
    previous_turn: int,
    turn: int,
    before_world: WorldState,
    after_world: WorldState,
    before_objects: Mapping[int, ObjectState],
    after_objects: Mapping[int, ObjectState],
) -> ReplayDelta:
    """Build a compact delta between two complete in-memory state captures."""
    before_ids = set(before_objects)
    after_ids = set(after_objects)
    common_ids = before_ids & after_ids
    changed = {
        sim_id: patch
        for sim_id in sorted(common_ids)
        if (patch := state_changes(before_objects[sim_id], after_objects[sim_id]))
    }
    return ReplayDelta(
        turn=turn,
        previous_turn=previous_turn,
        world=state_changes(before_world, after_world),
        changed=changed,
        created=[
            deepcopy(after_objects[sim_id]) for sim_id in after_ids - before_ids
        ],
        removed=sorted(before_ids - after_ids),
    )
