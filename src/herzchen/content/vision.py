"""Finite Vision inline validation over DAT/EDT, with no new persistence.

Managed resources are data. Only trusted owner composition selects definitions
and supplies an authorized target reader. No schema hooks or graph writes run.
"""
from __future__ import annotations

from datetime import date
import hashlib
import json
from typing import Any, Callable, Mapping, Sequence

from herzchen.contracts import ResourceRef, ReferenceBinding, canonical_json
from herzchen.packs.authoring import ExecutionPin, ManagedPack, PackAuthoringError

SCHEMA = "vision.node.v1"
HOST_CONTRACT = "vision-inline.v1"
RESOURCE_PATH = "schemas/vision-node.json"
MAX_BYTES = 32768
KINDS = ("product", "area", "repository", "subsystem", "concept", "design-decision")
RELATIONS = ("refines", "contributes_to", "depends_on", "in_tension_with", "supersedes")
MATURITIES = ("sketch", "proposed", "aligned", "superseded")
FIELDS = ("schema", "definition", "kind", "title", "summary", "maturity", "as_of",
          "horizon", "body_markdown", "navigation_parent", "applies_to",
          "relationships", "sources", "work_refs", "repository", "members")
REQUIRED = ("schema", "definition", "kind", "title", "summary", "as_of", "body_markdown")
# Declarative descriptor: the maintained host interprets exactly this contract.
# It never executes a schema-supplied evaluator or accepts different semantics.
DEFINITION_CONTRACT = {
    "schema": SCHEMA, "host_contract": HOST_CONTRACT, "document_role": "vision",
    "fields": list(FIELDS), "required": list(REQUIRED), "kinds": list(KINDS),
    "relations": list(RELATIONS), "maturities": list(MATURITIES),
    "max_content_bytes": MAX_BYTES, "max_members": 128,
    "max_relationships": 32, "max_applies_to": 16, "max_sources": 16,
    "max_work_refs": 8, "unknown_fields": "reject",
}


class VisionValidationError(ValueError):
    def __init__(self, *errors: str):
        self.errors = errors
        super().__init__("; ".join(errors))


def _fail(path: str, reason: str, code: str = "schema_invalid") -> None:
    raise VisionValidationError(f"{code}: {path}: {reason}")


def _object(value: Any, path: str, allowed: Sequence[str], required: Sequence[str] = ()) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(path, "must be an object")
    if set(value) - set(allowed) or set(required) - set(value):
        _fail(path, "unknown or missing fields")
    return value


def _text(value: Any, path: str, limit: int, nonempty: bool = True) -> None:
    if not isinstance(value, str) or len(value) > limit or (nonempty and not value.strip()):
        _fail(path, f"must be {'nonempty ' if nonempty else ''}text of at most {limit} characters")


def _array(value: Any, path: str, limit: int) -> Sequence[Any]:
    if not isinstance(value, list) or len(value) > limit:
        _fail(path, f"must be an array of at most {limit} items")
    return value


def _ref(value: Any, path: str, authority: str, *, kinds: Sequence[str] = ("dat.content.document",)) -> ResourceRef:
    try:
        ref = ResourceRef.from_dict(value)
    except (TypeError, ValueError, KeyError) as exc:
        _fail(path, str(exc))
    if ref.authority != authority:
        _fail(path, "foreign graph authority is unsupported", "unsupported_scope")
    if ref.kind not in kinds or len(canonical_json(value).encode("utf-8")) > 1024:
        _fail(path, "invalid kind or oversized ref")
    return ref


def _identity(ref: ResourceRef) -> tuple[str, str, str]:
    return ref.authority, ref.kind, ref.id


def _binding(value: Any, path: str, authority: str, *, current_only: bool = False) -> ReferenceBinding:
    _object(value, path, ("mode", "ref"), ("mode", "ref"))
    ref = _ref(value["ref"], path + ".ref", authority)
    try:
        binding = ReferenceBinding(ref, value["mode"])
    except (TypeError, ValueError) as exc:
        _fail(path, str(exc))
    if current_only and binding.mode != "current":
        _fail(path, "current binding required")
    return binding


