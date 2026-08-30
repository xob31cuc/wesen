"""This is a place to collect helpful functions,
which sometimes are more like methods,
such that the AI main method
contains more high-level strategy.

Beware: this code is likely to move somewhere else."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from numpy.random import randint

from ...defaultwesensource import CloserLookDescriptor

if TYPE_CHECKING:
    from Wesen.sources.Nightwatch.main import WesenSource

type Descriptor = CloserLookDescriptor


def DrunkenSailor(self: WesenSource) -> None:
    self.Move([randint(-1, 1), randint(-1, 1)])


def recoverAge(self: WesenSource) -> None:
    if self.age() + 5 > self.infoWesen["maxage"]:
        child = self.Reproduce()
        self.Donate(self.energy(), child)


def CatchTarget(
    self: WesenSource,
    Action: Callable[[WesenSource, Descriptor], bool],
    actionTime: int,
) -> bool:
    targ = self.target
    if targ is None:
        return False
    if self.MoveToPosition(targ["position"]):
        if targ["position"] == self.position() and self.time() >= actionTime:
            self.target = None
            if Action(self, targ):
                return True
            elif targ["id"] not in self.forbiddenTargets:
                self.forbiddenTargets.append(targ["id"])
    return False


def EatObject(self: WesenSource, o: Descriptor) -> bool:
    return self.Eat(o["id"])


def AttackObject(self: WesenSource, o: Descriptor) -> bool:
    return self.Attack(o["id"])


def EatTarget(self: WesenSource) -> bool:
    return CatchTarget(self, EatObject, self.infoTime["eat"] + 1)


def AttackTarget(self: WesenSource) -> bool:
    return CatchTarget(self, AttackObject, self.infoTime["attack"] + 1)


def lookForTarget(
    self: WesenSource,
    lookRange: list[Descriptor],
    objectType: str,
    objectCondition: Callable[[WesenSource, Descriptor], bool],
    objectFitness: Callable[[Descriptor], int],
) -> bool:
    matchingObjects = [
        o
        for o in lookRange
        if (o["type"] == objectType and objectCondition(self, o))
    ]
    if matchingObjects:
        if self.target and self.targetType == objectType:
            for o in matchingObjects:
                if o["id"] == self.target["id"]:
                    self.target = o
                    return True
        matchingObjects.sort(key=objectFitness)
        self.target = matchingObjects[0]
        self.targetType = objectType
        return True
    else:
        self.target = None
        self.targetType = None
        return False


def acceptableFood(self: WesenSource, o: Descriptor) -> bool:
    if o["energy"] >= self.minimumEnergyToEat:
        if o["id"] in self.forbiddenTargets:
            del self.forbiddenTargets[self.forbiddenTargets.index(o["id"])]
        return True
    else:
        return False


def foodFitness(a: Descriptor) -> int:
    return a["energy"]


def acceptableEnemy(self: WesenSource, o: Descriptor) -> bool:
    if o["source"] != self.source:
        if o["energy"] <= (self.energy() + self.minimumEnergyToFight):
            return True
        else:
            self.minimumEnergyToFight = (
                self.energy() + self.minimumEnergyToFight + o["energy"]
            ) // 2
            return False
    else:
        return False


def enemyFitness(a: Descriptor) -> int:
    return a["energy"]


def lookForFoodTarget(
    self: WesenSource,
    lookRange: list[Descriptor] | None = None,
) -> bool:
    if not lookRange:
        lookRange = self.closerLook()
    return lookForTarget(self, lookRange, "food", acceptableFood, foodFitness)


def lookForEnemyTarget(
    self: WesenSource, lookRange: list[Descriptor] | None = None
) -> bool:
    if not lookRange:
        lookRange = self.closerLook()
    return lookForTarget(self, lookRange, "wesen", acceptableEnemy, enemyFitness)


def HandleTarget(self: WesenSource) -> bool:
    if self.target:
        if self.targetType == "food":
            return EatTarget(self)
        elif self.targetType == "wesen":
            return AttackTarget(self)
        else:
            return False
    else:
        return False


def ScannerMove(self: WesenSource) -> None:
    self.Move([2, int(randint(0, 3) / 2)])
