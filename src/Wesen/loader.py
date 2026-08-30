"""The Loader function determines which configfile to use
and interprets command-line arguments.
It makes sure that the configured wesen sources exist.
It then runs a Wesend instance."""

from __future__ import annotations

import importlib
import sys
from argparse import Action, ArgumentParser
from collections.abc import Sequence
from os import mkdir
from os.path import exists, expanduser, join
from typing import TYPE_CHECKING, Any

from .configed import ConfigEd
from .defaults import DEFAULT_CONFIGFILE
from .replay.replayer import ReplayError
from .strings import (
    STRING_USAGE_CONFIGFILE,
    STRING_USAGE_DEFAULTCONFIG,
    STRING_USAGE_DESCRIPTION,
    STRING_USAGE_EDITCONFIG,
    STRING_USAGE_EPILOG,
    STRING_USAGE_OVERWRITE,
    STRING_USAGE_PRINTCONFIG,
    STRING_USAGE_RESUME,
    VERSIONSTRING,
)
from .wesend import Wesend

if TYPE_CHECKING:
    from argparse import Namespace


def Loader(run_immediately: bool = True) -> Wesend | None:
    """Calling a Loader object will start a Wesen simulation,
    if the found configuration allows it.

    First, looks for the config file location
    provided by command-line (or using a fallback).
    Then, using ConfigEd, getting the config
    (using fallback config from defaults.py)
    and modifying it according to command-line parameters.
    Then it checks whether the provided sources exist,
    and runs a Wesen simulation with the given config.

    If you want to manipulate the Wesen simulation
    before the start, pass run_immediately=False,
    then Loader returns a Wesend instance,
    which you can start by start()"""
    _enableCustomSourcesFolder()
    parsedArgs, extraArgs = _parseArgs()
    configEd = ConfigEd(parsedArgs.configfile)
    if parsedArgs.invoke_defaultconfig:
        configEd.writeDefaults()
    if parsedArgs.invoke_editconfig:
        configEd.edit()
    if parsedArgs.invoke_printconfig:
        configEd.printConfig()
    config: dict[str, Any] = configEd.getConfig()
    if "_config" in parsedArgs:
        for section, sectionDict in parsedArgs._config.items():
            config[section].update(sectionDict)
    config["resume"] = parsedArgs.resume
    config["record_replay"] = parsedArgs.record_replay
    config["replay"] = parsedArgs.replay
    config["verify_replay"] = parsedArgs.verify_replay
    if len(extraArgs) > 0:
        print(
            "handing over the following command-line arguments to OpenGL: ",
            " ".join(extraArgs),
        )
    if not (parsedArgs.replay or parsedArgs.verify_replay):
        _checkSourcesAvailability(config["wesen"]["sources"])
    try:
        wesend = Wesend(config)
    except ReplayError as error:
        if run_immediately:
            print(f"replay error: {error}")
            raise SystemExit(1) from None
        raise
    if run_immediately:
        success = wesend.start(" ".join(extraArgs))
        if parsedArgs.verify_replay and not success:
            raise SystemExit(1)
        return None
    return wesend


def _enableCustomSourcesFolder() -> None:
    """Appends to the path a folder where the user can store custom AI code."""
    configroot = join(expanduser("~"), ".wesen")
    sourcefolder = join(configroot, "sources")
    if not exists(configroot):
        mkdir(configroot)
    if not exists(sourcefolder):
        mkdir(sourcefolder)
    sys.path.append(sourcefolder)