class ManagedVisionDefinitions:
    """Owner-selected exact managed resource pins, including retained versions.

    ``selected_pins`` comes from actual adoption, not pack discovery or a draft.
    A caller's valid-looking descriptor alone never admits a definition. The
    existing ExecutionPin shape is reused without changing DEFAULT_CATALOG.
    """
    def __init__(self, packs: Sequence[ManagedPack], selected_pins: Sequence[ExecutionPin]):
        self._packs = tuple(packs)
        self._pins = tuple(selected_pins)

    def resolve(self, descriptor: Any) -> None:
        keys = ("pack_id", "source_revision", "resource_path", "resource_sha256", "host_contract")
        _object(descriptor, "definition", keys, keys)
        for key in keys:
            _text(descriptor[key], "definition." + key, 1024)
        for key, lengths in (("source_revision", (40, 64)), ("resource_sha256", (64,))):
            token = descriptor[key]
            if len(token) not in lengths or any(char not in "0123456789abcdef" for char in token):
                _fail("definition." + key, "full immutable hex identity required")
        if (descriptor["pack_id"] != "vision" or descriptor["resource_path"] != RESOURCE_PATH
                or descriptor["host_contract"] != HOST_CONTRACT):
            _fail("definition", "unsupported definition contract", "definition_mismatch")
        matches = [pack for pack in self._packs if isinstance(pack, ManagedPack)
                   and pack.pack_id == descriptor["pack_id"]
                   and pack.source.source_revision == descriptor["source_revision"]]
        if len(matches) != 1:
            _fail("definition", "exact managed source unavailable", "definition_unavailable")
        pack = matches[0]
        try:
            resource = pack.resource(RESOURCE_PATH)
        except PackAuthoringError:
            _fail("definition", "declared resource unavailable", "definition_unavailable")
        expected = ExecutionPin("vision/" + RESOURCE_PATH, "vision_schema",
                                pack.source.source_revision, resource.source_digest)
        if expected not in self._pins:
            _fail("definition", "exact resource is not selected by owner adoption", "definition_unavailable")
        if (resource.kind != "vision_schema" or resource.source_ref != ResourceRef(
                "astrid-managed", "managed_pack", "vision", pack.source.source_revision)
                or resource.source_digest != descriptor["resource_sha256"]
                or hashlib.sha256(resource.content).hexdigest() != resource.source_digest):
            _fail("definition", "resource provenance or byte digest mismatch", "definition_mismatch")
        if len(resource.content) > 65536:
            _fail("definition", "declarative resource exceeds metadata bound", "definition_mismatch")
        try:
            schema = json.loads(resource.content)
        except (ValueError, UnicodeDecodeError):
            _fail("definition", "invalid declarative resource", "definition_mismatch")
        if schema != DEFINITION_CONTRACT:
            _fail("definition", "unsupported declarative semantics", "definition_mismatch")


