from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

Getter = Callable[[Any], Any]
Setter = Callable[[Any, Any], None]
StaticFields = dict[str, Any]
DynamicFields = dict[str, Any]


def persistence(
    func: Callable[..., Any], static: StaticFields, dynamic: DynamicFields
) -> Callable[..., Any]:
    """decorator for handling persistence.
    static fields are fields that are set only once in the constructor and
    thus only need to be stored. Dynamic fields are part of the dynamic state
    of the object and are set during restoring in addition to being stored."""
    for entry in static.keys():
        if static[entry] is None:
            static[entry] = lambda that, entry=entry: getattr(that, entry)
    for entry in dynamic.keys():
        if dynamic[entry] is None:
            dynamic[entry] = (
                lambda that, entry=entry: getattr(that, entry),
                lambda that, v, entry=entry: setattr(that, entry, v),
            )
        else:
            __getter, __setter = dynamic[entry]
            getter = __getter or (lambda that, entry=entry: getattr(that, entry))
            setter = __setter or (
                lambda that, v, entry=entry: setattr(that, entry, v)
            )
            dynamic[entry] = (getter, setter)

    @wraps(func)
    def wrapper(
        this: Any, obj: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        if obj is None:  # setter case
            d: dict[str, Any] = {}
            for entry, getter_func in static.items():
                d[entry] = getter_func(this)
            for entry, (getter_func, _) in dynamic.items():
                d[entry] = getter_func(this)
            return d
        else:  # getter case
            for entry, (_, setter_func) in dynamic.items():
                setter_func(this, obj[entry])
            return None

    return wrapper
