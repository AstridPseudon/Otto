"""Finite host composition; settings select names, never executables or verifiers."""
from __future__ import annotations

from dataclasses import dataclass
import copy
from typing import Any, Callable, Mapping, Optional


@dataclass(frozen=True)
class TrustedAdapter:
    identity: str
    compose: Callable[..., Any]
    models: frozenset[str]
    profiles: frozenset[str]
    pins: Mapping[str, Any]
    # Efforts the CLI itself accepts. None keeps the generic vocabulary; a
    # CLI with a narrower set (Claude: low..max) must declare it so an
    # unsupported effort fails at resolve, not later at compose/launch.
    reasonings: Optional[frozenset[str]] = None


REASONINGS = frozenset({"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"})


def _reasoning_qualified(adapter: TrustedAdapter, reasoning: Any) -> bool:
    allowed = REASONINGS if adapter.reasonings is None else adapter.reasonings & REASONINGS
    return reasoning in allowed


class TrustedAdapterSelection:
    def __init__(self, choices: Mapping[str, TrustedAdapter]) -> None:
        if not choices or len(choices) > 8 or any(
                not isinstance(name, str) or not name or not isinstance(value, TrustedAdapter)
                or not callable(value.compose) or not value.identity or not value.pins
                for name, value in choices.items()):
            raise ValueError("finite host-owned adapter compositions and pins required")
        self._choices = {name: TrustedAdapter(value.identity, value.compose, value.models, value.profiles,
                                              copy.deepcopy(dict(value.pins)), value.reasonings)
                         for name, value in choices.items()}

    def resolve(self, *, override: Mapping[str, Any] | None = None,
                role: Mapping[str, Any], defaults: Mapping[str, Any] | None = None,
                profile: str = "workspace-write") -> dict[str, Any]:
        values, provenance = {}, {}
        for field in ("adapter", "model", "reasoning"):
            for source, candidate in (("explicit_override", override), ("project_role", role),
                                      ("user_default", defaults)):
                if candidate and field in candidate:
                    values[field], provenance[field] = candidate[field], source
                    break
            if field not in values:
                raise ValueError("missing qualified " + field + " selection")
        selected = self._choices.get(values["adapter"])
        if (selected is None or values["model"] not in selected.models or profile not in selected.profiles
                or not _reasoning_qualified(selected, values["reasoning"])):
            raise ValueError("adapter/model/profile is not qualified by this host; no fallback")
        return {**values, "profile": profile, "provenance": provenance,
                "identity": selected.identity, "pins": copy.deepcopy(dict(selected.pins))}

    def compose(self, selection: Mapping[str, Any], **options: Any) -> Any:
        selected = self._choices[selection["adapter"]]
        if selection["identity"] != selected.identity or selection["pins"] != dict(selected.pins):
            raise PermissionError("adapter composition pins changed")
        if (selection["model"] not in selected.models or selection["profile"] not in selected.profiles
                or not _reasoning_qualified(selected, selection["reasoning"])):
            raise PermissionError("retained adapter/model/profile is no longer qualified; no fallback")
        app = selected.compose(model=selection["model"], reasoning=selection["reasoning"], **options)
        if app.native_adapter_identity() != selected.identity:
            raise PermissionError("composed adapter identity differs from trusted selection")
        return app
