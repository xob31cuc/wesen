"""Helpers for describing replay-relevant object effects."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from Wesen.objects.base import WorldObject

type ObjectState = dict[str, Any]


def json_value(value: Any) -> Any:
    """Normalize persistence data before logging and hashing."""
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
    """Convert a supported JSON key to a string."""
    if key is None or isinstance(key, (bool, int, float, str)):
        return str(key)
    key_type = type(key)
    return f"<unsupported:{key_type.__module__}.{key_type.__qualname__}>"


def object_state(obj: WorldObject) -> ObjectState:
    """Return an object's stable, JSON-serializable simulation state."""
    return deepcopy(obj.persist())


def object_states(
    objects: dict[int, WorldObject],
) -> dict[int, ObjectState]:
    """Take a state snapshot of an object mapping keyed by ``sim_id``."""
    return {sim_id: object_state(obj) for sim_id, obj in objects.items()}


def state_changes(
    before: ObjectState,
    after: ObjectState,
) -> ObjectState:
    """Return changed fields, using the values from ``after``."""
    return {
        key: deepcopy(value)
        for key, value in after.items()
        if before.get(key) != value
    }
