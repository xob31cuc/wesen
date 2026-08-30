"""The Food class, which is present in every simulation."""

from __future__ import annotations

from typing import Any

from numpy.random import random_sample

from ..point import getRandomPositionInRadius
from .base import WorldObject, WorldObjectContext


class Food(WorldObject):
    """Unlike wesen, who are programmable and capable of intelligence,
    food can only grow every turn and reproduce over distance.
    """

    def __init__(self, infoAllWorld: WorldObjectContext) -> None:
        """Initialize food growth, seeding, and lifetime parameters."""
        WorldObject.__init__(self, infoAllWorld)
        self.source = "food"
        self.seedrate = self.infoObject["seedrate"]
        self.growrate = self.infoObject["growrate"]
        self.rangeseed = self.infoRange["seed"]
        self.maxamount = self.infoObject["maxamount"]
        self.maxage = self.infoObject["maxage"]

    def __repr__(self) -> str:
        """Return a compact description of this food object's state."""
        return (
            f"<food sim_id={self.sim_id} growrate={self.growrate} "
            f"pos={self.position} energy={self.energy}>"
        )

    def getDescriptor(self) -> dict[str, Any]:
        """currently doing nothing than returning the WorldObjects getDescriptor."""
        return WorldObject.getDescriptor(self)

    def persist(self) -> dict[str, Any]:
        """returns JSON serializable object with all information
        needed to restore the state of the object"""
        d = WorldObject.persist(self)
        d.update(
            {
                "seedrate": self.seedrate,
                "growrate": self.growrate,
                "rangeseed": self.rangeseed,
                "maxamount": self.maxamount,
                "maxage": self.maxage,
            }
        )
        return d

    def restore(self, obj: dict[str, Any]) -> None:
        """restores the state of the food object"""
        WorldObject.restore(self, obj)
        self.seedrate = obj["seedrate"]
        self.growrate = obj["growrate"]
        self.rangeseed = obj["rangeseed"]
        self.maxamount = obj["maxamount"]
        self.maxage = obj["maxage"]

    def getEaten(self) -> int:
        """dies and returns previous energy amount."""
        energy: int = self.energy
        if not self.dead:
            self.Die()
        return energy

    def Grow(self) -> None:
        """increment energy by some amount."""
        self.energy += int(random_sample() * 2 * self.growrate)

    def Seed(self) -> Food:
        """create a new Food instance in seedrange."""
        infoFood = self.infoObject
        infoFood["energy"] = 1
        infoFood["position"] = getRandomPositionInRadius(
            self.position, self.rangeseed, self.infoWorld["length"]
        )
        newFood = self.AddObject(infoFood)
        assert isinstance(newFood, Food)
        newFood._eatFoodAtSamePlace()
        return newFood

    def _AgeCheck(self) -> None:
        """Remove this food when it reaches its configured maximum age."""
        WorldObject._AgeCheck(self)
        if self.age >= self.infoObject["maxage"]:
            self.Die()

    def _EnergyCheck(self) -> None:
        """Clamp this food's energy to its configured valid range."""
        WorldObject._EnergyCheck(self)
        if self.energy >= self.infoObject["maxamount"]:
            self.energy = self.infoObject["maxamount"]
        elif self.energy < 0:
            self.energy = 0
            # this happens only if one manipulates food via the GUI
            # TODO the GUI should be more careful and this raise an Error.
            print("warning: food energy lower than zero detected")

    def _hasTooMuchFoodNearby(self) -> bool:
        """return True as soon as there is a lot of food nearby."""
        for i, _ in enumerate(
            self.getRangeIterator(
                self.rangeseed, condition=lambda o: o.objectType == "food"
            )
        ):
            if i == 10:  # TODO make this number configurable!
                return True
        return False

    def _eatFoodAtSamePlace(self) -> None:
        """Eat Food at the same position whose id differs from this Food's."""
        for obj in [
            # The range iterator allows increasing this radius later.
            obj
            for oid, obj in self.getRangeIterator(
                0, condition=lambda o: o.objectType == "food"
            )
            if oid != self.sim_id
        ]:
            self.energy += obj.getEaten()

    def main(self) -> None:
        """randomly grow or seed, based on growrate and seedrate.
        When too old, die."""
        WorldObject.main(self)
        # handles age and low-energy death
        if not self.dead:
            if self.age > 10:  # TODO numbers should be a config option
                if random_sample() < self.seedrate:
                    if not self._hasTooMuchFoodNearby():
                        self.Seed()
            self.Grow()
