"""This module contains all methods related to displaying text in the gui,
such as the Text GuiObject subclass and the TextPrinter class"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from OpenGL.GL import (
    GL_COMPILE,
    glCallLists,
    glEndList,
    glGenLists,
    glListBase,
    glNewList,
    glPopMatrix,
    glPushMatrix,
    glRasterPos,
    glTranslatef,
)
from OpenGL.GLUT import GLUT_BITMAP_8_BY_13, glutBitmapCharacter

from .object import GuiObject

if TYPE_CHECKING:
    from Wesen.gui.basicgui import BasicGUI
    from Wesen.world import World


class Text(GuiObject):
    """A Text object displays world.stats"""

    def __init__(self, gui: BasicGUI, world: World) -> None:
        """Initialize the statistics display for ``world``."""
        GuiObject.__init__(self, gui)
        self.world = world
        self.printer = TextPrinter()
        self.givenText: str | None = None
        # TODO replace this mechanism by something else

    def Print(
        self, line: str
    ) -> None:  # TODO replace this mechanism by something else
        """there's a single place where this line is shown.
        Call Print(line) again and the previous line is removed."""
        self.givenText = line

    def Reshape(self, x: int, y: int) -> None:
        """Corrects content sizes after changing GuiObject size"""
        GuiObject.Reshape(self, x, y)
        self.printer.Reshape(x, y)

    def DrawGameStats(self) -> None:
        """Print world.stats"""
        p = self.printer
        statString = "%-20s | %9s | %9s | %14s |\n"
        lines = [statString % ("", "energy", "count", "energy/object")]
        for source in sorted(self.world.stats.keys()):
            energy = self.world.stats[source]["energy"]
            count = self.world.stats[source]["count"]
            if count == 0:
                perWesen = 0
            else:
                perWesen = energy // count
            lines.append(statString % (source, energy, count, perWesen))
        p.Print("".join(lines))

    def DrawEngineStats(self) -> None:
        """Print some information about the game engine,
        such as fps (frames per second), number of turns, etc."""
        p = self.printer
        status = "paused" if self.gui.pause else "running"
        p.Print(
            f"{status}\n\n\n{self.gui.fps:3.1f} fps,  "
            f"{self.world.turns:8d} turns\n\n"
        )
        # p.Print("manual slowdown: %3d percent" %
        # (int(100.0/self.gui.speed)));

    def DrawGivenText(self) -> None:  # TODO replace this mechanism by something else
        """Draws the last text given previously by Print(line)"""
        if self.givenText is not None:
            self.printer.Print("\n")
            self.printer.Print(self.givenText)

    def Draw(self) -> None:
        """Draw the frame, engine statistics, and current message."""
        GuiObject.Draw(self)
        self.printer.ResetRaster()
        self.DrawEngineStats()
        self.DrawGameStats()
        self.DrawGivenText()


class TextPrinter:
    """A printer that uses OpenGL to draw strings.
    Use ResetRaster() and then Print(text)."""

    _fontListBase: int | None = None

    def __init__(self) -> None:
        """Initialize raster positioning and shared bitmap-font lists."""
        if TextPrinter._fontListBase is None:
            TextPrinter._fontListBase = self._BuildFontLists()
        self.fontListBase = TextPrinter._fontListBase
        self.x: float = (
            0.0  # TODO x currently unused, results in suboptimal resizing
        )
        self.y = 0.03  # TODO where does the magic number come from?
        self.rasterPos: float = 0.0
        self.ResetRaster()

    @staticmethod
    def _BuildFontLists() -> int:
        """Compile the GLUT bitmap font once for batched string drawing."""
        base = glGenLists(256)
        for character in range(256):
            glNewList(base + character, GL_COMPILE)
            glutBitmapCharacter(GLUT_BITMAP_8_BY_13, character)
            glEndList()
        return cast(int, base)

    def ResetRaster(self) -> None:
        """Call each frame before any Print()"""
        self.rasterPos = self.y
        self.Print("\n")

    def Reshape(self, x: int, y: int) -> None:
        """Gets into good shape again"""
        self.x = x
        self.y = 30 / y  # TODO where does the magic number come from?

    def Print(self, text: str) -> None:
        """Print(String text) prints text to the screen"""
        glPushMatrix()
        glTranslatef(0.02, 0.96, 0.0)  # TODO where does the magic number come from?
        lines = text.split("\n")
        last_line = len(lines) - 1
        glListBase(self.fontListBase)
        for index, line in enumerate(lines):
            if line:
                try:
                    encoded_line = line.encode("latin-1")
                except UnicodeEncodeError:
                    # FreeGLUT renders characters outside its table as asterisks.
                    encoded_line = bytes(
                        ord(character) if ord(character) < 256 else ord("*")
                        for character in line
                    )
                glCallLists(encoded_line)
            if index != last_line:
                self.rasterPos -= self.y
                glRasterPos(0, self.rasterPos)
        glPopMatrix()
