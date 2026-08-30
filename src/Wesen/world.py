"""The world in which Wesen takes place"""

from __future__ import annotations

import json
from bisect import bisect_left, insort
from collections.abc import Callable
from copy import deepcopy
from typing import TYPE_CHECKING, Any

import deal
import numpy as np

from .defaults import DEFAULT_GAME_STATE_FILE
from .objects.base import WorldObject, WorldObjectContext
from .objects.food import Food
from .objects.wesen import RuleException, Wesen

if TYPE_CHECKING:
    from Wesen.objects.food import Food
    from Wesen.objects.wesen import Wesen
    from Wesen.replay.events import ReplayDelta, WorldPatch
    from Wesen.replay.recorder import ReplayRecorder


def _delta_is_applicable(world: World, delta: ReplayDelta) -> bool:
    """Return whether object identity and turn invariants allow ``delta``."""
    existing_ids = set(world.objects)
    changed_ids = set(delta.changed)
    removed_ids = set(delta.removed)
    created_ids = {int(state["sim_id"]) for state in delta.created}
    return (
        delta.previous_turn == world.turns
        and delta.turn == world.turns + 1
        and changed_ids <= existing_ids
        and removed_ids <= existing_ids
        and not created_ids & existing_ids
        and not changed_ids & removed_ids
        and not changed_ids & created_ids
        and not removed_ids & created_ids
    )


