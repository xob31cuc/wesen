"""This class contains the code to run a Wesen game,
with or without GUI,
with or without savegame,
provided a configuration is given."""

from __future__ import annotations

import importlib
import json
from os.path import exists
from pprint import pprint
from typing import Any

from .defaults import DEFAULT_GAME_STATE_FILE
from .replay.recorder import ReplayRecorder
from .replay.replayer import Replayer
from .world import World

# TODO change the name of this class (it is not a daemon)


class Wesend:
    """Wesend(config)
    Runs one Wesen game by start(), with given config data.
    This module intruments a World object
    and, if enabled in the config, a Gui object.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """config should be a dictionary (see loader.py),
        extraArgs are all passed to OpenGL"""
        self.replay_path = config.pop("replay", None)
        self.verify_replay_path = config.pop("verify_replay", None)
        self.record_replay_path = config.pop("record_replay", None)
        self.replayer = None
        self.recorder = None
        self.replay_finished = False
        self.infoGui = config["gui"]
        if self.replay_path or self.verify_replay_path:
            replay_file = self.replay_path or self.verify_replay_path
            self.replayer = Replayer(replay_file)
            self.world = self.replayer.create_world()
            self.infoWorld = self.world.infoAllWorld["world"]
            self.infoWesen = self.world.infoAllWorld["wesen"]
            self.infoFood = self.world.infoAllWorld["food"]
            self.infoRange = self.world.infoAllWorld["range"]
            self.infoTime = self.world.infoAllWorld["time"]
            if self.verify_replay_path:
                self.infoGui["enable"] = False
            return

        self.infoWorld = config["world"]
        self.infoWesen = config["wesen"]
        self.infoFood = config["food"]
        self.infoRange = config["range"]
        self.infoTime = config["time"]
        if isinstance(self.infoWesen["sources"], str):
            self.infoWesen["sources"] = self.infoWesen["sources"].split(",")
        self.infoWorld["Debug"] = self.Debug
        infoAllWorld = {
            "world": self.infoWorld,
            "wesen": self.infoWesen,
            "food": self.infoFood,
            "range": self.infoRange,
            "time": self.infoTime,
        }
        if config.pop("resume", False) and exists(DEFAULT_GAME_STATE_FILE):
            with open(DEFAULT_GAME_STATE_FILE) as f:
                string = f.read()
                d = json.loads(string)
                infoAllWorld.update(d)
                self.world = World(infoAllWorld, False)
                self.world.restore(infoAllWorld)
        else:
            self.world = World(infoAllWorld)
        if self.record_replay_path:
            self.recorder = ReplayRecorder(
                self.record_replay_path,
                metadata={"program": "wesen", "mode": "snapshot"},
            )
            self.world.setRecorder(self.recorder)
            self.recorder.start(self.world)

    def start(self, extraArgs: str = "") -> bool | None:
        """starts the simulation (with GUI, if configured)"""
        try:
            if self.verify_replay_path:
                return self.verifyReplay()
            if self.infoGui["enable"]:
                self.initGUI(extraArgs)
                return None
            return self.main()
        finally:
            self.close()

    def initGUI(self, extraArgs: str) -> None:
        """handing over all control to the gui"""
        GUI = importlib.import_module(
            ".gui." + self.infoGui["source"], __package__
        ).GUI
        infoGui = {
            "wesend": self,
            "world": self.infoWorld,
            "wesen": self.infoWesen,
            "food": self.infoFood,
            "gui": self.infoGui,
        }
        GUI(infoGui, self.mainLoop, self.world, extraArgs)

    def Debug(self, message: Any) -> None:
        """currently just prints the message."""
        # TODO change or remove the Debug mechanism.
        print("debug message: ", message)

    def mainLoop(self) -> list[dict[str, Any]]:
        """Advance one normal turn or apply one replay frame."""
        if self.replayer is not None:
            self.replay_finished = not self.replayer.step(self.world)
        else:
            self.world.main()
        return self.world.getDescriptor()

    def main(self) -> bool | None:
        """calls world.main() in gui-less mode,
        until KeyboardInterrupt
        and prints stats every 1000 turns to show some action"""
        if self.replayer is not None:
            while self.replayer.step(self.world):
                pass
            self.replay_finished = True
            print(
                f"replay completed: {len(self.replayer.frames)} frames "
                f"through turn {self.world.turns}"
            )
            return True

        while True:
            try:
                self.world.main()
            except KeyboardInterrupt:
                print(" got keyboard interrupt, stopping now.")
                self.world.DumpGameState()
                break
            if (self.world.turns % 1000) == 0:
                print("turn", self.world.turns, "stats:")
                pprint(self.world.stats, indent=3, depth=4, width=80)
        return None

    def verifyReplay(self) -> bool:
        """Verify every replay frame and report the first mismatch."""
        if self.replayer is None:
            raise RuntimeError("cannot verify a replay without a replay file")
        result = self.replayer.verify()
        print(result.message)
        if not result.ok and result.expected is not None:
            print(f"expected: {result.expected}")
            print(f"actual:   {result.actual}")
        return result.ok

    def close(self) -> None:
        """Flush and close resources owned by this simulation runner."""
        if self.recorder is not None:
            self.recorder.close()
