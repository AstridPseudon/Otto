"""Thin Otto view over the existing Herzchen assessment owner.

This module owns no assessment state.  It delegates every command to the
supplied AssessmentModule and joins scoped, current owner records for the
manager's coverage view.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from herzchen.contracts import AuthenticatedActor, ResourceRef


class OttoAssessmentError(ValueError):
    """The owner port or requested assessment scope is not admissible."""


def _ref(value: Any, field: str) -> ResourceRef:
    if isinstance(value, ResourceRef):
        return value
    if hasattr(value, "ref") and isinstance(value.ref, ResourceRef):
        return value.ref
    if isinstance(value, Mapping):
        return ResourceRef.from_dict(value)
    raise OttoAssessmentError(f"{field} must be a typed ResourceRef")


def _same_identity(left: ResourceRef, right: ResourceRef) -> bool:
    return (left.authority, left.kind, left.id) == (right.authority, right.kind, right.id)


def _json(value: Any) -> Any:
    if isinstance(value, ResourceRef):
        return value.to_dict()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(item) for item in value]
    return value


class OttoAssessment:
    """Explicit assessment operations and a complete parent-scoped view."""

    def __init__(self, assessment: Any, actor: AuthenticatedActor) -> None:
        if not isinstance(actor, AuthenticatedActor):
            raise TypeError("actor must be an AuthenticatedActor")
        reader = getattr(assessment, "reader", None)
        if reader is None or not isinstance(getattr(reader, "authority", None), str):
            raise OttoAssessmentError("assessment owner must expose its finite public reader")
        # Trusted composition supplies the owner/actor pair. Principal and
        # record-store namespaces may differ; owner commands enforce admission.
        self._assessment = assessment
        self._reader = reader
        self._actor = actor

    def get_scope(self, scope: Any) -> Any:
        return self._assessment.get_scope(_ref(scope, "scope"))

    def get_input(self, input_packet: Any) -> Any:
        return self._assessment.get_input(_ref(input_packet, "input packet"))

    def get_selection(self, selection: Any) -> Any:
        return self._assessment.get_selection(_ref(selection, "candidate selection"))

    def get_result(self, result: Any) -> Any:
        return self._assessment.get_result(_ref(result, "assessment result"))

    def get_finding(self, finding: Any) -> Any:
        return self._assessment.get_finding(_ref(finding, "finding"))

    def get_correction(self, correction: Any) -> Any:
        return self._assessment.get_correction(_ref(correction, "correction"))

    def get_decision(self, decision: Any) -> Any:
        return self._assessment.get_decision(_ref(decision, "decision"))

    def declare_scope(self, scope: Any, **kwargs: Any) -> Any:
        kwargs["actor"] = self._actor
        return self._assessment.declare_scope(_ref(scope, "scope"), **kwargs)

    def freeze_input(self, scope: Any, **kwargs: Any) -> Any:
        kwargs["actor"] = self._actor
        return self._assessment.freeze_input(_ref(scope, "scope"), **kwargs)

    def select_candidate(self, scope: Any, **kwargs: Any) -> Any:
        kwargs["actor"] = self._actor
        return self._assessment.select_candidate(_ref(scope, "scope"), **kwargs)

    def assess(self, scope: Any, **kwargs: Any) -> Any:
        kwargs["actor"] = self._actor
        return self._assessment.assess(_ref(scope, "scope"), **kwargs)

    def create_correction(self, result: Any, **kwargs: Any) -> Any:
        kwargs["actor"] = self._actor
        return self._assessment.create_correction(_ref(result, "result"), **kwargs)

    def close_finding(self, finding: Any, **kwargs: Any) -> Any:
        kwargs["actor"] = self._actor
        return self._assessment.close_finding(_ref(finding, "finding"), **kwargs)

    def accept(self, result: Any, **kwargs: Any) -> Any:
        kwargs["actor"] = self._actor
        return self._assessment.accept(_ref(result, "result"), **kwargs)

    def dispose_unknown(self, result: Any, **kwargs: Any) -> Any:
        kwargs["actor"] = self._actor
        return self._assessment.dispose_unknown(_ref(result, "result"), **kwargs)

    def resolve_correction(self, correction: Any, *, retest_result: Any, decision: Any, **kwargs: Any) -> Any:
        kwargs["actor"] = self._actor
        return self._assessment.resolve_correction(
            _ref(correction, "correction"), retest_result=_ref(retest_result, "retest result"),
            decision=_ref(decision, "decision"), **kwargs,
        )

    def coverage(self, parent_obligation: Any) -> dict[str, Any]:
        """Return all current assessment records and uncovered criteria for one parent.

        This uses only the owner's public event and identity reader.  It has no
        pagination: exceeding the defensive scan bound fails explicitly so a
        response cannot silently hide later criteria or results.
        """
        parent = _ref(parent_obligation, "parent obligation")
        if parent.authority != self._reader.authority:
            raise OttoAssessmentError("parent obligation belongs to another owner authority")
        current_parent = self._reader.get_identity(ResourceRef(parent.authority, parent.kind, parent.id))
        if current_parent is None or (parent.revision is not None and parent.revision != current_parent.ref.revision):
            raise OttoAssessmentError("parent obligation is missing or stale")
        events = tuple(self._reader.list_events(
            stream="assessment", assessment_parent=current_parent.ref
        ))
        if len(events) > 10000:
            raise OttoAssessmentError("assessment history exceeds the complete-view bound")

        scopes: dict[tuple[str, str], Any] = {}
        results: dict[tuple[str, str], Any] = {}
        corrections: dict[tuple[str, str], Any] = {}
        decisions: dict[tuple[str, str], Any] = {}

        def current_record(event: Any, expected_kind: str) -> Optional[ResourceRef]:
            subject = event.subject
            if event.store_authority != self._reader.authority or subject.authority != self._reader.authority or subject.kind != expected_kind:
                return None
            identity = self._reader.get_identity(ResourceRef(subject.authority, subject.kind, subject.id))
            if identity is None or identity.ref.authority != subject.authority or identity.ref.kind != subject.kind or identity.ref.id != subject.id:
                return None
            return identity.ref

        for event in events:
            if event.event_type == "assessment.scope.declared":
                ref = current_record(event, "assessment.scope")
                if ref is None:
                    continue
                scope = self._assessment.get_scope(ref)
                if _same_identity(scope.parent_obligation_ref, current_parent.ref):
                    scopes[(ref.authority, ref.id)] = scope
            elif event.event_type == "assessment.completed":
                ref = current_record(event, "assessment.result")
                if ref is None:
                    continue
                result = self._assessment.get_result(ref)
                if _same_identity(result.parent_obligation_ref, current_parent.ref):
                    results[(ref.authority, ref.id)] = result
            elif event.event_type in {"assessment.correction.created", "assessment.correction.resolved"}:
                ref = current_record(event, "assessment.correction")
                if ref is None:
                    continue
                correction = self._assessment.get_correction(ref)
                if _same_identity(correction.parent_obligation_ref, current_parent.ref):
                    corrections[(ref.authority, ref.id)] = correction
            elif event.event_type in {"assessment.accepted", "assessment.unknown.disposed"}:
                ref = current_record(event, "assessment.decision")
                if ref is None:
                    continue
                decision = self._assessment.get_decision(ref)
                if _same_identity(decision.parent_obligation_ref, current_parent.ref):
                    decisions[(ref.authority, ref.id)] = decision

        scope_rows = []
        coverage_rows = []
        for scope in sorted(scopes.values(), key=lambda row: (row.ref.authority, row.ref.id)):
            scope_criteria = tuple(scope.criterion_refs)
            scope_rows.append({
                "ref": _json(scope.ref), "parent_obligation_ref": _json(scope.parent_obligation_ref),
                "criteria": [_json(value) for value in scope_criteria], "protocol": scope.protocol,
                "designated_approver": scope.designated_approver, "authority": scope.authority,
            })
            for criterion in scope_criteria:
                matching = [
                    result for result in results.values()
                    if _same_identity(result.scope_ref, scope.ref) and _same_identity(result.criterion_ref, criterion)
                ]
                matching.sort(key=lambda row: (row.ref.authority, row.ref.id))
                coverage_rows.append({
                    "scope_ref": _json(scope.ref), "criterion_ref": _json(criterion),
                    "state": "uncovered" if not matching else "assessed",
                    "result_refs": [_json(result.ref) for result in matching],
                    "verdicts": [result.verdict.value for result in matching],
                })

        result_rows = []
        for result in sorted(results.values(), key=lambda row: (row.ref.authority, row.ref.id)):
            matching_decisions = [decision for decision in decisions.values() if decision.result_ref is not None and _same_identity(decision.result_ref, result.ref)]
            result_rows.append({
                "ref": _json(result.ref), "scope_ref": _json(result.scope_ref),
                "parent_obligation_ref": _json(result.parent_obligation_ref),
                "criterion_ref": _json(result.criterion_ref), "candidate_ref": _json(result.candidate_ref),
                "input_packet_ref": _json(result.input_packet_ref), "verdict": result.verdict.value,
                "finding_refs": [_json(item.ref) for item in result.findings],
                "correction_refs": [_json(value) for value in result.correction_refs],
                "decision_refs": [_json(item.ref) for item in matching_decisions],
            })

        correction_rows = []
        for correction in sorted(corrections.values(), key=lambda row: (row.ref.authority, row.ref.id)):
            correction_rows.append({
                "ref": _json(correction.ref), "result_ref": _json(correction.result_ref),
                "finding_refs": [_json(value) for value in correction.finding_refs],
                "owner": correction.owner, "status": correction.status,
                "next_step": correction.payload.get("instruction"),
                "fix_candidate_ref": _json(correction.fix_candidate_ref),
                "evidence_refs": [_json(value) for value in correction.evidence_refs],
                "retest_result_ref": _json(correction.retest_result_ref),
                "decision_ref": _json(correction.decision_ref),
            })

        decision_rows = []
        for decision in sorted(decisions.values(), key=lambda row: (row.ref.authority, row.ref.id)):
            decision_rows.append({
                "ref": _json(decision.ref), "result_ref": _json(decision.result_ref),
                "parent_obligation_ref": _json(decision.parent_obligation_ref),
                "candidate_ref": _json(decision.candidate_ref), "criterion_ref": _json(decision.criterion_ref),
                "author": decision.author, "authority": decision.authority,
                "disposition": decision.disposition, "evidence_refs": [_json(value) for value in decision.evidence_refs],
            })

        return {
            "parent_obligation_ref": _json(current_parent.ref), "scope_count": len(scope_rows),
            "scopes": scope_rows, "coverage": coverage_rows, "results": result_rows,
            "corrections": correction_rows, "decisions": decision_rows,
            "complete_scan": True, "pagination": None,
        }


__all__ = ["OttoAssessment", "OttoAssessmentError"]
