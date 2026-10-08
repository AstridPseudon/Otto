"""Bounded, restartable Worker-project staging through the existing owners.

This is deliberately a fixture/source import.  It does not admit a project,
assign a worker, dispatch a task, publish a resource, or transfer authority.
The work project holds source provenance; owner receipts and ResourceRefs hold
the progress of each write.  There is no separate import-status store.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Mapping

from herzchen.contracts import ResourceRef, canonical_json

from .worker_import_map import build_worker_import_map


class WorkerOwnerImportError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


def _digest(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _ref(value: Any) -> ResourceRef:
    return value if isinstance(value, ResourceRef) else ResourceRef.from_dict(value)


def _identity(value: Any) -> tuple[str, str, str]:
    ref = _ref(value)
    return ref.authority, ref.kind, ref.id


class WorkerProjectImporter:
    """Compose public work, content, and assessment operations for one freeze.

    The caller supplies already selected disposable owner facades.  Each
    operation has a stable key derived from the caller's logical request and
    source alias; replay is decided by the owner, including changed payloads.
    """

    def __init__(self, *, portfolio: Any, sheet: Any, documents: Any, content: Any,
                 assessment: Any, actor: Any) -> None:
        self.portfolio = portfolio
        self.sheet = sheet
        self.documents = documents
        self.content = content
        self.assessment = assessment
        self.actor = actor
        self.reader = portfolio.operations.reader
        authority = portfolio.operations.binding.authority
        if actor.authority != authority:
            raise WorkerOwnerImportError("foreign_mapping", "owner authorities differ")
        self.authority = authority

    @staticmethod
    def _task_rows(mapping: Mapping[str, Any]) -> list[dict[str, Any]]:
        portions = {row["alias"]: "portion-" + row["alias"].replace(":", "-")
                    for row in mapping["derived_aliases"]}
        rows = []
        for row in mapping["tasks"]:
            rows.append({
                "id": row["source_alias"], "title": row["source_alias"] + " — " + row["outcome_scope"][:100],
                "outcome": row["outcome_scope"], "acceptance": row["source_acceptance"],
                "dependencies": [portions.get(alias, alias) for alias in row["requires_aliases"]],
                "metadata": {"source_alias": row["source_alias"], "source_status": row["source_status"],
                             "applicability_guard": row["applicability_guard"],
                             "source_dependency_gate": row["source_dependency_gate"],
                             "route_class": row["route_class"], "worker_binding": row["worker_binding"],
                             "criterion_aliases": row["criterion_aliases"], "canonical_source_task": True},
            })
        for row in mapping["derived_aliases"]:
            rows.append({
                "id": portions[row["alias"]], "title": row["alias"],
                "outcome": "Derived T14 portion; source task T14 remains the canonical task",
                "acceptance": "No imported completion or PASS",
                "metadata": {"source_alias": row["alias"], "parent_source_alias": "T14",
                             "canonical_source_task": False, "source_status": "not_started"},
            })
        return rows

    def _project(self, mapping: Mapping[str, Any], *, request_id: str, title: str) -> ResourceRef:
        # Source policy is provenance on the canonical work project.  It is
        # deliberately not an independent mutable import ledger.
        created = self.portfolio.create_pending(
            actor=self.actor.actor, request_id=request_id + ":project",
            edit={"title": title, "outcome": "Frozen Worker project staging; no imported execution",
                  "metadata": {"worker_source_projection": dict(mapping),
                               "worker_source_mapping_sha256": mapping["mapping_sha256"]}},
        )
        if created.get("outcome") not in {"created", "replayed"}:
            raise WorkerOwnerImportError("project_write_failed", repr(created.get("error", created)))
        ref = _ref(created["project_ref"])
        if ref.authority != self.authority or ref.kind != "work.project":
            raise WorkerOwnerImportError("foreign_mapping", "project identity belongs to another owner")
        record = self.reader.get_record(ResourceRef(ref.authority, ref.kind, ref.id))
        metadata = record.payload.get("metadata", {}) if record is not None else {}
        if metadata.get("worker_source_mapping_sha256") != mapping["mapping_sha256"]:
            raise WorkerOwnerImportError("changed_request_conflict", "project source projection differs")
        return ResourceRef(ref.authority, ref.kind, ref.id)

    def _work(self, mapping: Mapping[str, Any], project: ResourceRef, request_id: str) -> dict[str, Any]:
        rows = self._task_rows(mapping)
        try:
            batch = self.sheet.adopt_existing_effort(
                {"id": mapping["source_run"], "tasks": rows,
                 "criteria": mapping["criteria"], "external_budget_refs": []},
                project=project, logical_request_key=request_id + ":work", actor=self.actor,
            )
        except Exception as exc:
            code = "changed_request_conflict" if type(exc).__name__ == "ReplayConflictError" else "work_write_failed"
            raise WorkerOwnerImportError(code, str(exc)) from exc
        refs = {alias: ref.to_dict() for alias, ref in batch.mappings.items()}
        expected = {row["id"] for row in rows}
        if set(refs) != expected or len({_identity(ref) for ref in refs.values()}) != len(expected):
            raise WorkerOwnerImportError("work_mapping_incomplete", "task aliases did not map one-to-one")
        return refs

    def _assessment(self, mapping: Mapping[str, Any], project: ResourceRef, request_id: str) -> dict[str, Any]:
        scope_ref = ResourceRef(self.authority, "assessment.scope",
                                "worker-" + sha256(request_id.encode()).hexdigest()[:28])
        definitions = [{"id": "worker-" + sha256((request_id + ":" + row["source_alias"]).encode()).hexdigest()[:28],
                        "source_alias": row["source_alias"], "expected_behavior": row["expected_behavior"],
                        "proof": row["proof"], "applicability": row["applicability"]}
                       for row in mapping["criteria"]]
        try:
            scope = self.assessment.declare_scope(
                scope_ref, parent_obligation=project, protocol="worker-source-freeze",
                criteria=definitions, review_required=True,
                policy={"source_mapping_sha256": mapping["mapping_sha256"], "imported_verdicts": False},
                logical_request_key=request_id + ":assessment",
            )
        except Exception as exc:
            code = "changed_request_conflict" if type(exc).__name__ == "ReplayConflictError" else "assessment_write_failed"
            raise WorkerOwnerImportError(code, str(exc)) from exc
        refs = {row["source_alias"]: ref.to_dict()
                for row, ref in zip(mapping["criteria"], scope.criterion_refs)}
        if len(refs) != 24 or len({_identity(ref) for ref in refs.values()}) != 24:
            raise WorkerOwnerImportError("assessment_mapping_incomplete", "criterion aliases did not map one-to-one")
        return {"scope_ref": scope.ref.to_dict(), "criterion_refs": refs}

    def _documents(self, mapping: Mapping[str, Any], document_bytes: Mapping[str, bytes],
                   project: ResourceRef, request_id: str, interrupt_after: int | None) -> dict[str, Any]:
        refs: dict[str, dict[str, Any]] = {}
        for index, row in enumerate(mapping["documents"]):
            alias = row["source_alias"]
            alias_key = sha256(alias.encode()).hexdigest()[:28]
            document_id = "worker-" + sha256((request_id + ":" + alias).encode()).hexdigest()[:28]
            created = self.portfolio.create_document(
                project.to_dict(), actor=self.actor.actor, request_id=request_id + ":doc:" + alias_key,
                document_id=document_id, role="supporting", visibility="shared", access_mode="read",
                content=document_bytes[alias].decode("utf-8"),
            )
            if created.get("outcome") not in {"created", "replayed"}:
                raise WorkerOwnerImportError("document_write_failed", alias + ": " + repr(created.get("error")))
            linked = self.portfolio.link_document(
                project.to_dict(), created["document_ref"], actor=self.actor.actor,
                request_id=request_id + ":link:" + alias_key,
                namespace="worker.source", key="alias-" + alias_key, access_mode="read",
            )
            if linked.get("outcome") not in {"linked", "replayed"}:
                raise WorkerOwnerImportError("document_link_failed", alias + ": " + repr(linked.get("error")))
            refs[alias] = {"document_ref": created["document_ref"], "association_ref": linked["association_ref"]}
            if interrupt_after is not None and index + 1 == interrupt_after:
                raise WorkerOwnerImportError("injected_interruption", f"after {interrupt_after} linked documents")
        return refs

    def reconcile(self, mapping: Mapping[str, Any], project: Any, *, task_refs: Mapping[str, Any],
                  criterion_refs: Mapping[str, Any], scope_ref: Any,
                  document_refs: Mapping[str, Any], request_id: str) -> dict[str, Any]:
        """Read every staged owner and compare with the pinned source map."""
        project_ref = _ref(project)
        if project_ref.authority != self.authority:
            raise WorkerOwnerImportError("foreign_mapping", "project authority differs")
        record = self.reader.get_record(ResourceRef(project_ref.authority, project_ref.kind, project_ref.id))
        if record is None:
            raise WorkerOwnerImportError("missing_mapping", "project record missing")
        metadata = record.payload.get("metadata", {})
        if metadata.get("worker_source_mapping_sha256") != mapping["mapping_sha256"]:
            raise WorkerOwnerImportError("stale_mapping", "source digest mismatch")
        if metadata.get("worker_source_projection") != mapping:
            raise WorkerOwnerImportError("stale_mapping", "full source projection differs")
        view = self.sheet.export(project_ref)
        observed_tasks = {row["authored"].get("metadata", {}).get("source_alias"): row for row in view.tasks}
        expected_aliases = {row["source_alias"] for row in mapping["tasks"]} | {row["alias"] for row in mapping["derived_aliases"]}
        if set(observed_tasks) != expected_aliases or len(task_refs) != 28:
            raise WorkerOwnerImportError("work_readback_failed", "task alias census differs")
        for alias, row in observed_tasks.items():
            if _identity(row["ref"]) != _identity(task_refs["portion-" + alias.replace(":", "-") if alias.startswith("T14:") else alias]):
                raise WorkerOwnerImportError("stale_mapping", alias + " native task reference differs")
            observed = row.get("observed", {})
            if observed.get("results") or observed.get("decisions") or observed.get("dispatches"):
                raise WorkerOwnerImportError("fabricated_progress", alias)
        portions = {row["alias"]: "portion-" + row["alias"].replace(":", "-")
                    for row in mapping["derived_aliases"]}
        for source in mapping["tasks"]:
            authored = observed_tasks[source["source_alias"]]["authored"]
            source_metadata = authored.get("metadata", {})
            expected_metadata = {
                "source_alias": source["source_alias"], "source_status": source["source_status"],
                "applicability_guard": source["applicability_guard"],
                "source_dependency_gate": source["source_dependency_gate"],
                "route_class": source["route_class"], "worker_binding": source["worker_binding"],
                "criterion_aliases": source["criterion_aliases"], "canonical_source_task": True,
            }
            if any(source_metadata.get(key) != value for key, value in expected_metadata.items()):
                raise WorkerOwnerImportError("work_readback_failed", source["source_alias"] + " source policy differs")
            if authored.get("outcome") != source["outcome_scope"] or authored.get("acceptance") != source["source_acceptance"]:
                raise WorkerOwnerImportError("work_readback_failed", source["source_alias"] + " scope differs")
            expected_dependencies = {_identity(task_refs[portions.get(alias, alias)])
                                     for alias in source["requires_aliases"]}
            if {_identity(ref) for ref in authored.get("dependencies", ())} != expected_dependencies:
                raise WorkerOwnerImportError("work_readback_failed", source["source_alias"] + " dependency refs differ")
        scope = self.assessment.get_scope(scope_ref)
        if len(scope.criterion_refs) != 24 or set(criterion_refs) != {row["source_alias"] for row in mapping["criteria"]}:
            raise WorkerOwnerImportError("assessment_readback_failed", "criterion alias census differs")
        for row, ref in zip(mapping["criteria"], scope.criterion_refs):
            if _identity(ref) != _identity(criterion_refs[row["source_alias"]]):
                raise WorkerOwnerImportError("stale_mapping", row["source_alias"] + " native criterion differs")
        coverage = self.assessment.coverage(project_ref)
        if len(coverage["coverage"]) != 24 or any(row["state"] != "uncovered" for row in coverage["coverage"]):
            raise WorkerOwnerImportError("assessment_readback_failed", "imported criteria were assessed")
        listed = self.documents.list_documents(project_ref, actor=self.actor)
        memberships = {membership["key"]: item["document_ref"]
                       for item in listed.get("documents", ())
                       for membership in item.get("memberships", ())
                       if membership.get("namespace") == "worker.source"}
        expected_membership_keys = {"alias-" + sha256(row["source_alias"].encode()).hexdigest()[:28]
                                    for row in mapping["documents"]}
        document_count = len(mapping["documents"])
        expected_document_aliases = {row["source_alias"] for row in mapping["documents"]}
        if (len(expected_document_aliases) != document_count
                or set(document_refs) != expected_document_aliases
                or len(document_refs) != document_count
                or set(memberships) != expected_membership_keys):
            raise WorkerOwnerImportError("document_readback_failed", "document alias census differs")
        for row in mapping["documents"]:
            alias = row["source_alias"]
            ref = document_refs[alias]["document_ref"]
            key = "alias-" + sha256(alias.encode()).hexdigest()[:28]
            if _identity(ref) != _identity(memberships[key]):
                raise WorkerOwnerImportError("stale_mapping", alias + " native document differs")
            body = self.content.read(_ref(ref))
            revision = body.get("revision", {}) if isinstance(body, Mapping) else {}
            content = revision.get("content") if isinstance(revision, Mapping) else None
            if not isinstance(content, str) or sha256(content.encode()).hexdigest() != row["raw_sha256"] or _digest(content) != row["canonical_content_sha256"]:
                raise WorkerOwnerImportError("failed_readback", alias + " content digest differs")
        readback = self.portfolio.operations.read("work.import.readback", {
            "project_ref": project_ref.to_dict(), "scope_ref": _ref(scope_ref).to_dict(),
            "criterion_refs": dict(criterion_refs), "document_refs": dict(document_refs),
            "request_id": request_id,
        }, actor=self.actor.actor)
        if readback.get("outcome") != "read":
            raise WorkerOwnerImportError("import_readback_unavailable", "scoped owner proof is unavailable")
        definitions = readback.get("criterion_definitions", {})
        for row in mapping["criteria"]:
            definition = definitions.get(row["source_alias"], {})
            if any(definition.get(field) != row[field] for field in (
                    "source_alias", "expected_behavior", "proof", "applicability")):
                raise WorkerOwnerImportError("assessment_readback_failed", "criterion definition differs")
        if readback.get("verified_receipt_count") != 3 + 2 * len(mapping["documents"]):
            raise WorkerOwnerImportError("missing_mapping", "owner receipt proof is incomplete")
        return {"reconciled": True, "project_ref": project_ref.to_dict(), "canonical_tasks": 24,
                "derived_portions": 4, "criteria": 24, "document_aliases": document_count,
                "raw_content_hashes": len({row["raw_sha256"] for row in mapping["documents"]}),
                "hard_edges": len(mapping["dependency_edges"]), "alternatives": len(mapping["dependency_options"]),
                "owner_receipts": {"project": 1, "work_batch": 1, "assessment_scope": 1,
                                   "content_documents": document_count, "content_links": document_count},
                "authority_handover_performed": False, "dispatch": False, "execution": False}

    def stage(self, truth_bytes: bytes, document_bytes: Mapping[str, bytes], *, request_id: str,
              title: str = "Worker project source freeze", interrupt_after: int | None = None,
              continuation: Any = None) -> dict[str, Any]:
        mapping = build_worker_import_map(truth_bytes, document_bytes)
        if not request_id or not isinstance(request_id, str):
            raise WorkerOwnerImportError("invalid_request", "logical request ID required")
        if continuation is None:
            project = self._project(mapping, request_id=request_id, title=title)
            task_refs = self._work(mapping, project, request_id)
            assessment = self._assessment(mapping, project, request_id)
        else:
            if self.portfolio.operations.content_command_guard is not continuation:
                raise WorkerOwnerImportError("continuation_guard_missing", "same guard required at content boundary")
            prefix = continuation.hydrate(mapping, request_id)
            project = _ref(prefix["project_ref"])
            task_refs = prefix["task_refs"]
            assessment = {"scope_ref": prefix["scope_ref"], "criterion_refs": prefix["criterion_refs"]}
        document_refs = self._documents(mapping, document_bytes, project, request_id, interrupt_after)
        result = self.reconcile(mapping, project, task_refs=task_refs,
                                criterion_refs=assessment["criterion_refs"], scope_ref=assessment["scope_ref"],
                                document_refs=document_refs, request_id=request_id)
        return {**result, "mapping_sha256": mapping["mapping_sha256"], "task_refs": task_refs,
                "criterion_refs": assessment["criterion_refs"], "assessment_scope_ref": assessment["scope_ref"],
                "document_refs": document_refs}

    @staticmethod
    def handover_preflight(result: Mapping[str, Any] | None) -> bool:
        if not result or result.get("reconciled") is not True:
            raise WorkerOwnerImportError("incomplete_import", "authority handover requires complete owner readback")
        raise WorkerOwnerImportError("authority_handover_unavailable", "disposable source staging cannot transfer authority")


__all__ = ["WorkerOwnerImportError", "WorkerProjectImporter"]
