"""Reserved DAT membership for a lifetime primary direction identity.

This is a binding contract, not revision adoption or execution authority.
Ordinary DAT/WRK membership operations cannot author this namespace.
"""
from typing import Any, Mapping

PRIMARY_DIRECTION_NAMESPACE = "direction.primary.v1"
PRIMARY_DIRECTION_KEY = "primary"


def is_primary_direction(value: Any) -> bool:
    if isinstance(value, Mapping):
        value = value.get("association", value)
        return isinstance(value, Mapping) and value.get("namespace") == PRIMARY_DIRECTION_NAMESPACE
    return getattr(value, "namespace", None) == PRIMARY_DIRECTION_NAMESPACE