class World:
    """A World object contains a single Wesen simulation,
    In the MVC paradigm it is M+C.
    The main() method runs a single simulation turn.
    The getDescriptor() method returns descriptive data for viewers.
    Via AddObject(info) and DeleteObject(id)
    one can manipulate the simulation."""

    def __init__(
        self,
        infoAllWorld: dict[str, Any] | None = None,
        createObjects: bool = True,
        callbacks: dict[str, Callable[..., Any]] | None = None,
        load_sources: bool = True,
    ) -> None:
        """infoAllWorld is a dictionary of dictionaries"""
        self.callbacks = callbacks or {}
        self.load_sources = load_sources
        self.recorder: ReplayRecorder | None = None
        self.win_probabilities: dict[str, float] = {}
        self.stats: dict[str, dict[str, int]]
        if infoAllWorld is not None:
            self.setInfoAllWorld(infoAllWorld)
            if createObjects:
                self.createDefaultObjects()
            if "stats" in infoAllWorld:
                self.stats = deepcopy(infoAllWorld["stats"])
            else:
                self.initStats()

    def setInfoAllWorld(self, infoAllWorld: dict[str, Any]) -> None:
        """sets the infoAllWorld and initializes member variables"""
        # copy everything that will be modified
        self.infoAllWorld = infoAllWorld.copy()
        self.infoAllWorld.update(
            {
                key: infoAllWorld[key].copy()
                for key in ("wesen", "world", "food", "range", "time")
            }
        )
        self.objects: dict[int, WorldObject] = {}
        self.turns = infoAllWorld.get("turns", 0)
        self.next_sim_id = infoAllWorld.get("next_sim_id", 1)
        self.stats = {}
        length = infoAllWorld["world"]["length"]
        self.map = np.empty((length, length), dtype=object)
        self.map.flat[:] = [{} for _ in range(length**2)]
        self._occupied_y: list[list[int]] = [[] for _ in range(length)]
        # is initialized depending on sources in initStats()
        self.infoAllWorld["world"].update(
            {
                "DeleteObject": self.DeleteObject,
                "AddObject": self.AddObject,
                "UpdatePos": self.UpdatePos,
                "objects": self.objects,
                "map": self.map,
            }
        )
        self.infoAllWorld["food"]["type"] = "food"
        self.infoAllWorld["wesen"]["type"] = "wesen"
        sources = self.infoAllWorld["wesen"]["sources"]
        if isinstance(sources, str):
            sources = sources.split(",")
            self.infoAllWorld["wesen"]["sources"] = sources
        sources.sort()

    def setCallbacks(self, callbacks: dict[str, Callable[..., Any]]) -> None:
        """used by UI to manipulate the world
        >>> callbacks = dict.fromkeys(["DeleteObject", "AddObject", "UpdatePos"])
        >>> set(callbacks) == {"DeleteObject", "AddObject", "UpdatePos"}
        True
        """
        self.callbacks = callbacks

    def setRecorder(self, recorder: ReplayRecorder) -> None:
        """Attach a replay recorder to future simulation changes."""
        self.recorder = recorder
        for obj in self.objects.values():
            obj.recorder = recorder

    def createDefaultObjects(self) -> None:
        """creates all objects (wesen and food) as specified by self.infoAllWorld"""
        self.objects = {}
        for entry in self.infoAllWorld["wesen"]["sources"]:
            for _ in range(self.infoAllWorld["wesen"]["count"]):
                temp = self.infoAllWorld["wesen"].copy()
                temp["source"] = entry
                self.AddObject(temp)
        for _ in range(self.infoAllWorld["food"]["count"]):
            self.AddObject(self.infoAllWorld["food"])

    def initStats(self) -> None:
        """resets self.stats to count and energy 0 for all object-types"""
        stats = {
            "food": {"count": 0, "energy": 0},
            "global": {"count": 0, "energy": 0},
        }
        for source in self.infoAllWorld["wesen"]["sources"]:
            stats[source] = {"count": 0, "energy": 0}
        self.stats = stats

    def DeleteObject(self, objectid: int) -> bool:
        """removes an object from the world."""
        obj = self.objects[objectid]
        pos = obj.position
        cell = self.map[pos[0]][pos[1]]
        del cell[objectid]
        if not cell:
            ys = self._occupied_y[pos[0]]
            del ys[bisect_left(ys, pos[1])]
        del self.objects[objectid]
        if self.recorder is not None:
            self.recorder.semantic_event(
                "object_deleted",
                turn=self.turns,
                object_id=objectid,
            )
        callback = self.callbacks.get("DeleteObject")
        if callback is not None:
            callback(objectid)
        return True

    def AddObject(self, infoObject: dict[str, Any]) -> WorldObject:
        """adds an object to the world."""
        requested_sim_id = infoObject.get("sim_id")
        if requested_sim_id is None:
            sim_id = self.next_sim_id
            self.next_sim_id += 1
            object_info = infoObject
        else:
            sim_id = int(requested_sim_id)
            if sim_id in self.objects:
                raise ValueError(f"duplicate simulation object id: {sim_id}")
            self.next_sim_id = max(self.next_sim_id, sim_id + 1)
            object_info = infoObject.copy()
            object_info.pop("sim_id", None)
        infoAllObject: WorldObjectContext = {
            "world": self.infoAllWorld["world"],
            "range": self.infoAllWorld["range"],
            "time": self.infoAllWorld["time"],
            "food": self.infoAllWorld["food"],
            "object": object_info,
            "sim_id": sim_id,
            "load_source": self.load_sources,
            "recorder": self.recorder,
            "get_turn": lambda: self.turns,
            "occupied_y": self._occupied_y,
        }
        infoAllObject["world"].update({"objects": self.objects})
        newObject: WorldObject
        if object_info["type"] == "wesen":
            newObject = Wesen(infoAllObject)
        elif object_info["type"] == "food":
            newObject = Food(infoAllObject)
        else:
            raise Exception("invalid objectType: " + object_info["type"])
        self.objects[sim_id] = newObject
        x, y = newObject.position
        cell = self.map[x][y]
        if not cell:
            insort(self._occupied_y[x], y)
        cell[sim_id] = newObject
        if self.recorder is not None:
            self.recorder.semantic_event(
                "object_created",
                turn=self.turns,
                object_id=sim_id,
            )
        callback = self.callbacks.get("AddObject")
        if callback is not None:
            callback(sim_id, newObject.getDescriptor())
        return newObject

    def UpdatePos(self, _id: int, oldPos: list[int], obj: dict[str, Any]) -> None:
        """updates the map about an objects position"""
        old_cell = self.map[oldPos[0]][oldPos[1]]
        del old_cell[_id]
        if not old_cell:
            ys = self._occupied_y[oldPos[0]]
            del ys[bisect_left(ys, oldPos[1])]
        newPos = obj["position"]
        new_cell = self.map[newPos[0]][newPos[1]]
        if not new_cell:
            insort(self._occupied_y[newPos[0]], newPos[1])
        new_cell[_id] = self.objects[_id]
        if self.recorder is not None:
            self.recorder.semantic_event(
                "object_moved",
                turn=self.turns,
                object_id=_id,
                **{"from": oldPos, "to": newPos},
            )
        callback = self.callbacks.get("UpdatePos")
        if callback is not None:
            callback(_id, obj)

    def getDescriptor(self) -> list[dict[str, Any]]:
        """returns a list of descriptive information for the GUI"""
        return [o.getDescriptor() for o in self.objects.values()]

    def DumpGameState(self, filename: str = DEFAULT_GAME_STATE_FILE) -> None:
        """writes the whole game state to a given filename (as JSON)"""
        # TODO move this to wesend, where it belongs!
        with open(filename, "w") as f:
            jsonDump = self.persistToJSON()
            f.write(jsonDump)

    def persist(self) -> dict[str, Any]:
        """Return all state required to restore this world independently.

        Replay deltas use :meth:`persist_world_state` and one object capture
        instead, avoiding this full-world operation on ordinary turns.
        """
        state = self.persist_world_state()
        state["objects"] = [obj.persist() for obj in self.objects.values()]
        return state

    def persist_world_state(self) -> dict[str, Any]:
        """Return replay-relevant world state without persisting any objects."""
        state: dict[str, Any] = {
            "world": self.infoAllWorld[
                "world"
            ].copy(),  # need to copy, since we are modifying it
            "wesen": deepcopy(self.infoAllWorld["wesen"]),
            "range": deepcopy(self.infoAllWorld["range"]),
            "time": deepcopy(self.infoAllWorld["time"]),
            "food": deepcopy(self.infoAllWorld["food"]),
            "turns": self.turns,
            "next_sim_id": self.next_sim_id,
            "stats": deepcopy(self.stats),
        }
        state["world"].pop("Debug", None)
        state["world"].pop("map", None)
        state["world"].pop("DeleteObject", None)
        state["world"].pop("AddObject", None)
        state["world"].pop("objects", None)
        state["world"].pop("UpdatePos", None)
        return state

    def restore(self, obj: dict[str, Any]) -> None:
        """restores the state of the world represented by obj"""
        for objectid in list(self.objects):
            callback = self.callbacks.get("DeleteObject")
            if callback is not None:
                callback(objectid)
        self.objects = {}
        length = self.infoAllWorld["world"]["length"]
        self.map = np.empty((length, length), dtype=object)
        self.map.flat[:] = [{} for _ in range(length**2)]
        self._occupied_y = [[] for _ in range(length)]
        self.infoAllWorld["world"]["objects"] = self.objects
        self.infoAllWorld["world"]["map"] = self.map
        self.turns = obj.get("turns", 0)
        self.next_sim_id = obj.get("next_sim_id", 1)
        for infoObj in obj["objects"]:
            newObj = self.AddObject(infoObj)
            newObj.restore(infoObj)
        largest_id = max(self.objects, default=0)
        self.next_sim_id = max(self.next_sim_id, largest_id + 1)
        if "stats" in obj:
            self.stats = deepcopy(obj["stats"])
        else:
            self.initStats()

    def apply_state(self, obj: dict[str, Any]) -> None:
        """Replace this world from one independently restorable checkpoint."""
        callbacks = self.callbacks
        recorder = self.recorder
        load_sources = self.load_sources
        old_ids = list(self.objects)
        for objectid in old_ids:
            callback = callbacks.get("DeleteObject")
            if callback is not None:
                callback(objectid)
        self.callbacks = {}
        self.setInfoAllWorld(obj)
        self.callbacks = callbacks
        self.recorder = recorder
        self.load_sources = load_sources
        self.restore(obj)

    @deal.pre(_delta_is_applicable)
    def apply_delta(self, delta: ReplayDelta) -> None:
        """Apply recorded state changes without executing simulation behavior."""
        self._apply_world_patch(delta.world)

        for sim_id in delta.removed:
            self.DeleteObject(sim_id)
        for state in delta.created:
            new_object = self.AddObject(state)
            new_object.restore(state)
        for sim_id, patch in delta.changed.items():
            obj = self.objects[sim_id]
            old_position = list(obj.position)
            state = obj.persist()
            state.update(deepcopy(patch))
            obj.restore(state)
            if obj.position != old_position:
                self.UpdatePos(sim_id, old_position, obj.getDescriptor())

        self.turns = delta.turn

    def _apply_world_patch(self, patch: WorldPatch) -> None:
        """Restore changed world fields while retaining runtime references."""
        allowed = {
            "world",
            "wesen",
            "range",
            "time",
            "food",
            "turns",
            "next_sim_id",
            "stats",
        }
        unknown = set(patch) - allowed
        if unknown:
            raise ValueError(f"unsupported replay world fields: {sorted(unknown)!r}")

        for key in ("wesen", "range", "time", "food"):
            if key in patch:
                value = patch[key]
                if not isinstance(value, dict):
                    raise ValueError(f"replay world field {key!r} must be an object")
                target = self.infoAllWorld[key]
                target.clear()
                target.update(deepcopy(value))

        if "world" in patch:
            value = patch["world"]
            if not isinstance(value, dict):
                raise ValueError("replay world field 'world' must be an object")
            old_length = self.infoAllWorld["world"]["length"]
            runtime = {
                key: self.infoAllWorld["world"][key]
                for key in (
                    "Debug",
                    "map",
                    "DeleteObject",
                    "AddObject",
                    "objects",
                    "UpdatePos",
                )
                if key in self.infoAllWorld["world"]
            }
            self.infoAllWorld["world"].clear()
            self.infoAllWorld["world"].update(deepcopy(value))
            self.infoAllWorld["world"].update(runtime)
            if self.infoAllWorld["world"]["length"] != old_length:
                self._rebuild_spatial_index()

        if "next_sim_id" in patch:
            self.next_sim_id = int(patch["next_sim_id"])
        if "stats" in patch:
            stats = patch["stats"]
            if not isinstance(stats, dict):
                raise ValueError("replay world field 'stats' must be an object")
            self.stats = deepcopy(stats)
        if "turns" in patch:
            self.turns = int(patch["turns"])

    def _rebuild_spatial_index(self) -> None:
        """Rebuild maps and object references after a recorded world resize."""
        length = int(self.infoAllWorld["world"]["length"])
        if length <= 0:
            raise ValueError("recorded world length must be positive")
        self.map = np.empty((length, length), dtype=object)
        self.map.flat[:] = [{} for _ in range(length**2)]
        self._occupied_y = [[] for _ in range(length)]
        self.infoAllWorld["world"]["map"] = self.map
        for sim_id, obj in self.objects.items():
            x, y = obj.position
            if not 0 <= x < length or not 0 <= y < length:
                raise ValueError(
                    f"object {sim_id} is outside recorded world boundaries"
                )
            obj.map = self.map
            obj.occupiedY = self._occupied_y
            cell = self.map[x][y]
            if not cell:
                insort(self._occupied_y[x], y)
            cell[sim_id] = obj

    def persistToJSON(self) -> str:
        """returns the persistency info as a JSON string"""
        d = self.persist()
        return json.dumps(d)

    def restoreFromJson(self, string: str) -> None:
        # TODO figure out if restore and restoreFromJson are both needed
        """restores the state of the world from a JSON string"""
        obj = json.loads(string)
        self.setInfoAllWorld(obj)
        self.restore(obj)

    def main(self) -> None:
        """runs one turn of Game code (and all objects code, including the AI)"""
        self.turns += 1
        if self.recorder is not None:
            self.recorder.semantic_event(
                "turn_start",
                turn=self.turns,
                object_count=len(self.objects),
            )
        self.initStats()
        stats = self.stats
        # in the following, the self.objects.copy() is inevitable,
        # as the o.main() might modify self.objects.
        for o in self.objects.copy().values():
            if o.objectType == "wesen":
                stats[o.source]["count"] += 1
                stats[o.source]["energy"] += o.energy
                # stillActive = True;
            else:
                stats["food"]["count"] += 1
                stats["food"]["energy"] += o.energy
            try:
                o.main()
            except RuleException:
                pass  # TODO: make offending source loose
        stats["global"] = {
            "count": len(self.objects),
            "energy": sum(objectType["energy"] for objectType in stats.values()),
        }
        self.stats = stats
        if self.recorder is not None:
            self.recorder.record_turn(self)
