"""Otto's typed ``otto.plan`` task metadata namespace.

Herzchen's work domain refuses a write whose ``otto.plan`` values fail
``validate_plan``.  Routes are the worker routes Otto dispatches (``normal``,
``xhard``); a plan's ``branch`` names a branch in its ``repo``, so it needs one.
"""

from herzchen.domains.work.model import WorkValidationError
from herzchen.domains.work.module import register_metadata_namespace


PLAN_NAMESPACE = "otto.plan"
PLAN_KEYS = ("route", "size", "lines", "repo", "branch")
PLAN_ROUTES = ("normal", "xhard")
PLAN_SIZES = ("small", "medium", "large")


def _text(values, key):
    value = values[key]
    if not isinstance(value, str) or not value.strip() or any(char.isspace() for char in value):
        raise WorkValidationError(f"otto.plan {key} must be a non-blank name without spaces")


def validate_plan(values):
    unknown = sorted(str(key) for key in set(values) - set(PLAN_KEYS))
    if unknown:
        raise WorkValidationError("unknown otto.plan keys: " + ", ".join(unknown))
    if "route" in values and values["route"] not in PLAN_ROUTES:
        raise WorkValidationError("otto.plan route must be one of: " + ", ".join(PLAN_ROUTES))
    if "size" in values and values["size"] not in PLAN_SIZES:
        raise WorkValidationError("otto.plan size must be one of: " + ", ".join(PLAN_SIZES))
    if "lines" in values and (type(values["lines"]) is not int or values["lines"] < 1):
        raise WorkValidationError("otto.plan lines must be a positive integer")
    for key in ("repo", "branch"):
        if key in values:
            _text(values, key)
    if "branch" in values and "repo" not in values:
        raise WorkValidationError("otto.plan branch requires a repo")


def register_plan_metadata():
    """Register ``otto.plan`` on the work domain's hook; repeat calls are no-ops."""

    register_metadata_namespace(PLAN_NAMESPACE, validate_plan)
