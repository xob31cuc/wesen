"""Example code, don't call.

For more examples, see the subfolders of the sources folder.

For more information on the interface,
take a look at Wesen.PutInterface in wesen.py"""

from __future__ import annotations

from typing import Any

from Wesen.defaultwesensource import DefaultWesenSource


class WesenSource(DefaultWesenSource):
    """this is a template to your own wesen sources."""

    def __init__(self, infoAllSource: dict[str, Any]) -> None:
        """Do all initialization stuff."""
        DefaultWesenSource.__init__(self, infoAllSource)

    def __str__(self) -> str:
        """Give yourself an awesome string representation,
        which will only show up in debug information."""
        return "<unspecified WesenSource>"

    def getDescriptor(self) -> dict[Any, Any]:
        """If you use some other GUI than the standard,
        this descriptive information might show up there.
        Usually, you can just omit this method."""
        return {}

    def Receive(self, message: dict[str, str]) -> None:
        """called when the wesen listens to a message.

        message should be a dictionary,
        but there is no unified protocol.
        """

    def main(self) -> None:
        """A.I. code here, this method is run every turn.
        Please try to write code with low runtime complexity.
        """
