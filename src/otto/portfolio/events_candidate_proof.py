"""Disposable candidate proof for the maintained Events public surface.

The proof deliberately stops at the injected CLI/facade boundary.  It does
not create an owner, install a pack, migrate a live Store, or publish an
artifact.  A host can use it with an admitted ``ObservabilityViews`` instance
to qualify one bounded JSON overview, one selected detail, and the equivalent
text rendering before owner adoption.
"""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from typing import Any, Mapping, Optional, Sequence

from .cli import main
from .observability_contract import CANDIDATE_COMMIT, CLIENT_PIN, CONTEXT_PINS, RUNTIME_PIN, RESOURCE_PINS, SOURCE_COMMIT
from .observability_views import ObservabilityViews


PROOF_SCHEMA = "otto.events.candidate-proof.v1"


class CandidateProofError(ValueError):
    """The injected candidate surface did not produce bounded proof."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _project_ref(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CandidateProofError("project_ref must be a canonical mapping")
    if value.get("kind") != "work.project" or not all(isinstance(value.get(key), str) and value[key].strip()
                                                       for key in ("authority", "id")):
        raise CandidateProofError("project_ref must identify a work.project")
    return dict(value)


def _invoke(
    argv: Sequence[str],
    *,
    views: ObservabilityViews,
    grant: Any,
    actor: str,
    bound_actor: Optional[str],
) -> tuple[int, Any, str]:
    output = StringIO()
    with redirect_stdout(output):
        exit_code = main(
            list(argv), observability_views=views, observability_grant=grant,
            bound_actor=bound_actor,
        )
    rendered = output.getvalue().strip()
    if not rendered:
        raise CandidateProofError("the public Events CLI returned no output")
    try:
        value = json.loads(rendered) if "--format" in argv and argv[-1] == "json" else rendered
    except json.JSONDecodeError as exc:
        raise CandidateProofError("the JSON Events CLI response was malformed") from exc
    if exit_code != 0:
        raise CandidateProofError(f"the public Events CLI rejected the candidate request: {value!r}")
    return exit_code, value, rendered


def run_candidate_journey(
    *,
    views: ObservabilityViews,
    grant: Any,
    actor: str,
    project_ref: Mapping[str, Any],
    limit: int = 1,
    bound_actor: Optional[str] = None,
) -> dict[str, Any]:
    """Run one authenticated bounded JSON/text overview/detail journey.

    The returned object is evidence for owner adoption readiness, not an
    installed-proof or acceptance record.  ``views`` and ``grant`` must be
    supplied by the host or disposable fixture; this helper never constructs
    either authority.
    """
    if not isinstance(views, ObservabilityViews):
        raise CandidateProofError("an injected ObservabilityViews facade is required")
    if not isinstance(actor, str) or not actor.strip():
        raise CandidateProofError("actor is required")
    if type(limit) is not int or not 1 <= limit <= 200:
        raise CandidateProofError("limit must be between 1 and 200")
    project = _project_ref(project_ref)
    project_arg = _canonical_json(project)
    base = ["events", "overview", "--actor", actor, "--project-ref", project_arg, "--limit", str(limit)]
    _, overview, overview_raw = _invoke(
        [*base, "--format", "json"], views=views, grant=grant, actor=actor, bound_actor=bound_actor,
    )
    if not isinstance(overview, Mapping) or overview.get("outcome") != "read" or overview.get("view") != "overview":
        raise CandidateProofError("overview did not return a bounded read envelope")
    snapshot = overview.get("snapshot")
    rows = overview.get("rows")
    if not isinstance(snapshot, Mapping) or not isinstance(rows, list) or not rows:
        raise CandidateProofError("overview did not return a snapshot and selected row")
    facet_id = rows[0].get("facet_id") if isinstance(rows[0], Mapping) else None
    if not isinstance(facet_id, str) or not facet_id:
        raise CandidateProofError("overview row did not expose a selected facet")
    _, detail, detail_raw = _invoke(
        ["events", "detail", "--actor", actor, "--project-ref", project_arg,
         "--facet-id", facet_id, "--snapshot", _canonical_json(snapshot), "--format", "json"],
        views=views, grant=grant, actor=actor, bound_actor=bound_actor,
    )
    if not isinstance(detail, Mapping) or detail.get("outcome") != "read" or detail.get("facet_id") != facet_id:
        raise CandidateProofError("detail did not return the selected bounded facet")
    _, text_value, text_raw = _invoke(
        [*base, "--format", "text"], views=views, grant=grant, actor=actor, bound_actor=bound_actor,
    )
    if "Canonical response:" not in text_value:
        raise CandidateProofError("text output did not retain the canonical response")
    return {
        "schema": PROOF_SCHEMA,
        "outcome": "candidate_ready",
        "installed_claimed": False,
        "owner_adoption_required": True,
        "actor": actor,
        "project_ref": project,
        "limit": limit,
        "overview": overview,
        "detail": detail,
        "renderings": {
            "json_overview": overview_raw,
            "json_detail": detail_raw,
            "text_overview": text_raw,
        },
        "pins": {
            "installed_source_commit": SOURCE_COMMIT,
            "candidate_checkpoint": CANDIDATE_COMMIT,
            "runtime": dict(RUNTIME_PIN),
            "client": dict(CLIENT_PIN),
            "resources": json.loads(json.dumps(RESOURCE_PINS, sort_keys=True)),
            "context": json.loads(json.dumps(CONTEXT_PINS, sort_keys=True)),
        },
        "limits": {
            "returned_rows": len(rows),
            "detail_bounded": detail.get("coverage", {}).get("bounded") is True,
            "snapshot_digest": overview.get("snapshot_digest"),
        },
    }


__all__ = ["CandidateProofError", "PROOF_SCHEMA", "run_candidate_journey"]
