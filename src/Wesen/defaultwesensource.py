"""defines an interface for AI code"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, TypedDict


class LookDescriptor(TypedDict):
    """Information returned by the inexpensive ``look`` capability."""

    position: list[int]
    type: str
    id: int


class CloserLookDescriptor(LookDescriptor):
    """Complete object information returned by ``closerLook``."""

    energy: int
    age: int
    time: int
    source: str


class DefaultWesenSource:
    """each AI code should subclass this class."""

    # Wesen.PutInterface supplies these callables after source construction.
    id: Callable[[], int]
    age: Callable[[], int]
    position: Callable[[], list[int]]
    energy: Callable[[], int]
    time: Callable[[], int]
    look: Callable[[], list[LookDescriptor]]
    closerLook: Callable[[], list[CloserLookDescriptor]]
    Move: Callable[[Sequence[int | float]], bool]
    MoveToPosition: Callable[[Sequence[int | float]], bool]
    Talk: Callable[[int, Any], bool]
    Eat: Callable[[int], bool]
    Reproduce: Callable[[], int]
    Attack: Callable[[int], bool]
    Vomit: Callable[[int], bool]
    Donate: Callable[[int, int], bool]
    Broadcast: Callable[[Any], bool]

    def __init__(self, infoAllSource: dict[str, Any]) -> None:
        """links a few variables to infoAllSource contents."""
        self.infoSource = infoAllSource["source"]
        self.infoWesen = infoAllSource["wesen"]
        self.infoFood = infoAllSource["food"]
        self.infoWorld = infoAllSource["world"]
        self.infoTime = infoAllSource["time"]
        self.infoRange = infoAllSource["range"]
        self.worldlength = self.infoWorld["length"]
        self.source = self.infoSource["source"]

    def getDescriptor(self) -> dict[Any, Any]:
        """currently unused, designed for debugging and UI"""
        return {}

    def persist(self) -> dict[Any, Any]:
        """returns JSON serializable object with all information
        needed to restore the state of the object

        subclasses need to add all information they need to restore their state"""
        return {}

    def restore(self, obj: dict[Any, Any]) -> None:
        """given a dict obj as returned by persist,
        to restore internal state of AI"""

    def Receive(self, message: Any) -> None:
        """message should be a dict"""

    def main(self) -> None:
        """called every turn"""
        raise NotImplementedError("Every Wesen Source (AI code) needs a main method")