def _parseArgs() -> tuple[Namespace, list[Any]]:
    """returns the result of an ArgumentParser.parse_known_args call"""
    # HINT: If you consider adding an option,
    #      please consider adding a config file option first.
    parser = ArgumentParser(
        description=STRING_USAGE_DESCRIPTION, epilog=STRING_USAGE_EPILOG
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s (" + VERSIONSTRING + ")",
    )
    parser.add_argument(
        "-c",
        "--configfile",
        action="store",
        dest="configfile",
        default=DEFAULT_CONFIGFILE,
        help=STRING_USAGE_CONFIGFILE,
    )
    parser.add_argument(
        "-e",
        "--editconfig",
        action="store_true",
        dest="invoke_editconfig",
        default=False,
        help=STRING_USAGE_EDITCONFIG,
    )
    parser.add_argument(
        "--defaultconfig",
        action="store_true",
        dest="invoke_defaultconfig",
        default=False,
        help=STRING_USAGE_DEFAULTCONFIG,
    )
    parser.add_argument(
        "--printconfig",
        action="store_true",
        dest="invoke_printconfig",
        default=False,
        help=STRING_USAGE_PRINTCONFIG,
    )
    _addOverwriteBool(parser, "gui", "gui", "enable")
    parser.add_argument(
        "-s",
        "--sources",
        section="wesen",
        dest="sources",
        action=_OverwriteConfigAction,
    )
    parser.add_argument(
        "-r",
        "--resume",
        dest="resume",
        action="store_true",
        default=False,
        help=STRING_USAGE_RESUME,
    )
    replay_group = parser.add_mutually_exclusive_group()
    replay_group.add_argument(
        "--record-replay",
        metavar="PATH",
        help="record this simulation as a JSON Lines replay",
    )
    replay_group.add_argument(
        "--replay",
        metavar="PATH",
        help="apply checkpoints and deltas from a JSON Lines replay",
    )
    replay_group.add_argument(
        "--verify-replay",
        metavar="PATH",
        help="verify replay integrity and checkpoints without a GUI",
    )
    return parser.parse_known_args()


def _addOverwriteBool(
    parser: ArgumentParser, argName: str, section: str, key: str
) -> None:
    """for convenience, adds a mutually exclusive group
    with --enable and --disable argName, to modify [section] key"""
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--enable" + argName,
        section=section,
        dest=key,
        storeValue=True,
        action=_OverwriteConfigActionBool,
    )
    group.add_argument(
        "--disable" + argName,
        section=section,
        dest=key,
        storeValue=False,
        action=_OverwriteConfigActionBool,
    )


def _checkSourcesAvailability(sourcesList: str) -> None:
    """imports all sources listed in sourcesList.
    Upon ImportError, prints a polite message and kills the process."""
    sources = sourcesList.split(",")
    for source in sources:
        try:
            module = importlib.import_module(
                ".sources." + source + ".main", __package__
            )
            _ = module.WesenSource
        except ImportError as e:
            print(e)
            print(
                "The source code for one of your AIs could not be loaded: ",
                source,
            )
            sys.exit()


class _OverwriteConfigAction(Action):
    """An ArgumentParser Action that stores in a dict
    called _config in the namespace
    which config option should be overwritten by command-line."""

    # TODO change name _config to sth else, as its not a protected member

    def __init__(
        self, option_strings: list[str], dest: str, section: str, nargs: int = 1
    ) -> None:
        """Configure an argparse action for one configuration override."""
        helpMessage = STRING_USAGE_OVERWRITE % (section, dest)
        super().__init__(
            option_strings=option_strings,
            dest=dest,
            nargs=nargs,
            const=False,
            default=None,
            required=False,
            help=helpMessage,
        )
        self.section = section

    def __call__(
        self,
        parser: ArgumentParser,
        namespace: Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        """Store the parsed override under its configuration section."""
        if values is None:
            raise ValueError("missing value for config option to overwrite")
        normalized = values
        if len(normalized) != 1:
            raise ValueError(
                "wrong number of values for config option to overwrite: [",
                self.section,
                "]",
                self.dest,
                "=",
                ",".join(str(value) for value in normalized),
            )
        else:
            # print("Overwritten config option: [",
            #      self.section, "]",
            #      self.dest, "=",
            #      values[0]);
            if "_config" not in namespace:
                namespace._config = {}
            if self.section not in namespace._config.keys():
                namespace._config[self.section] = {}
            namespace._config[self.section][self.dest] = normalized[0]


class _OverwriteConfigActionBool(_OverwriteConfigAction):
    """For convenience, storing True/False as specified"""

    def __init__(
        self,
        option_strings: list[str],
        dest: str,
        section: str,
        storeValue: bool | None = None,
    ) -> None:
        """Configure a flag that stores a predetermined Boolean value."""
        super().__init__(
            option_strings=option_strings,
            dest=dest,
            section=section,
            nargs=0,
        )
        self.storeValue = storeValue

    def __call__(
        self,
        parser: ArgumentParser,
        namespace: Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        """Replace argparse's value with the configured Boolean override."""
        if self.storeValue is not None:
            values = [self.storeValue]
        super().__call__(parser, namespace, values, option_string)
