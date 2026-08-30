from __future__ import annotations

from functools import reduce
from math import atan2, cos, pi, sin
from typing import Any

from ...defaultwesensource import CloserLookDescriptor, DefaultWesenSource
from ...point import getDistInMaxMetric, getShortestTranslation
from . import helper


class WesenSource(DefaultWesenSource):
    def __init__(self, infoAllSource: dict[str, Any]) -> None:
        """Do all initialization stuff."""
        DefaultWesenSource.__init__(self, infoAllSource)
        self.infoAllSource = infoAllSource
        self.active = True
        reprFactor = 0.9
        self.minimumTime = 10
        self.minimumEnergyToEat = 0
        self.minimumEnergyToReproduce = 300 * reprFactor
        # self.minimumEnergyToReproduce = (reprFactor * 2 *
        # self.infoWesen["energy"]) / self.infoFood["count"];
        self.minimumEnergyToFight = self.minimumEnergyToReproduce * 0.75
        self.target: CloserLookDescriptor | None = None
        self.targetType: str | None = None
        self.forbiddenTargets: list[int] = []
        self.angle = 0.0
        self.first_move = True
        self.midPoint: list[int] | None = None
        self.state: Any = self.searchFood
        self.resumeState: Any = self.searchFood
        self.radius = 20

    def __str__(self) -> str:
        return "<Sorccerer>"

    def continueOnCircle(self) -> bool:
        r = self.radius
        delta_angle = 2 * pi / 50
        mid_point = self.midPoint
        assert mid_point is not None
        radius = getShortestTranslation(
            mid_point,
            self.position(),
            self.infoAllSource["world"]["length"],
        )
        self.angle = atan2(radius[1], radius[0]) + delta_angle
        move_pos = [
            int(mid_point[0] + r * cos(self.angle))
            % self.infoAllSource["world"]["length"],
            int(mid_point[1] + r * sin(self.angle))
            % self.infoAllSource["world"]["length"],
        ]
        oldPos = self.position()
        self.MoveToPosition(move_pos)
        return self.position() != oldPos

    def bestFoodInRange(
        self, foods: list[CloserLookDescriptor]
    ) -> CloserLookDescriptor | None:
        int(
            (self.time() - self.infoAllSource["time"]["eat"])
            / self.infoAllSource["time"]["move"]
        )
        # TODO movingRange is not used after assignment!
        suitableFoods = [f for f in foods if f["age"] > 100]
        reachableFoods = [
            f
            for f in suitableFoods
            if getDistInMaxMetric(
                self.position(),
                f["position"],
                self.infoAllSource["world"]["length"],
            )
        ]
        if len(reachableFoods) > 0:
            return max(reachableFoods, key=lambda f: f["energy"])
        else:
            return None

    def searchFood(self) -> None:
        foods = [o for o in self.range if o["type"] == "food"]
        if len(foods) > 0:
            self.state = self.protectFood
        else:
            self.midPoint = None
            if not helper.ScannerMove(self):
                self.state = "pass"

    def protectFood(self) -> None:
        foods = [o for o in self.range if o["type"] == "food"]
        if len(foods) == 0:
            self.state = self.searchFood
            return
        if not self.midPoint:
            totalEnergy = sum(map(lambda o: o["energy"], foods)) + 1
            # +1 to avoid divbyzero
            weighted_midpoint = reduce(
                lambda a, b: [
                    a[i] + float(b["energy"]) / float(totalEnergy) * b["position"][i]
                    for i in range(len(a))
                ],
                foods,
                [0.0, 0.0],
            )
            self.midPoint = [
                int(c) % self.infoAllSource["world"]["length"]
                for c in weighted_midpoint
            ]
        # print("midpoint:", self.midPoint);
        if self.energy() > 200:
            self.Reproduce()
        bestFood = self.bestFoodInRange(foods)
        if bestFood:
            if self.MoveToPosition(bestFood["position"]):
                self.Eat(bestFood["id"])
        if not self.continueOnCircle():
            self.state = "pass"

    def main(self) -> None:
        self.range = self.closerLook()
        self.state = self.resumeState
        while self.state != "pass":
            self.resumeState = self.state
            # print("main:", self.state.__name__);
            self.state()
