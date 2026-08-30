from __future__ import annotations

from collections.abc import Callable
from random import randint
from typing import TYPE_CHECKING

from ...defaultwesensource import CloserLookDescriptor

if TYPE_CHECKING:
    from Wesen.sources.Rincewind.main import WesenSource

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
    result = False
    target = self.target
    if target is None:
        return False
    self.MoveToPosition(target["position"])
    if target["position"] == self.position() and self.time() >= actionTime:
        result = Action(self, target)
        if not result:
            if target["id"] not in self.forbiddenTargets:
                self.forbiddenTargets.append(target["id"])
        self.target = None
    return result


def EatObject(self: WesenSource, object: Descriptor) -> bool:
    return self.Eat(object["id"]) or True


def AttackObject(self: WesenSource, object: Descriptor) -> bool:
    return self.Attack(object["id"]) or True


def EatTarget(self: WesenSource) -> bool:
    return CatchTarget(self, EatObject, self.infoTime["attack"] + 1)


def AttackTarget(self: WesenSource) -> bool:
    return CatchTarget(self, AttackObject, self.infoTime["eat"] + 1)


def lookForTarget(
    self: WesenSource,
    lookRange: list[Descriptor],
    objectType: str,
    objectCondition: Callable[[WesenSource, Descriptor], bool],
    objectFitness: Callable[[Descriptor], int],
) -> bool:
    matchingObjects = []
    for object in lookRange:
        if object["type"] == objectType:
            if objectCondition(self, object):
                matchingObjects.append(object)
    if matchingObjects:
        matchingObjects.sort(key=objectFitness)
        self.target = matchingObjects[0]
        self.targetType = objectType
        return True
    else:
        return False


def acceptableFood(self: WesenSource, object: Descriptor) -> bool:
    if object["energy"] >= self.minimumEnergyToEat:
        if object["id"] in self.forbiddenTargets:
            del self.forbiddenTargets[self.forbiddenTargets.index(object["id"])]
        return True
    else:
        return False


def foodFitness(a: Descriptor) -> int:
    return a["energy"]


def acceptableEnemy(self: WesenSource, object: Descriptor) -> bool:
    if object["source"] != self.source:
        if object["energy"] <= (self.energy() + self.minimumEnergyToFight):
            return True
        else:
            self.minimumEnergyToFight = int(
                ((self.energy() + self.minimumEnergyToFight) + object["energy"]) / 2
            )
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
    self: WesenSource,
    lookRange: list[Descriptor] | None = None,
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


def ScannerMove(self: WesenSource) -> bool:
    return self.Move([2, int(randint(0, 3) / 2)])
