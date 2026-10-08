"""Optional high-level work identities and structural commands."""

from .model import (
    GraphCycleError,
    InvalidDependencyError,
    InvalidParentError,
    Lifecycle,
    WorkError,
    WorkKind,
    WorkNotFoundError,
    WorkRecord,
    WorkStateView,
    WorkValidationError,
)
from .module import (
    DEFAULT_TITLE,
    DOMAIN_ID,
    DOMAIN_OWNER,
    DOMAIN_VERSION,
    SCHEMA_REVISION,
    WorkGraph,
    WorkModule,
    WorkStore,
    contribution,
    contributions,
    register_assignment_resources,
    register_orchestration,
    register_work,
    work_handler,
)
from .lifecycle import (
    LIFECYCLE_DOMAIN_ID,
    LIFECYCLE_EVENT,
    LIFECYCLE_OPERATION,
    LIFECYCLE_SCHEMA_REVISION,
    ProjectLifecycle,
    ProjectLifecycleError,
)
# Orchestration loads batch persistence. Keep resource-only imports inert;
# explicitly requesting an orchestration export still resolves the same object.
_ORCHESTRATION_EXPORTS = frozenset({
    "DEFAULT_KIND", "ORCHESTRATION_DOMAIN_ID", "ORCHESTRATION_SCHEMA_REVISION", "Orchestration",
})


def __getattr__(name):
    if name in _ORCHESTRATION_EXPORTS:
        from importlib import import_module
        value = getattr(import_module(".orchestration", __name__), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | _ORCHESTRATION_EXPORTS)


__all__ = [
    "DEFAULT_TITLE",
    "DOMAIN_ID",
    "DOMAIN_OWNER",
    "DOMAIN_VERSION",
    "GraphCycleError",
    "InvalidDependencyError",
    "InvalidParentError",
    "LIFECYCLE_DOMAIN_ID",
    "LIFECYCLE_EVENT",
    "LIFECYCLE_OPERATION",
    "LIFECYCLE_SCHEMA_REVISION",
    "Lifecycle",
    "SCHEMA_REVISION",
    "WorkError",
    "WorkGraph",
    "WorkKind",
    "WorkModule",
    "WorkNotFoundError",
    "WorkRecord",
    "WorkStateView",
    "WorkStore",
    "WorkValidationError",
    "ProjectLifecycle",
    "ProjectLifecycleError",
    "contribution",
    "contributions",
    "register_assignment_resources",
    "register_orchestration",
    "register_work",
    "work_handler",
    "DEFAULT_KIND",
    "ORCHESTRATION_DOMAIN_ID",
    "ORCHESTRATION_SCHEMA_REVISION",
    "Orchestration",
]
