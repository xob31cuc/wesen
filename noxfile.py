import nox

nox.options.default_venv_backend = "uv"

SOURCE = "src"
TESTS = "tests"

SUPPORTED_PYTHONS = ["3.12", "3.13", "3.14"]
DEFAULT_PYTHON = "3.14"


@nox.session(
    python=SUPPORTED_PYTHONS,
    reuse_venv=True,
)
def tests(session: nox.Session) -> None:
    """Run unit, property-based, Faker, and doctests."""

    # Install the project itself.
    session.install("-e", ".")

    # Test-only dependencies.
    session.install(
        "pytest",
        "faker",
        "hypothesis",
    )

    session.run(
        "pytest",
        "--doctest-modules",
        SOURCE,
        TESTS,
        *session.posargs,
    )


@nox.session(
    python=DEFAULT_PYTHON,
    reuse_venv=True,
)
def crosshair(session: nox.Session) -> None:
    """Check Deal contracts and assertions symbolically with CrossHair."""

    session.install("-e", ".")
    session.install(
        "crosshair-tool",
        "deal",
    )

    session.run(
        "crosshair",
        "check",
        "--analysis_kind=deal,asserts",
        SOURCE,
    )


@nox.session(
    python=DEFAULT_PYTHON,
    reuse_venv=True,
    default=False,
)
def mutation(session: nox.Session) -> None:
    """Run mutation tests with pytest-gremlins."""

    session.install("-e", ".")
    session.install(
        "pytest",
        "pytest-gremlins",
        "pytest-xdist",
        "faker",
        "hypothesis",
    )

    session.run(
        "pytest",
        "--gremlins",
        TESTS,
    )
