"""Compact checkpoint-and-delta replay recording."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol
from uuid import uuid4

import deal

from .events import ObjectState, WorldState, object_states, replay_delta
from .hash import GENESIS_HASH, canonical_json, replay_event_hash, state_hash

if TYPE_CHECKING:
    from Wesen.world import World

SCHEMA_VERSION = 2
DEFAULT_CHECKPOINT_INTERVAL = 100


class SemanticEventSink(Protocol):
    """Accept simulation meaning without coupling it to replay state storage."""

    def event(self, event_type: str, **data: Any) -> None:
        """Record one semantic simulation event."""
        ...


@deal.pre(lambda interval: interval > 0)
def _checked_checkpoint_interval(interval: int) -> int:
    """Validate and return a positive checkpoint interval."""
    if interval <= 0:
        raise ValueError("checkpoint interval must be positive")
    return interval


class ReplayRecorder:
    """Write independent checkpoints and compact turn deltas as JSON Lines."""

    path: Path
    run_id: str
    metadata: dict[str, str]
    checkpoint_interval: int
    semantic_sink: SemanticEventSink | None
    seq: int
    closed: bool
    started: bool

    def __init__(
        self,
        path: Path | str,
        metadata: dict[str, str] | None = None,
        run_id: str | None = None,
        checkpoint_interval: int = DEFAULT_CHECKPOINT_INTERVAL,
        semantic_sink: SemanticEventSink | None = None,
    ) -> None:
        """Open ``path`` and configure a versioned replay state stream."""
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or str(uuid4())
        self.metadata = dict(metadata or {})
        self.checkpoint_interval = _checked_checkpoint_interval(checkpoint_interval)
        self.semantic_sink = semantic_sink
        self.seq = 0
        self.closed = False
        self.started = False
        self._initial_turn = 0
        self._last_turn = 0
        self._turn_count = 0
        self._chain_hash = GENESIS_HASH
        self._previous_world: WorldState = {}
        self._previous_objects: dict[int, ObjectState] = {}
        self._stream = self.path.open("w", encoding="utf-8", buffering=1)

    def _write_event(self, event_type: str, **data: Any) -> None:
        """Write one sequenced event and extend the replay integrity chain."""
        if self.closed:
            raise RuntimeError("cannot write to a closed replay recorder")
        self.seq += 1
        event = {
            "event": event_type,
            "schema": SCHEMA_VERSION,
            "run_id": self.run_id,
            "seq": self.seq,
            **data,
        }
        self._chain_hash = replay_event_hash(self._chain_hash, event)
        event["chain_hash"] = self._chain_hash
        self._stream.write(canonical_json(event) + "\n")

    def semantic_event(self, event_type: str, **data: Any) -> None:
        """Forward meaning-oriented instrumentation to its separate sink."""
        if self.semantic_sink is not None:
            self.semantic_sink.event(event_type, **data)

    def start(self, world: World) -> None:
        """Write the header and independently restorable initial checkpoint."""
        if self.started:
            raise RuntimeError("replay recorder has already been started")
        initial_world = world.persist_world_state()
        initial_objects = object_states(world.objects)
        initial_state = dict(initial_world)
        initial_state["objects"] = list(initial_objects.values())
        self._initial_turn = int(initial_state.get("turns", 0))
        self._last_turn = self._initial_turn
        self._previous_world = initial_world
        self._previous_objects = initial_objects
        self._write_event(
            "replay_header",
            mode="checkpoint_delta",
            checkpoint_interval=self.checkpoint_interval,
            initial_turn=self._initial_turn,
            metadata=self.metadata,
        )
        self._write_checkpoint(initial_state)
        self.started = True

    def _write_checkpoint(self, state: dict[str, Any]) -> None:
        """Write a full state and its checkpoint-only persisted-state hash."""
        self._write_event(
            "checkpoint",
            turn=state.get("turns", 0),
            state=state,
            state_hash=state_hash(state),
        )

    @deal.pre(
        lambda self, world: self.started and world.turns == self._last_turn + 1
    )
    def record_turn(self, world: World) -> None:
        """Capture one turn once, then write either its delta or a checkpoint."""
        if not self.started:
            raise RuntimeError("replay recorder must be started before recording")
        if world.turns != self._last_turn + 1:
            raise ValueError("recorded replay turns must be contiguous")

        current_world = world.persist_world_state()
        current_objects = object_states(world.objects)
        if (world.turns - self._initial_turn) % self.checkpoint_interval == 0:
            checkpoint = dict(current_world)
            checkpoint["objects"] = list(current_objects.values())
            self._write_checkpoint(checkpoint)
        else:
            delta = replay_delta(
                previous_turn=self._last_turn,
                turn=world.turns,
                before_world=self._previous_world,
                after_world=current_world,
                before_objects=self._previous_objects,
                after_objects=current_objects,
            )
            self._write_event("turn_delta", **delta.event_data())

        self._previous_world = current_world
        self._previous_objects = current_objects
        self._last_turn = world.turns
        self._turn_count += 1

    def close(self) -> None:
        """Write a terminal integrity event, then close the stream exactly once."""
        if not self.closed:
            if self.started:
                self._write_event(
                    "replay_end",
                    final_turn=self._last_turn,
                    turns_recorded=self._turn_count,
                )
            self._stream.flush()
            self._stream.close()
            self.closed = True

    def __enter__(self) -> ReplayRecorder:
        """Return this recorder for use as a context manager."""
        return self

    def __exit__(self, *_exc_info: Any) -> None:
        """Close the replay stream when leaving a context."""
        self.close()
