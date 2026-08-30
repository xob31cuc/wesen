"""
the drunken sailor is a simple implementation of random movement.
"""

from __future__ import annotations

from random import choice
from typing import Any

from ...defaultwesensource import DefaultWesenSource


class WesenSource(DefaultWesenSource):
    def __init__(self, infoAllSource: dict[str, Any]) -> None:
        """Do all initialization stuff."""
        DefaultWesenSource.__init__(self, infoAllSource)
        self.randRange = [-1, 0, 1]

    def __str__(self) -> str:
        return "<Sailor, hasn't been on any boat yet>"

    def main(self) -> None:
        while self.time() > self.infoTime["move"]:
            self.Move([choice(self.randRange), choice(self.randRange)])
            edible = [
                o
                for o in self.closerLook()
                if o["type"] == "food" and o["position"] == self.position()
            ]
            if edible:
                self.Eat(edible[0]["id"])
