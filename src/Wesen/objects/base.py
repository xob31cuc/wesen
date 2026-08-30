"""model and controller for single objects in the simulation"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterator
from typing import (
    TYPE_CHECKING,
    Any,
    NotRequired,
    TypedDict,
)

from ..point import getRandomPosition

if TYPE_CHECKING:
    from Wesen.replay.recorder import ReplayRecorder


class WorldObjectContext(TypedDict):
    """Dependencies and configuration supplied by ``World.AddObject``."""

    world: dict[str, Any]
    range: dict[str, Any]
    time: dict[str, Any]
    food: dict[str, Any]
    object: dict[str, Any]
    sim_id: int
    load_source: NotRequired[bool]
    recorder: NotRequired[ReplayRecorder | None]
    get_turn: NotRequired[Callable[[], int]]
    occupied_y: list[list[int]]


class WorldObject:
    """this class is an abstraction to all world objects,
    as Wesen, Food and maybe some day something else.
    """

    infoWorld: dict[str, Any]
    infoObject: dict[str, Any]
    infoRange: dict[str, Any]
    sim_id: int
    recorder: ReplayRecorder | None
    getTurn: Callable[[], int]
    objectType: str
    energy: int
    DeleteObject: Callable[[int], bool]
    AddObject: Callable[[dict[str, Any]], WorldObject]
    worldObjects: dict[int, Any]
    map: Any
    occupiedY: list[list[int]]
    UpdatePos: Callable[[int, list[int], dict[str, Any]], None]
    age: int
    time: int
    source: str
    dead: bool
    position: list[int]

    def __init__(self, infoAllObject: WorldObjectContext) -> None:
        # self.infoAllObject = infoAllObject;
        self.infoWorld = infoAllObject["world"]
        self.infoObject = infoAllObject["object"]
        self.infoRange = infoAllObject["range"]
        self.sim_id = infoAllObject["sim_id"]
        self.recorder = infoAllObject.get("recorder")
        self.getTurn = infoAllObject.get("get_turn", lambda: 0)
        self.objectType = self.infoObject["type"]
        self.energy = self.infoObject["energy"]
        self.DeleteObject = self.infoWorld["DeleteObject"]
        self.AddObject = self.infoWorld["AddObject"]
        self.worldObjects = self.infoWorld["objects"]
        self.map = self.infoWorld["map"]
        self.occupiedY = infoAllObject["occupied_y"]
        self.UpdatePos = self.infoWorld["UpdatePos"]
        self.age = 0
        self.time = 0
        self.source = ""
        self.dead = False
        self.position = self.infoObject.get(
            "position", getRandomPosition(self.infoWorld["length"])
        )

    def __repr__(self) -> str:
        return (
            f"<worldobject sim_id={self.sim_id} "
            f"pos={self.position} energy={self.energy}>"
        )

    def getRangeIterator(
        self, radius: int, condition: Callable[[Any], bool] | None
    ) -> Iterator[tuple[int, Any]]:
        """returns an iterator of pairs (id, object)
        with all objects from objectIterator in radius
        that match the condition.
        The radius is taken in the maximum metric,
        where norm(v) = max(abs(v[0]),abs(v[1]))"""
        # HINT: as this is the most time-consuming function,
        #      timeit-testing has been used to select the
        #      most efficient implementation here.
        #      There is still room for improvement.
        # SEE testradius.py and testrange.py
        # TODO: apparently this comment is outdated already?
        x, y = self.position
        minX = max(0, x - radius)
        maxX = min(self.infoWorld["length"], x + radius + 1)
        # +1 since upper bound of range is exclusive
        minY = max(0, y - radius)
        maxY = min(self.infoWorld["length"], y + radius + 1)
        # print(minX, maxX, maxY, maxY, self.infoWorld["length"]);
        world_map = self.map
        occupied_y = self.occupiedY
        if condition is None:
            for x1 in range(minX, maxX):
                ys = occupied_y[x1]
                start = bisect_left(ys, minY)
                stop = bisect_right(ys, maxY - 1)
                for y_index in range(start, stop):
                    yield from world_map[x1][ys[y_index]].items()
        else:
            for x1 in range(minX, maxX):
                ys = occupied_y[x1]
                start = bisect_left(ys, minY)
                stop = bisect_right(ys, maxY - 1)
                for y_index in range(start, stop):
                    for object_id, obj in world_map[x1][ys[y_index]].items():
                        if condition(obj):
                            yield object_id, obj

    def Die(self) -> None:
        """deletes WorldObject instance from world."""
        self.dead = True
        self.DeleteObject(self.sim_id)

    def getDescriptor(self) -> dict[str, Any]:
        """return descriptive data for the gui,
        included by the world in World.getDescriptor.
        """
        return {
            "position": self.position,
            "id": self.sim_id,
            "sim_id": self.sim_id,
            "energy": self.energy,
            "age": self.age,
            "type": self.objectType,
        }

    def persist(self) -> dict[str, Any]:
        """returns JSON serializable object with all information
        needed to restore the state of the object"""
        return {
            "sim_id": self.sim_id,
            "type": self.objectType,
            "energy": self.energy,
            "age": self.age,
            "position": self.position,
            "source": self.source,
            "time": self.time,
        }

    def restore(self, obj: dict[str, Any]) -> None:
        """restores state of this objects from obj"""
        # Old savegames predate stable simulation IDs. In that case AddObject
        # has already assigned the replacement ID used by this restored world.
        self.sim_id = obj.get("sim_id", self.sim_id)
        self.age = obj["age"]
        self.energy = obj["energy"]
        self.position = obj["position"]
        self.time = obj["time"]

    def _AgeCheck(self) -> None:
        """virtual function, look in wesen or food"""
        assert not self.dead

    def _EnergyCheck(self) -> bool | None:
        """virtual function, look in wesen or food"""
        assert not self.dead
        return None

    def main(self) -> None:
        """run one turn of object code"""
        if not self.dead:
            self._EnergyCheck()
        if not self.dead:
            self.age += 1
            self._AgeCheck()
