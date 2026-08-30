"""Structlog-backed JSON Lines replay recorder."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import structlog

from .events import ObjectState, json_value, state_changes
from .hash import world_hash

if TYPE_CHECKING:
    from pathlib import PosixPath

    from Wesen.objects.base import WorldObject
    from Wesen.world import World

SCHEMA_VERSION = 1


def _serialize(event_dict: dict[str, Any], **_kwargs: Any) -> str:
    """Serialize an event dictionary to a compact JSON string."""
    return json.dumps(
        json_value(event_dict),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


class ReplayRecorder:
    """Write replay events through a small simulation-specific API."""

    def __init__(
        self,
        path: PosixPath | str,
        metadata: dict[str, str] | None = None,
        run_id: str | None = None,
    ) -> None:
        """Open ``path`` and initialize metadata for a replay event stream."""
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or str(uuid4())
        self.metadata = dict(metadata or {})
        self.seq = 0
        self.closed = False
        self._stream = self.path.open("w", encoding="utf-8", buffering=1)
        self._logger = structlog.wrap_logger(
            structlog.PrintLogger(self._stream),
            processors=[structlog.processors.JSONRenderer(serializer=_serialize)],
        )

    def event(self, event_type: str, **data: Any) -> None:
        """Write one schema-tagged, monotonically sequenced event."""
        if self.closed:
            raise RuntimeError("cannot write to a closed replay recorder")
        self.seq += 1
        event_data = {
            "schema": SCHEMA_VERSION,
            "run_id": self.run_id,
            "seq": self.seq,
        }
        event_data.update(data)
        self._logger.info(event_type, **event_data)

    def start(self, world: World) -> None:
        """Write the replay header and its full initial snapshot."""
        self.event(
            "replay_header",
            mode="snapshot",
            initial_state=world.persist(),
            metadata=self.metadata,
        )

    def record_state_changes(
        self,
        before: dict[int, ObjectState],
        objects: dict[int, WorldObject],
        turn: int,
    ) -> None:
        """Record field changes for objects present before and after."""
        for sim_id in sorted(before.keys() & objects.keys()):
            current = objects[sim_id].persist()
            changes = state_changes(before[sim_id], current)
            if changes:
                self.event(
                    "object_state",
                    turn=turn,
                    object_id=sim_id,
                    changes=changes,
                )

    def record_turn(self, world: World) -> None:
        """Write a complete frame and its verification hash."""
        digest = world_hash(world)
        self.event(
            "frame",
            turn=world.turns,
            state=world.persist(),
            world_hash=digest,
        )
        self.event("turn_end", turn=world.turns, world_hash=digest)

    def close(self) -> None:
        """Close the replay recorder"""
        if not self.closed:
            self._stream.flush()
            self._stream.close()
            self.closed = True

    def __enter__(self) -> ReplayRecorder:
        """Return this recorder for use as a context manager."""
        return self

    def __exit__(self, *_exc_info: Any) -> None:
        """Close the replay stream when leaving a context."""
        self.close()
