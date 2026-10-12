"""Finite own-root onboarding facade over existing owner and consumer ports.

This module never opens a Store. A trusted host supplies the already-open owner,
serialized owner-lane callback, current portfolio/document capabilities, and the
existing queue and reviewed-activation operations. Callers receive only a
finite command-facade transport descriptor.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
from typing import Any, Mapping

from herzchen.contracts import ResourceRef

MAX_ARGUMENT_BYTES = 65_536
MAX_RESPONSE_BYTES = 262_144
MAX_ITEMS = 32


class _BoundOnboardingOwner:
    def __init__(self, store: Any, *, owner: Any, root_ref: Mapping[str, Any], generation: int,
                 principal: str, portfolio: Any, document_operations: Any,
                 owner_call: Any, source_readback: Any, queue_command: Any = None,
                 reviewed_activation: Any = None, attach_created_project: Any = None,
                 activation_context: Mapping[str, Any] | None = None,
                 journey_command: Any = None):
        if store is not owner.store:
            raise PermissionError("the existing owner Store capability is required")
        if not callable(owner_call) or not callable(source_readback):
            raise ValueError("existing owner lane and source readback are required")
        self._owner = owner
        self._root_ref = ResourceRef.from_dict(root_ref)
        self._generation = generation
        self._principal = principal
        self._portfolio = portfolio
        self._documents = document_operations
        self._owner_call = owner_call
        self._source_readback = source_readback
        self._queue = queue_command
        self._activation = reviewed_activation
        self._journey_command = journey_command
        self._attach_created_project = attach_created_project
        self._activation_context = dict(activation_context or {})
        if len(json.dumps(self._activation_context, separators=(",", ":")).encode()) > MAX_ARGUMENT_BYTES:
            raise ValueError("activation context exceeds the finite host policy bound")
        self._created_project: Mapping[str, Any] | None = None
        self._create_argv: tuple[str, ...] | None = None
        self._sessions: dict[str, str] = {}
        self._save_replays: dict[str, str] = {}
        self._queue_head: Mapping[str, Any] | None = None

    def _current(self) -> Any:
        root = self._owner.assignments.get(self._root_ref)
        if (root.ref != self._root_ref or root.role != "orchestrator"
                or root.generation != self._generation or root.principal != self._principal
                or getattr(root.status, "value", root.status) not in
                    {"queued", "running", "active", "assigned", "reassigned"}
                or self._owner.owner_actor.actor != self._principal
                or not isinstance(self._owner.queue_binding, dict)
                or self._owner.queue_binding.get("root") != root.ref
                or self._owner.queue_binding.get("owner") != self._owner.owner_actor
                or self._owner.queue_binding.get("portfolio") != root.scope):
            raise PermissionError("issued own-root onboarding binding is stale or foreign")
        return root

    def whoami(self) -> Mapping[str, Any]:
        def read():
            root = self._current()
            installed = self._source_readback()
            if not isinstance(installed, Mapping):
                raise ValueError("installed selection readback must be bounded JSON")
            adopted = root.payload.get("resource_adoptions", [])
            if not isinstance(adopted, list) or len(adopted) > 8:
                raise PermissionError("current root resource adoptions exceed the finite identity view")
            return {"schema": "otto.bound-onboarding-identity.v1", "principal": root.principal,
                    "assignment_ref": root.ref.to_dict(), "generation": root.generation,
                    "adopted_resources": adopted,
                    "portfolio_ref": root.scope.to_dict(), "installed_selection": dict(installed),
                    "dispatch": False, "provider_called": False}
        return self._owner_call(read)

    def help(self) -> Mapping[str, Any]:
        return {**self.whoami(),
                "entrypoint": "python -m otto.portfolio.onboarding_bound_cli --connection ISSUED_FILE --request-json JSON",
                "commands": ["whoami", "help", "onboarding create/find/reopen", "save", "release",
                             "queue read/seed/after", "activation read/apply"] +
                            (["journey read-result/read-artifact/consume-result/review-input/review-task/finish-task/finish-project"]
                             if callable(self._journey_command) else []),
                "authority": "host-issued exact current root; actor is fixed on the owner lane",
                "inert_boundary": "draft/save/reopen does not add execution tasks, roles, pools, Due records, or provider effects",
                "activation": "separate existing reviewed-plan owner operation; no worker/provider dispatch",
                "templates": "unsupported by this bounded issuance",
                "transport": "connection file is a bearer capability; keep it private"}

    def journey(self, operation: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        allowed = {"read-result", "read-artifact", "consume-result", "review-input",
                   "review-task", "finish-task", "finish-project"}
        if (operation not in allowed or not isinstance(arguments, Mapping)
                or len(json.dumps(arguments, separators=(",", ":")).encode()) > MAX_ARGUMENT_BYTES):
            raise ValueError("finite bounded manager journey operation required")
        if not callable(self._journey_command):
            raise RuntimeError("host has not issued a manager journey capability")
        def execute():
            self._current()
            result = self._journey_command(operation, dict(arguments))
            if not isinstance(result, Mapping):
                raise ValueError("manager journey returned no bounded JSON object")
            encoded = json.dumps(result, separators=(",", ":"), ensure_ascii=False).encode()
            if len(encoded) > MAX_RESPONSE_BYTES:
                raise ValueError("manager journey response exceeds the bounded transport")
            return dict(result)
        return self._owner_call(execute)

    def cli(self, argv: list[str]) -> Mapping[str, Any]:
        if (not isinstance(argv, list) or not argv or len(argv) > 64
                or any(not isinstance(item, str) or "\x00" in item for item in argv)
                or sum(len(item.encode("utf-8")) for item in argv) > MAX_ARGUMENT_BYTES):
            raise ValueError("finite bounded CLI arguments required")
        self._authorize_cli(argv)

        def execute():
            self._current()
            from otto.portfolio.cli import main
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = main([*argv, "--actor", self._principal], portfolio=self._portfolio,
                              document_operations=self._documents, bound_actor=self._principal)
            value = output.getvalue()
            if len(value.encode("utf-8")) > MAX_RESPONSE_BYTES:
                raise ValueError("response exceeds the bounded onboarding transport")
            response = json.loads(value)
            if argv[:2] == ["onboarding", "create"] and isinstance(response, Mapping) \
                    and response.get("outcome") in {"created", "partial", "replayed"}:
                project = response.get("project_ref")
                workspace = response.get("workspace")
                if not isinstance(project, Mapping) or not isinstance(workspace, Mapping) \
                        or not isinstance(workspace.get("session_id"), str):
                    raise ValueError("create lacks project/session readback; inspect its retained receipt")
                if not callable(self._attach_created_project):
                    return {"schema": "otto.bound-onboarding-cli.v1", "exit_code": status,
                            "response": response, "provider_called": False,
                            "next_action": "host must issue an exact-project reader grant before find/reopen"}
                refreshed = self._attach_created_project(dict(project))
                if (not isinstance(refreshed, Mapping)
                        or set(refreshed) != {"owner", "portfolio", "document_operations", "reviewed_activation"}
                        or refreshed["owner"].store is not self._owner.store
                        or refreshed["owner"].owner_actor.actor != self._principal
                        or refreshed["owner"].project_read_grant is None
                        or refreshed["owner"].project_read_grant.principal != refreshed["owner"].owner_actor
                        or refreshed["owner"].project_read_grant.project_ids != (project["id"],)):
                    raise PermissionError("host returned a foreign or malformed exact-project attachment")
                self._owner = refreshed["owner"]
                self._portfolio = refreshed["portfolio"]
                self._documents = refreshed["document_operations"]
                self._activation = refreshed["reviewed_activation"]
                self._created_project = dict(project)
                self._create_argv = tuple(argv)
                self._sessions[project["id"]] = workspace["session_id"]
            elif argv[:2] == ["onboarding", "reopen"] and isinstance(response, Mapping) \
                    and response.get("outcome") in {"opened", "replayed"}:
                project = response.get("project_ref")
                workspace = response.get("workspace")
                if (project != self._created_project or not isinstance(workspace, Mapping)
                        or not isinstance(workspace.get("session_id"), str)):
                    raise PermissionError("reopen did not preserve the issued project identity")
                self._created_project = dict(project)
                self._sessions[project["id"]] = workspace["session_id"]
            return {"schema": "otto.bound-onboarding-cli.v1", "exit_code": status,
                    "response": response, "provider_called": False,
                    "actor_source": "host-issued-current-root",
                    "transcript_identity": self._created_project}
        return self._owner_call(execute)

    def save(self, project_ref: Mapping[str, Any], session_id: str, project_json: Mapping[str, Any],
             document_changes: list[Mapping[str, Any]], request_key: str) -> Mapping[str, Any]:
        if (not isinstance(project_json, Mapping) or not isinstance(document_changes, list)
                or len(document_changes) > MAX_ITEMS
                or len(json.dumps([project_json, document_changes], separators=(",", ":")).encode()) > MAX_ARGUMENT_BYTES):
            raise ValueError("bounded canonical draft/save inputs required")
        if not isinstance(request_key, str) or not request_key.strip() or request_key != request_key.strip():
            raise ValueError("exact stable request key required")
        replay_digest = hashlib.sha256(json.dumps([dict(project_ref), session_id, dict(project_json),
            list(document_changes)], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        def execute():
            self._current()
            prior_digest = self._save_replays.get(request_key)
            if prior_digest is not None and prior_digest != replay_digest:
                raise PermissionError("saved check-in key was reused with changed inputs")
            if dict(project_ref) != self._created_project and prior_digest != replay_digest:
                raise PermissionError("save target differs from the host-created project")
            if self._sessions.get(project_ref.get("id")) != session_id:
                raise PermissionError("save session is stale or foreign")
            if project_json.get("tasks") not in (None, []) or any(
                    project_json.get(field) is not None for field in ("manager", "worker", "budget", "execution")):
                raise PermissionError("inert draft save cannot introduce execution state")
            result = self._portfolio.check_in_project(project_ref, actor=self._principal, request_id=request_key,
                session_id=session_id, project_json=dict(project_json), document_changes=list(document_changes))
            if isinstance(result, Mapping) and isinstance(result.get("project_ref"), Mapping):
                self._created_project = dict(result["project_ref"])
                if result.get("outcome") in {"finished", "replayed"}:
                    self._save_replays[request_key] = replay_digest
            return result
        return self._owner_call(execute)

    def release(self, project_ref: Mapping[str, Any], session_id: str, request_key: str) -> Mapping[str, Any]:
        if not isinstance(request_key, str) or not request_key.strip() or request_key != request_key.strip():
            raise ValueError("exact stable release request key required")
        def execute():
            self._current()
            if dict(project_ref) != self._created_project or self._sessions.get(project_ref.get("id")) != session_id:
                raise PermissionError("release target or session is stale or foreign")
            result = self._portfolio.release_project(project_ref, session_id=session_id,
                actor=self._principal, request_id=request_key)
            if isinstance(result, Mapping) and result.get("outcome") in {"released", "replayed"}:
                self._sessions.pop(project_ref["id"], None)
            return result
        return self._owner_call(execute)

    def queue(self, operation: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        if (operation not in {"read", "seed", "after"} or not isinstance(arguments, Mapping)
                or len(json.dumps(arguments, separators=(",", ":")).encode()) > MAX_ARGUMENT_BYTES):
            raise ValueError("finite bounded queue operation required")
        if not callable(self._queue):
            raise RuntimeError("existing owner queue operation is unavailable")
        fields = {"read": {"consumer", "request_key"},
                  "seed": {"request_key", "order", "rule"},
                  "after": {"request_key", "order", "rule", "expected_revision", "predecessor_ref", "project_ref"}}
        if set(arguments) != fields[operation]:
            raise PermissionError("queue arguments differ from the finite maintained operation")
        if operation in {"seed", "after"}:
            order = arguments.get("order")
            if not isinstance(order, list) or not 1 <= len(order) <= MAX_ITEMS:
                raise ValueError("queue order must be a bounded canonical list")
            refs = [ResourceRef.from_dict(item) for item in order]
            if any(ref.kind != "work.project" for ref in refs) or len({_identity(ref) for ref in refs}) != len(refs):
                raise PermissionError("queue order must contain unique canonical project refs")
            if operation == "seed" and self._created_project is not None and not any(
                    _identity(ref) == _identity(self._created_project) for ref in refs):
                raise PermissionError("queue order omits the issued project")
        if operation == "after":
            if (self._created_project is None or dict(arguments["project_ref"]) != self._created_project
                    or self._queue_head is None
                    or arguments["expected_revision"] != self._queue_head.get("queue_ref", {}).get("revision")
                    or arguments["order"] != self._queue_head.get("order")
                    or arguments["predecessor_ref"] != (arguments["order"][-1] if arguments["order"] else None)
                    or arguments["rule"] != self._queue_head.get("rule")):
                raise PermissionError("queue extension must match the latest exact read and target the issued project")
        if operation == "after" and (self._created_project is None
                                      or dict(arguments["project_ref"]) != self._created_project):
            raise PermissionError("queue extension must target the host-created project")
        def execute():
            self._current()
            result = self._queue(operation, dict(arguments))
            if operation == "read" and isinstance(result, Mapping) and result.get("outcome") == "read":
                self._queue_head = dict(result)
            if operation == "after" and isinstance(result, Mapping) and result.get("outcome") == "queued":
                # Enrollment is a separate existing owner operation and can
                # advance the Work project head. Read its current exact pin
                # through the already-granted project reader before returning.
                current = self._portfolio.find_draft(actor=self._principal, project_ref=self._created_project)
                observed = current.get("project_ref") if isinstance(current, Mapping) else None
                if (not isinstance(current, Mapping) or current.get("outcome") != "read" or not isinstance(observed, Mapping)
                        or _identity(observed) != _identity(self._created_project)):
                    raise PermissionError("queued project current head could not be read back exactly")
                self._created_project = dict(observed)
                result = {**dict(result), "current_project_ref": dict(observed)}
            return result
        return self._owner_call(execute)

    def activation(self, operation: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        if operation not in {"read", "apply"} or not isinstance(arguments, Mapping):
            raise ValueError("finite reviewed activation operation required")
        if set(arguments) != {"project_ref", "plan_ref", "review_ref", "request_key"}:
            raise PermissionError("activation needs exact project, plan, review and request-key fields")
        if self._created_project is None or dict(arguments["project_ref"]) != self._created_project:
            raise PermissionError("activation project differs from the host-created project")
        if not isinstance(arguments["request_key"], str) or not arguments["request_key"].strip():
            raise ValueError("stable activation request key required")
        if self._activation is None:
            raise RuntimeError("existing reviewed activation capability is unavailable")
        for field in ("plan_ref", "review_ref"):
            ref = ResourceRef.from_dict(arguments[field])
            if ref.kind != "dat.content.document" or not ref.revision or ref.authority != self._root_ref.authority:
                raise PermissionError("activation refs must be exact immutable documents in the owner authority")
        def execute():
            self._current()
            method = self._activation.read if operation == "read" else self._activation.activate
            values = dict(self._activation_context)
            values.update({k: arguments[k] for k in ("project_ref", "plan_ref", "review_ref")})
            if operation == "apply":
                values["request_key"] = arguments["request_key"]
            return method(**values)
        return self._owner_call(execute)

    def _authorize_cli(self, argv: list[str]) -> None:
        if any(item == "--actor" or item.startswith("--actor=") for item in argv):
            raise PermissionError("actor is supplied only by the host")
        if argv[:2] == ["onboarding", "create"]:
            if not _options_exact(argv[2:], {"--request-id", "--title", "--brief"}, {"--supporting-files"}):
                raise PermissionError("create is limited to request-id, title, brief and bounded supporting files; templates are unavailable")
            if "--supporting-files" in argv:
                try:
                    supporting = json.loads(argv[argv.index("--supporting-files") + 1])
                except (IndexError, json.JSONDecodeError) as exc:
                    raise ValueError("supporting-files must be bounded JSON") from exc
                if (not isinstance(supporting, Mapping) or not 1 <= len(supporting) <= 3
                        or any(not isinstance(path, str) or not isinstance(text, str)
                               for path, text in supporting.items())
                        or sum(len(text.encode("utf-8")) for text in supporting.values()) > 24_576):
                    raise ValueError("supporting-files must contain at most three finite UTF-8 files")
            if self._create_argv is not None and tuple(argv) != self._create_argv:
                raise PermissionError("this issuance permits exact create replay only; changed input is refused")
            return
        if argv[:2] in (["onboarding", "find"], ["onboarding", "reopen"]):
            required = {"--project-ref"} | ({"--request-id"} if argv[1] == "reopen" else set())
            if not _options_exact(argv[2:], required):
                raise PermissionError("find/reopen require exact project identity and reopen request key")
            if self._created_project is None or _option_json(argv, "--project-ref") != self._created_project:
                raise PermissionError("project is outside this issuance")
            return
        raise PermissionError("command outside this finite onboarding issuance")


def issue_bound_onboarding_tool(store: Any, **bound: Any) -> tuple[Any, Any]:
    """Trusted host only: issue this facade through the existing Store command port."""
    from herzchen.command_ports import command_facade, serve_consumer_facade
    facade = command_facade(_BoundOnboardingOwner, "otto.portfolio.bound-onboarding")(store, **bound)
    return facade, serve_consumer_facade(facade)


def _options_exact(argv: list[str], expected: set[str], optional: set[str] | None = None) -> bool:
    seen: set[str] = set()
    allowed = expected | (optional or set())
    index = 0
    while index < len(argv):
        flag = argv[index]
        if flag not in allowed or flag in seen or index + 1 >= len(argv):
            return False
        seen.add(flag)
        index += 2
    return expected <= seen and seen <= allowed


def _option_json(argv: list[str], flag: str) -> Any:
    try:
        index = argv.index(flag)
        return json.loads(argv[index + 1])
    except (ValueError, IndexError, json.JSONDecodeError) as exc:
        raise ValueError("canonical project ref JSON required") from exc


def _identity(value: Any) -> tuple[str, str, str]:
    ref = value if isinstance(value, ResourceRef) else ResourceRef.from_dict(value)
    return ref.authority, ref.kind, ref.id
