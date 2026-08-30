"""The class for all data and operations a single Wesen has"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Sequence
from copy import deepcopy
from functools import wraps
from typing import Any

from ..defaultwesensource import CloserLookDescriptor, LookDescriptor
from .base import WorldObject, WorldObjectContext


class RuleException(Exception):
    """This exception is thrown whenever a wesen source
    violates the rules of the game."""

    def __init__(self, ruleDescription: str) -> None:
        """Create an exception describing the violated simulation rule."""
        super().__init__(ruleDescription)


class _ReplayWesenSource:
    """Inert source state holder used while applying replay snapshots."""

    def __init__(self) -> None:
        """Initialize an empty persisted AI state."""
        self._state: dict[str, Any] = {}

    def getDescriptor(self) -> dict[Any, Any]:
        """Return the empty UI descriptor used during replay."""
        return {}

    def persist(self) -> dict[Any, Any]:
        """Return the currently restored AI state."""
        return self._state

    def restore(self, state: dict[Any, Any]) -> None:
        """Replace the inert AI state with a deep copy of ``state``."""
        self._state = deepcopy(state)

    def Receive(self, _message: Any) -> None:
        """Ignore messages while replaying recorded state."""
        return None

    def main(self) -> None:
        """Reject attempts to execute AI logic during replay."""
        raise RuntimeError("Wesen source AI must not run during replay")


class Wesen(WorldObject):
    """Wesen(infoObject) creates a new Wesen instance.
    infoObject is a Dictionary of Dictionaries, time,range,world,etc.
    """

    # initialization

    def __init__(self, infoAllObject: WorldObjectContext) -> None:
        """imports the sourcecode of WesenSource and links the capabilities."""
        WorldObject.__init__(self, infoAllObject)
        self.infoTime = infoAllObject["time"]
        self.source = self.infoObject["source"]
        if infoAllObject.get("load_source", True):
            # TODO one can probably avoid multiple imports (if not already)
            WesenSource = importlib.import_module(
                "..sources." + self.source + ".main", __package__
            ).WesenSource
            infoSource = {"source": self.source}
            infoSourceWorld = self.infoWorld.copy()
            del infoSourceWorld["objects"]
            del infoSourceWorld["AddObject"]
            del infoSourceWorld["DeleteObject"]
            infoAllSource = {
                "world": infoSourceWorld,
                "source": infoSource,
                "time": self.infoTime,
                "range": self.infoRange,
                "wesen": self.infoObject,
                "food": infoAllObject["food"],
            }
            self.wesenSource = WesenSource(infoAllSource)
        else:
            self.wesenSource = _ReplayWesenSource()
        self.Receive: Callable[[Any], Any]
        self.PutInterface(self.wesenSource)

    def __repr__(self) -> str:
        """Return a compact description of this Wesen's simulation state."""
        return (
            f"<wesen sim_id={self.sim_id} pos={self.position} "
            f"energy={self.energy} source={str(self.wesenSource)}>"
        )

    def PutInterface(self, source: Any) -> None:
        """maps the source functions to the corresponding wesen functions."""
        source.id = self.getId
        source.age = self.getAge
        source.position = self.getPosition
        source.energy = self.getEnergy
        source.time = self.getTime
        source.look = self._sourceAction("Look", self.look)
        source.closerLook = self._sourceAction("CloserLook", self.closerLook)
        source.Move = self._sourceAction("Move", self.Move)
        source.MoveToPosition = self._sourceAction(
            "MoveToPosition", self.MoveToPosition
        )
        source.Talk = self._sourceAction("Talk", self.Talk)
        source.Eat = self._sourceAction("Eat", self.Eat)
        source.Reproduce = self._sourceAction("Reproduce", self.Reproduce)
        source.Attack = self._sourceAction("Attack", self.Attack)
        source.Vomit = self._sourceAction("Vomit", self.Vomit)
        source.Donate = self._sourceAction("Donate", self.Donate)
        source.Broadcast = self._sourceAction("Broadcast", self.Broadcast)
        self.Receive = source.Receive

    def _sourceAction(
        self, name: str, action: Callable[..., Any]
    ) -> Callable[..., Any]:
        """Wrap an AI-visible action with command/result instrumentation."""

        @wraps(action)
        def recorded(*args: Any, **kwargs: Any) -> Any:
            """Execute an action and optionally emit separate semantic data."""
            recorder = self.recorder
            try:
                result = action(*args, **kwargs)
            except Exception as error:
                if recorder is not None:
                    recorder.semantic_event(
                        "source_action",
                        turn=self.getTurn(),
                        actor=self.sim_id,
                        name=name,
                        args=list(args),
                        kwargs=kwargs,
                        result=False,
                        error=f"{type(error).__name__}: {error}",
                    )
                raise
            if recorder is not None:
                recorder.semantic_event(
                    "source_action",
                    turn=self.getTurn(),
                    actor=self.sim_id,
                    name=name,
                    args=list(args),
                    kwargs=kwargs,
                    result=result,
                )
            return result

        return recorded

    # small capabilites, no time cost

    def getTime(self) -> int:
        """returns time left to do stuff (for free)"""
        return self.time

    def getEnergy(self) -> int:
        """returns energy left (for free)"""
        return self.energy

    def getPosition(self) -> list[int]:
        """returns own position (for free)"""
        return self.position

    def getId(self) -> int:
        """returns own object id (for free)"""
        return self.sim_id

    def getAge(self) -> int:
        """returns own age (for free)"""
        return self.age

    # standard capabilities

    def look(self) -> list[LookDescriptor]:
        """returns a list of dictionaries with all visible WorldObjects position,
        objecttype and stable simulation id.
        """
        if self._UseTime("look"):
            return [
                {"position": o.position, "type": o.objectType, "id": oid}
                for oid, o in self.getRangeIterator(
                    self.infoRange["look"], condition=lambda x: self != x
                )
            ]
        else:
            return []

    def closerLook(self) -> list[CloserLookDescriptor]:
        """returns look() and a few more information, as
        energy, age, time, source (which equals to friend/foe).
        """
        if self._UseTime("closerlook"):
            return [
                {
                    "position": o.position,
                    "type": o.objectType,
                    "id": oid,
                    "energy": o.energy,
                    "age": o.age,
                    "time": o.time,
                    "source": o.source,
                }
                for oid, o in self.getRangeIterator(
                    self.infoRange["closer_look"],
                    condition=lambda x: self != x,
                )
            ]
        else:
            return []

    def Move(self, direction: Sequence[int | float]) -> bool:
        """moves the wesen into a specified direction,
        returns true if any position change happened."""
        if self.dead:
            return False
        direction = [int(dc) for dc in direction]
        # the following code is a more time-efficient way to do
        # usedTime = self.infoTime["move"]*(abs(direction[0])+abs(direction[1]));
        if direction[0] < 0:
            if direction[1] < 0:
                usedTime = self.infoTime["move"] * -1 * (direction[0] + direction[1])
            elif direction[1] > 0:
                usedTime = self.infoTime["move"] * (direction[1] - direction[0])
            else:
                usedTime = self.infoTime["move"] * -1 * direction[0]
        elif direction[0] > 0:
            if direction[1] < 0:
                usedTime = self.infoTime["move"] * (direction[0] - direction[1])
            elif direction[1] > 0:
                usedTime = self.infoTime["move"] * (direction[1] + direction[0])
            else:
                usedTime = self.infoTime["move"] * direction[0]
        else:
            if direction[1] < 0:
                usedTime = self.infoTime["move"] * -1 * direction[1]
            elif direction[1] > 0:
                usedTime = self.infoTime["move"] * direction[1]
            else:
                return False
        if self.time >= usedTime:
            self.time -= usedTime
            oldPos = self.position
            self.position = [
                (pc + dc) % self.infoWorld["length"]
                for (pc, dc) in zip(self.position, direction, strict=True)
            ]
            self.UpdatePos(self.sim_id, oldPos, self.getDescriptor())
            return True
        else:
            return False

    def MoveToPosition(self, newPosition: Sequence[int | float]) -> bool:
        """moves the wesen to a specified position"""
        newPosition = [int(pc) for pc in newPosition]
        while self.position != newPosition:
            if not self.Move(
                [
                    -1 if nc < pc else 1 if nc > pc else 0
                    for (nc, pc) in zip(newPosition, self.position, strict=True)
                ]
            ):
                return False
        return True

    def Talk(self, wesenid: int, message: Any) -> bool:
        """calls Receive(message) in the wesen specified by wesenid when in range."""
        if self._UseTime("talk"):
            for _oid, o in self.getRangeIterator(
                self.infoRange["look"],
                condition=lambda candidate: (
                    candidate.sim_id == wesenid and candidate.objectType == "wesen"
                ),
            ):
                o.wesenSource.Receive(message)
                return True
        return False

    def Eat(self, foodid: int) -> bool:
        """Eat the food with stable simulation id ``foodid``."""
        if self.dead:
            return False
        if foodid not in self.worldObjects:
            raise RuleException("Tried to eat non-existing food")
        o = self.worldObjects[foodid]
        if (o.position == self.position) and (o.objectType == "food"):
            if self._UseTime("eat"):
                self.energy += o.getEaten()
                return True
        else:
            if o.position != self.position:
                raise RuleException(
                    "In order to eat something, one has to be at the same "
                    "position. Keep in mind that wesen move and you have to "
                    "look where they are each turn, as the information from "
                    "looking around becomes stale quickly!"
                )
            if o.objectType != "food":
                raise RuleException("In order to eat something, it has to be food.")
        return False

    def Reproduce(self) -> int:
        """Create a new Wesen instance with the same source and the specified energy
        which is then subtracted from the reproducing wesen.
        """
        if self.dead:
            return False
        if self._UseTime("reproduce"):
            childEnergy = self.energy // 2
            infoWesen = self.infoObject.copy()
            infoWesen["energy"] = childEnergy
            infoWesen["source"] = self.source
            infoWesen["position"] = self.position
            child = self.AddObject(infoWesen)
            self.energy -= childEnergy
            self.age = 0
            self._EnergyCheck()
            return child.sim_id
        return False

    def Attack(self, wesenid: int) -> bool:
        """attacks the wesen specified by wesenid when it's at the same position.
        the energy of the enemy is subtracted from the own energy,
        so the one who had more energy than his enemy can survive.
        The other Wesen dies.
        """
        if self.dead:
            return False
        try:
            o = self.worldObjects[wesenid]
        except KeyError as error:
            raise RuleException(
                f"May not attack non-existent enemy with id '{wesenid}'"
            ) from error
        if (o.objectType == "wesen") and (o.position == self.position):
            if self._UseTime("attack"):
                if self.recorder is not None:
                    self.recorder.semantic_event(
                        "attack",
                        turn=self.getTurn(),
                        attacker_source=self.source,
                        target_source=o.source,
                    )
                self.energy -= int(
                    o.getAttacked(self.energy, killer_source=self.source) * 0.5
                )
                return not self._EnergyCheck(killer_source=o.source)
        return False

    def getAttacked(self, energy: int, killer_source: str | None = None) -> int:
        """Apply attack energy and attribute a resulting death when possible."""
        previousEnergy = self.energy
        self.energy -= int(energy * 0.75)
        self._EnergyCheck(killer_source=killer_source)
        return previousEnergy

    # advanced capabilites

    def Vomit(self, energy: int, deathOnLowEnergy: bool = True) -> bool:
        """turns the given energy into strange food
        (other growing and seeding behaviour).
        the energy is subtracted from the wesen"""
        if self.dead:
            return False
        if self._UseTime("vomit"):
            if energy > self.energy:
                energy = self.energy
                if deathOnLowEnergy:
                    self.Die()
            if not energy <= 0:
                # TODO the magic numbers here should be configurable
                infoFood = {
                    "energy": energy,
                    "position": self.position,
                    "growrate": 1,
                    "seedrate": 0.001,
                    "maxamount": energy + 1000,
                    "maxage": 1000,
                    "type": "food",
                }
                self.AddObject(infoFood)
                self.energy -= energy
                return True
        return False

    def Donate(self, energy: int, wesenid: int) -> bool:
        """transfer energy from this wesen to another specified by wesenid"""
        if self.dead:
            return False
        o = self.worldObjects[wesenid]
        if (o.objectType == "wesen") and (o.position == self.position):
            if self._UseTime("donate"):
                if energy > self.energy:
                    energy = self.energy
                if not energy <= 0:
                    o.energy += energy
                    self.energy -= energy
                    self._EnergyCheck()
                    return True
        return False

    def Broadcast(self, message: Any) -> bool:
        """calls Talk(message) with all wesen in range"""
        if self.dead:
            return False
        if self._UseTime("broadcast"):
            for _, o in self.getRangeIterator(
                self.infoRange["talk"],
                condition=lambda x: self != x and x.objectType == "wesen",
            ):
                o.Receive(message)
            return True
        return False

    def Die(self, killer_source: str | None = None) -> None:
        """Record a death, emit remaining energy, and remove this Wesen."""
        if self.dead:
            return
        if self.recorder is not None:
            self.recorder.semantic_event(
                "death",
                turn=self.getTurn(),
                dead_source=self.source,
                killer_source=killer_source,
            )
        if self.energy:
            self.Vomit(self.energy, deathOnLowEnergy=False)
        WorldObject.Die(self)

    # general methods

    def getDescriptor(self) -> dict[str, Any]:
        """returns a dictionary
        with descriptive information about the wesen for the GUI"""
        descriptor = {
            "source": self.source,
            "sourcedescriptor": self.wesenSource.getDescriptor(),
        }
        descriptor.update(WorldObject.getDescriptor(self))
        return descriptor

    def persist(self) -> dict[str, Any]:
        """returns JSON serializable object with all information
        needed to restore the state of the object"""
        d = WorldObject.persist(self)
        d.update(
            {
                "wesensource": self.wesenSource.persist(),
                "maxage": self.infoObject["maxage"],
            }
        )
        return d

    def restore(self, obj: dict[str, Any]) -> None:
        """Restore dynamic Wesen, ownership, and inert source state."""
        WorldObject.restore(self, obj)
        if "maxage" in obj:
            self.infoObject["maxage"] = obj["maxage"]
        self.wesenSource.restore(obj.get("wesensource", {}))

    def _UseTime(self, function: str) -> bool:
        """if the wesen has enough time,
        return true and subtract the time needed for function;
        else return false.
        """
        usedTime = self.infoTime[function]
        if self.time >= usedTime:
            self.time -= usedTime
            return True
        return False

    def _AgeCheck(self) -> None:
        """kills the wesen if it's too old"""
        WorldObject._AgeCheck(self)
        if self.age > self.infoObject["maxage"]:
            self.Die()

    def _EnergyCheck(self, killer_source: str | None = None) -> bool:
        """Kill a depleted Wesen and retain known source attribution."""
        WorldObject._EnergyCheck(self)
        if self.energy <= 0:
            self.Die(killer_source=killer_source)
            return True
        return False

    def main(self) -> None:
        """runs one turn of wesen code and it's AI code"""
        WorldObject.main(self)
        if not self.dead:
            self.energy -= 1
            self.time = min(self.time + self.infoTime["init"], self.infoTime["max"])
            self.wesenSource.main()
