"""Snapshot replay reader and verifier."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .hash import world_hash
from .recorder import SCHEMA_VERSION

if TYPE_CHECKING:
    from pathlib import PosixPath

    from Wesen.world import World


class ReplayError(Exception):
    """Raised for malformed, unsupported, or exhausted replay data."""


@dataclass(frozen=True)
class VerificationResult:
    """Summarize replay verification success or the first mismatch."""

    ok: bool
    frames: int
    turn: int | None = None
    expected: str | None = None
    actual: str | None = None
    message: str = ""


class Replayer:
    """Read a replay file and apply its recorded snapshots one by one."""

    def __init__(self, path: PosixPath | str) -> None:
        """Load and validate the replay event stream at ``path``."""
        self.path = Path(path)
        self.events = self._read_events()
        self.header = self.events[0]
        if self.header.get("event") != "replay_header":
            raise ReplayError("first replay event must be replay_header")
        if self.header.get("schema") != SCHEMA_VERSION:
            raise ReplayError(
                f"unsupported replay schema: {self.header.get('schema')!r}"
            )
        if self.header.get("mode") != "snapshot":
            raise ReplayError(
                f"unsupported replay mode: {self.header.get('mode')!r}"
            )
        if "initial_state" not in self.header:
            raise ReplayError("replay header has no initial_state")
        self.frames = [
            event for event in self.events if event.get("event") == "frame"
        ]
        self.turn_end_hashes = {
            event["turn"]: event.get("world_hash")
            for event in self.events
            if event.get("event") == "turn_end" and "turn" in event
        }
        self.index = 0

    def _read_events(self) -> list[dict[str, Any]]:
        """Read and validate events from the replay file at self.path."""
        events = []
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
        sequences = [event.get("seq") for event in events]
        if sequences != list(range(1, len(events) + 1)):
            raise ReplayError("replay event sequence is not contiguous")
        run_ids = {event.get("run_id") for event in events}
        if len(run_ids) != 1 or None in run_ids:
            raise ReplayError("replay events do not share one run_id")
        if any(event.get("schema") != SCHEMA_VERSION for event in events):
            raise ReplayError("replay events do not share a supported schema")
        return events

    def create_world(self) -> World:
        """Restore the initial frame using inert source placeholders."""
        from ..world import World

        state = self.header["initial_state"]
        world = World(state, createObjects=False, load_sources=False)
        world.restore(state)
        return world

    def reset(self) -> None:
        """Reset Replayer to verify next recorded replay"""
        self.index = 0

    def step(self, world: World) -> bool:
        """Apply the next recorded frame, or return ``False`` at EOF."""
        if self.index >= len(self.frames):
            return False
        frame = self.frames[self.index]
        if "state" not in frame:
            raise ReplayError(f"replay frame {self.index + 1} has no state snapshot")
        world.apply_state(frame["state"])
        self.index += 1
        return True

    def verify(self) -> VerificationResult:
        """Apply every frame and return the first hash mismatch, if any."""
        self.reset()
        world = self.create_world()
        checked = 0
        for frame in self.frames:
            if not self.step(world):
                break
            checked += 1
            turn = frame.get("turn", world.turns)
            expected_hashes = [
                ("frame", frame.get("world_hash")),
                ("turn_end", self.turn_end_hashes.get(turn)),
            ]
            if any(expected is None for _, expected in expected_hashes):
                missing = next(
                    source
                    for source, expected in expected_hashes
                    if expected is None
                )
                return VerificationResult(
                    False,
                    checked,
                    turn=turn,
                    message=(
                        f"replay verification failed at turn {turn}: "
                        f"missing {missing} world_hash"
                    ),
                )
            actual = world_hash(world)
            for _source, expected in expected_hashes:
                if actual != expected:
                    return VerificationResult(
                        False,
                        checked,
                        turn=turn,
                        expected=expected,
                        actual=actual,
                        message=(f"replay verification failed at turn {turn}"),
                    )
        return VerificationResult(
            True,
            checked,
            message=f"replay verified successfully ({checked} frames)",
        )
