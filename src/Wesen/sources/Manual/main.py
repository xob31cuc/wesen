"""
for developers: manual (console) wesen programming
"""

from __future__ import annotations

import re
import readline
import sys
from typing import Any

from ...defaultwesensource import DefaultWesenSource


class WesenSource(DefaultWesenSource):
    def __init__(self, infoAllSource: dict[str, Any]) -> None:
        DefaultWesenSource.__init__(self, infoAllSource)
        self.exitPattern = re.compile("^(x|q|quit|exit)$")
        self.commands = ["x", "q", "quit", "exit"]
        readline.set_completer(Completer(self.commands).complete)
        readline.parse_and_bind("tab: complete")

    def getInput(self) -> Any:
        """pull a string from somewhere - usually raw_input()"""
        return eval(input("\n> "))

    def main(self) -> None:
        while True:
            try:
                userInput = self.getInput()
            except EOFError:
                break
            except KeyboardInterrupt:
                break
            else:
                if self.exitPattern.match(userInput):
                    sys.exit()
                else:
                    exec(userInput)


class Completer:
    def __init__(self, commands: list[str]) -> None:
        self.commands = [command + "()" for command in commands]

    def complete(self, text: str, state: int) -> str | None:
        matches = self.method_matches(text)
        try:
            return matches[state]
        except IndexError:
            return None

    def method_matches(self, text: str) -> list[str]:
        matches: list[str] = []
        if len(text) == 0:
            return self.commands
        n = len(text)
        for command in self.commands:
            if command[:n] == text:
                matches.append(command)
        return matches
