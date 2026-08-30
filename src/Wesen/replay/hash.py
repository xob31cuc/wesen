"""Canonical replay-event chaining and checkpoint-state hashing."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from .events import json_value

if TYPE_CHECKING:
    from Wesen.world import World

GENESIS_HASH = "0" * 64


def canonical_json(value: Any) -> str:
    """Serialize a value in the canonical form used by replay integrity hashes."""
    return json.dumps(
        json_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def replay_event_hash(previous_hash: str, event: dict[str, Any]) -> str:
    """Extend a SHA-256 replay hash chain with one canonical event."""
    payload = (
        previous_hash.encode("ascii") + b"\n" + canonical_json(event).encode("utf-8")
    )
    return hashlib.sha256(payload).hexdigest()


def _canonical_state(state: dict[str, Any]) -> dict[str, Any]:
    """Return checkpoint state with objects ordered by stable simulation ID."""
    canonical = dict(state)
    canonical["objects"] = sorted(
        state.get("objects", []), key=lambda obj: obj["sim_id"]
    )
    return canonical


def state_hash(state: dict[str, Any]) -> str:
    """Hash every persisted field in an independently restorable checkpoint."""
    payload = canonical_json(_canonical_state(state)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def world_hash(world: World) -> str:
    """Hash the complete stable persisted state of ``world``."""
    return state_hash(world.persist())
