from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from numpy.random import randint, uniform

from ...defaultwesensource import CloserLookDescriptor
from ...point import getDistInMaxMetric

if TYPE_CHECKING:
    from Wesen.sources.Dwarf.main import WesenSource

type Descriptor = CloserLookDescriptor

# TODO try to extract a sensible helper.py and move some of this back to the
# main source.
# TODO change most magic numbers to something computed from the game's time
# constraints
#     like food growth, moving time, etc.


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
    objectFitness: Callable[[Descriptor], int | float],
) -> bool:
    # TODO now ignores objectFitness, uses positionFitness instead;
    matchingObjects = [
        o
        for o in lookRange
        if (o["type"] == objectType and objectCondition(self, o))
    ]
    if matchingObjects:
        matchingObjects.sort(
            key=lambda o: getDistInMaxMetric(
                o["position"],
                self.position(),
                self.infoAllSource["world"]["length"],
            )
        )
        # self.target = matchingObjects[randint(len(matchingObjects))];
        self.target = matchingObjects[0]
        self.targetType = objectType
        return True
    else:
        self.target = None
        self.targetType = None
        return False


def acceptableFood(self: WesenSource, o: Descriptor) -> bool:
    if o["age"] >= self.minimalGardenAge:
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
        # else:
        # self.minimumEnergyToFight = int(((self.energy() +
        # self.minimumEnergyToFight) + o["energy"]) / 2); #TODO improve magic
    return False


def threateningEnemy(self: WesenSource, o: Descriptor) -> bool:
    if o["source"] == self.source:
        return False
    else:
        return o["energy"] > self.energy() * 1.2
        # TODO remove magic


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


def lookForThreat(
    self: WesenSource, lookRange: list[Descriptor] | None = None
) -> bool:
    if not lookRange:
        lookRange = self.closerLook()
    return lookForTarget(self, lookRange, "wesen", threateningEnemy, enemyFitness)


def lookAtYoungGarden(
    self: WesenSource,
    lookRange: list[Descriptor] | None = None,
) -> bool:
    if not lookRange:
        lookRange = self.closerLook()
    foodCount = 0
    for o in lookRange:
        if o["type"] == "food" and o["age"] <= self.minimalGardenAge:
            foodCount += 1
    return foodCount > 10
    # TODO magic number


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


def ScannerMove(
    self: WesenSource,
    scanVector: tuple[float, float] | list[float] = (1, 0),
    scanSpeed: int = 3,
    randomization: float = 0.2,
) -> None:
    self.Move(
        [
            int(randomization * uniform(-1, 1) + scanSpeed * coordinate)
            for coordinate in scanVector
        ]
    )


def Flee(self: WesenSource) -> None:
    target = self.target
    if target is None:
        return
    for _i in range(0, 5):
        ScannerMove(
            self,
            scanVector=[
                -1 * (tc - pc)
                for (tc, pc) in zip(target["position"], self.position(), strict=True)
            ],
        )


def seedOut(self: WesenSource) -> list[bool]:
    newFoodObjects = []
    for _i in range(0, 3):
        newFoodObjects.append(self.Vomit(1))
        for _j in range(0, 4):
            DrunkenSailor(self)
    return newFoodObjects
