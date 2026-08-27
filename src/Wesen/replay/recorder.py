"""Structlog-backed JSON Lines replay recorder."""

import json
from pathlib import Path
from uuid import uuid4

import structlog

from .events import json_value, state_changes
from .hash import world_hash

SCHEMA_VERSION = 1


def _serialize(event_dict, **_kwargs):
    return json.dumps(
        json_value(event_dict),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


class ReplayRecorder:
    """Write replay events through a small simulation-specific API."""

    def __init__(self, path, metadata=None, run_id=None):
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

    def event(self, event_type, **data):
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

    def start(self, world):
        """Write the replay header and its full initial snapshot."""
        self.event(
            "replay_header",
            mode="snapshot",
            initial_state=world.persist(),
            metadata=self.metadata,
        )

    def record_state_changes(self, before, objects, turn):
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

    def record_turn(self, world):
        """Write a complete frame and its verification hash."""
        digest = world_hash(world)
        self.event(
            "frame",
            turn=world.turns,
            state=world.persist(),
            world_hash=digest,
        )
        self.event("turn_end", turn=world.turns, world_hash=digest)

    def close(self):
        if not self.closed:
            self._stream.flush()
            self._stream.close()
            self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info):
        self.close()
