"""Stable hashing of replay-relevant simulation state."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from .events import json_value

if TYPE_CHECKING:
    from Wesen.world import World


def _canonical_state(state: dict[str, Any]) -> dict[str, Any]:
    """Define canonical order for replay-relevant data from a state dictionary."""
    objects = sorted(
        (deepcopy(obj) for obj in state.get("objects", [])),
        key=lambda obj: obj["sim_id"],
    )
    return {
        "turn": state.get("turns", 0),
        "next_sim_id": state.get("next_sim_id", 1),
        "world": state.get("world", {}),
        "wesen": state.get("wesen", {}),
        "food": state.get("food", {}),
        "range": state.get("range", {}),
        "time": state.get("time", {}),
        "objects": objects,
    }


def state_hash(state: dict[str, Any]) -> str:
    """Hash a persisted world state without runtime object identities."""
    payload = json.dumps(
        json_value(_canonical_state(state)),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def world_hash(world: World) -> str:
    """Hash the stable replay-relevant state of ``world``."""
    return state_hash(world.persist())
