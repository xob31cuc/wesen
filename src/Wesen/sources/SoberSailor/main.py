"""
the sober sailor is a smarter implementation of drunken sailor.
it searches food instead of only walking randomly.
"""

from __future__ import annotations

from random import choice
from typing import Any

from ...defaultwesensource import DefaultWesenSource


class WesenSource(DefaultWesenSource):
    def __init__(self, infoAllSource: dict[str, Any]) -> None:
        DefaultWesenSource.__init__(self, infoAllSource)
        self.randRange = [-1, 0, 1]
        self.minimalTime = 20

    def __str__(self) -> str:
        return "<Sober Sailor>"

    def sign(self, x: int) -> int:
        if x < 0:
            return -1
        if x > 0:
            return 1
        return 0

    def main(self) -> None:
        while self.time() > self.minimalTime:
            lookRange = self.closerLook()
            position = self.position()

            foodHere = [
                obj
                for obj in lookRange
                if obj["type"] == "food" and obj["position"] == position
            ]

            if foodHere:
                self.Eat(foodHere[0]["id"])
                continue

            foods = [obj for obj in lookRange if obj["type"] == "food"]

            if foods:
                # Nimm das erste Food, was auf dem Weg ist
                food = foods[0]
                dx = food["position"][0] - position[0]
                dy = food["position"][1] - position[1]

                # Immer geradeaus laufen
                if abs(dx) > abs(dy):
                    move = [self.sign(dx), 0]
                elif abs(dy) > abs(dx):
                    move = [0, self.sign(dy)]
                else:
                    move = [self.sign(dx), self.sign(dy)]

                self.Move(move)

            else:
                # Wenn kein Food hier ist, bewegt er sich wie DrunkenSailor
                if choice([True, False]):
                    self.Move([choice(self.randRange), 0])
                else:
                    self.Move([0, choice(self.randRange)])