class VisionValidator:
    def __init__(self, definitions: ManagedVisionDefinitions, *,
                 target_reader: Callable[[ReferenceBinding], Mapping[str, Any] | None]):
        self.definitions = definitions
        if not callable(target_reader):
            raise TypeError("Vision validation requires the host's authorized target reader")
        # The host binds DAT visibility and, where applicable, project grants.
        # Unavailable/denied targets both return None. Unexpected failures raise.
        self.target_reader = target_reader

    def validate(self, content: Any, target: ResourceRef, *, previous: Any = None) -> dict[str, Any]:
        _object(content, "content", FIELDS, REQUIRED)
        try:
            encoded = canonical_json(content).encode("utf-8")
            value = json.loads(encoded)
        except (TypeError, ValueError, UnicodeError):
            _fail("content", "must be UTF-8 JSON")
        if len(encoded) > MAX_BYTES:
            _fail("content", "exceeds 32768 UTF-8 bytes")
        if content["schema"] != SCHEMA or content["kind"] not in KINDS:
            _fail("schema/kind", "unsupported schema or kind")
        if previous is not None and (not isinstance(previous, Mapping)
                                     or previous.get("definition") != content["definition"]):
            _fail("definition", "existing canonical pin cannot be replaced by a draft", "definition_mismatch")
        self.definitions.resolve(content["definition"])
        for name, limit in (("title", 160), ("summary", 1000)):
            _text(content[name], name, limit)
        if not isinstance(content["body_markdown"], str):
            _fail("body_markdown", "must be text")
        value.setdefault("maturity", "sketch")
        if value["maturity"] not in MATURITIES:
            _fail("maturity", "unknown value")
        try:
            if not isinstance(content["as_of"], str) or date.fromisoformat(content["as_of"]).isoformat() != content["as_of"]:
                _fail("as_of", "must be an ISO calendar date")
        except ValueError:
            _fail("as_of", "must be an ISO calendar date")
        for name in ("horizon", "navigation_parent", "repository", "members"):
            value.setdefault(name, None)
        for name in ("applies_to", "relationships", "sources", "work_refs"):
            value.setdefault(name, [])
        if value["horizon"] is not None:
            _object(value["horizon"], "horizon", ("label", "target_range"), ("label",))
            for name, text in value["horizon"].items():
                _text(text, "horizon." + name, 160)
        if value["repository"] is not None:
            if value["kind"] != "repository":
                _fail("repository", "only repository descriptions carry this field")
            _object(value["repository"], "repository", ("key", "locator"), ("key",))
            for name, text in value["repository"].items():
                _text(text, "repository." + name, 80 if name == "key" else 1024)
        if value["navigation_parent"] is not None:
            parent = _binding(value["navigation_parent"], "navigation_parent", target.authority, current_only=True)
            if _identity(parent.ref) == _identity(target):
                _fail("navigation_parent", "self-parent is invalid")
            self._known_kind(parent, "navigation_parent")
        for field, limit, kind in (("applies_to", 16, "repository"), ("members", 128, None)):
            items = value[field]
            if items is None and field == "members":
                continue
            if field == "members" and value["kind"] != "product":
                _fail(field, "only product roots carry a roster")
            seen = set()
            for index, item in enumerate(_array(items, field, limit)):
                binding = _binding(item, f"{field}[{index}]", target.authority, current_only=True)
                identity = _identity(binding.ref)
                if identity in seen or (field == "members" and identity == _identity(target)):
                    _fail(field, "duplicate or self member")
                seen.add(identity)
                self._known_kind(binding, field, kind)
        ids, edges = set(), set()
        for index, edge in enumerate(_array(value["relationships"], "relationships", 32)):
            path = f"relationships[{index}]"
            _object(edge, path, ("id", "relation", "target", "note"), ("id", "relation", "target"))
            _text(edge["id"], path + ".id", 80)
            if edge["id"] in ids or edge["relation"] not in RELATIONS:
                _fail(path, "duplicate edge ID or unknown relation")
            ids.add(edge["id"])
            binding = _binding(edge["target"], path + ".target", target.authority)
            if edge["relation"] == "supersedes" and binding.mode != "pinned":
                _fail(path, "supersedes requires a pin")
            if _identity(binding.ref) == _identity(target):
                if (edge["relation"] != "supersedes" or previous is None
                        or self.target_reader is None or self.target_reader(binding) is None):
                    _fail(path, "self-link requires supersedes to an existing older revision")
            key = (edge["relation"], canonical_json(edge["target"]))
            if key in edges:
                _fail(path, "duplicate relation target")
            edges.add(key)
            if "note" in edge:
                _text(edge["note"], path + ".note", 1000, False)
            self._known_kind(binding, path)
        seen = set()
        for item in _array(value["sources"], "sources", 16):
            _object(item, "sources[]", ("ref", "use", "note"), ("ref", "use"))
            ref = _ref(item["ref"], "sources[].ref", target.authority)
            if not ref.is_pinned or item["use"] not in ("owner-intent", "observation", "rationale", "prior-context"):
                _fail("sources[]", "exact revision and supported use required")
            key = canonical_json(item["ref"])
            if key in seen:
                _fail("sources", "duplicate source ref")
            seen.add(key)
            if "note" in item:
                _text(item["note"], "sources[].note", 1000, False)
        seen = set()
        for item in _array(value["work_refs"], "work_refs", 8):
            ref = _ref(item, "work_refs[]", target.authority, kinds=("work.project", "work.task", "wrk.portfolio"))
            key = canonical_json(ref)
            if key in seen:
                _fail("work_refs", "duplicate ref")
            seen.add(key)
            visible = self.target_reader(ReferenceBinding(ref, "pinned" if ref.is_pinned else "current"))
            if visible is None:
                _fail("work_refs[]", "actual authorized Work reference unavailable", "document_unavailable")
            resolved = visible.get("resolved")
            if isinstance(resolved, Mapping):
                resolved = ResourceRef.from_dict(resolved)
            if (not isinstance(resolved, ResourceRef) or _identity(resolved) != _identity(ref)
                    or (ref.is_pinned and resolved != ref)):
                _fail("work_refs[]", "reader did not resolve the actual Work reference")
        if len(canonical_json(value).encode("utf-8")) > MAX_BYTES:
            _fail("content", "normalized content exceeds 32768 UTF-8 bytes")
        return value

    def _known_kind(self, binding: ReferenceBinding, path: str, kind: str | None = None) -> None:
        visible = self.target_reader(binding) if self.target_reader is not None else None
        if visible is None:
            return  # Unavailable targets are diagnostics, never an existence oracle.
        content = visible.get("content")
        document = visible.get("document")
        role = document.get("role") if isinstance(document, Mapping) else getattr(document, "role", None)
        if (role != "vision" or not isinstance(content, Mapping) or content.get("schema") != SCHEMA
                or content.get("kind") not in KINDS or (kind is not None and content.get("kind") != kind)):
            _fail(path, "visible target has wrong required kind")


def diagnose_collection(nodes: Mapping[str, Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Structural diagnostics over an already authorized bounded projection.

    Keys are canonical ref JSON for the source identity. No inventory/target
    hydration occurs. Authored refs remain visible; hidden target metadata does
    not enter results. Query/access enforcement is the V03 caller's duty.
    """
    if len(nodes) > 129:
        _fail("collection", "root plus 128 members exceeded", "collection_limit_exceeded")
    findings, parents = [], {}
    for source, node in nodes.items():
        parent = node.get("navigation_parent")
        links = [("navigation_parent", parent)] if parent else []
        links += [("applies_to", item) for item in node.get("applies_to", [])]
        links += [(edge["id"], edge["target"]) for edge in node.get("relationships", [])]
        for field, binding in links:
            ref = ResourceRef.from_dict(binding["ref"])
            target = canonical_json(ResourceRef(ref.authority, ref.kind, ref.id))
            if target not in nodes:
                findings.append({"source": source, "field": field, "code": "unresolved_or_outside_collection", "target": binding["ref"]})
            if field == "navigation_parent":
                parents[source] = target
    for source in sorted(parents):
        visited, current = set(), source
        while current in parents and current not in visited:
            visited.add(current)
            current = parents[current]
        if current == source:
            findings.append({"source": source, "code": "navigation_cycle"})
    return tuple(findings)
