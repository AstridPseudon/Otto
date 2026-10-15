"""Compose the one owner over the one Store, using only supported owner APIs.

``create_store`` performs first admission for a brand-new installation (tests,
a fresh machine): ``Store.create`` plus the owner's full domain set. An existing
Store (for example the one Codex's owner created) is only *attached*: opened
with the exact persisted descriptor set, never recreated. ``join_host`` gives an
agent CLI host its own orchestrator principal and portfolio responsibility via
``ResponsibilityAssignments.assign``. ``HostSession`` holds the Store's
exclusive writer lock for one command and never opens any other Store. No
provider is called anywhere in this module.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
from pathlib import Path
import stat
from typing import Any, Iterator, Mapping, Optional

from herzchen.contracts import ResourceRef

# Inside the running owner service, every composition reuses the ONE Store the
# service holds open; nothing in the service opens the file a second time.
_SERVICE_STORE: ContextVar[Any] = ContextVar("otto_service_store", default=None)


@contextmanager
def service_store(store: Any) -> Iterator[None]:
    """Compose HostSessions over the service's open Store (owner service only)."""
    token = _SERVICE_STORE.set(store)
    try:
        yield
    finally:
        _SERVICE_STORE.reset(token)


def host_domains() -> tuple:
    """The owner's complete domain set, in canonical order.

    It equals the set the existing owner services register (work with
    orchestration and assignment resources, content, packets, authoring,
    assessment, Due records, direction bindings/adoption and Evidence), so
    every host reopens the same Store with the exact same descriptors.
    """
    from herzchen.authoring import domain_contribution as authoring
    from herzchen.content import domain_contribution as content
    from herzchen.content.packets import domain_contribution as packets
    from herzchen.domains.assessment.module import contribution as assessment
    from herzchen.domains.work import contributions
    from herzchen.evidence.commands import domain_contribution as evidence
    from otto.attention import due_record_contribution
    from otto.portfolio.direction import adoption_contribution, contribution as direction
    items = (*contributions(include_orchestration=True, include_assignment_resources=True),
             content(), packets(), authoring(), assessment(), due_record_contribution(),
             direction(), adoption_contribution(), evidence())
    return tuple(sorted(items, key=lambda item: item.domain_id))


def _private_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        raise PermissionError(str(path) + " must be a directory owned by this account (no symlink)")
    if info.st_mode & 0o077:
        os.chmod(path, 0o700)


def native_body_root(config: Mapping[str, Any]) -> Path:
    """Where this Otto home keeps each host turn's transcript, once, by digest.

    Beside the other private runtime state, never inside a Store's directory or
    another host's receiving tree. One directory per Store authority.
    """
    return Path(config["home"]) / "state" / "native-bodies" / config["store"]["authority"]


def runtime_dirs(config: Mapping[str, Any]) -> None:
    home = Path(config["home"])
    for path in (home, home / "run", home / "receipts", home / "projects", home / "bin"):
        _private_dir(path)


def create_store(config: dict[str, Any]) -> dict[str, Any]:
    """First admission of a NEW Store; refuses an existing file."""
    from herzchen.kernel.store import Store
    runtime_dirs(config)
    store_path = Path(config["store"]["path"])
    if store_path.exists():
        raise FileExistsError("a Store already exists at " + str(store_path) + "; attach it instead")
    store_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    store = Store.create(store_path, authority=config["store"]["authority"])
    try:
        os.chmod(store_path, 0o600)
        store.register_domain_handler(host_domains())
    finally:
        store.close()
    return attach_store(config)


def attach_store(config: dict[str, Any]) -> dict[str, Any]:
    """Open the existing Store once with the exact domain set and pin its identity."""
    from herzchen.kernel.store import Store
    runtime_dirs(config)
    store_path = Path(config["store"]["path"])
    store = Store.open(store_path, authority=config["store"]["authority"], expected_domains=host_domains())
    try:
        digest = store.domain_descriptor_digest
    finally:
        store.close()
    info = os.stat(store_path)
    config["store"].update(domain_descriptor_digest=digest, device_inode=[info.st_dev, info.st_ino])
    return config


def join_host(config: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """Give a host its own orchestrator principal and portfolio responsibility."""
    with HostSession(config) as session:
        portfolio = ResourceRef(config["store"]["authority"], "wrk.portfolio", entry["kind"] + "-portfolio")
        # The orchestrator's conversation locator: where help for it is retained.
        # It names the host's own session (or its receipt mailbox), never another's.
        root = session.owner.assignments.assign(portfolio, role="orchestrator", principal=entry["principal"],
                                                session=entry.get("conversation"),
                                                logical_request_key="host-join:" + entry["kind"] + ":v1")
    entry = dict(entry, portfolio_ref=portfolio.to_dict(), root_assignment_ref=root.ref.to_dict(),
                 root_generation=root.generation)
    config.setdefault("hosts", {})[entry["kind"]] = entry
    return entry


class HostSession:
    """Owner composition over the one Store.

    Inside the running owner service (``ottoctl service run``) it composes over
    the Store the service already holds. Outside it, only the operator's
    ``install`` and the service itself open the file, under its exclusive
    writer lock; host clients never construct one (they use their lane).
    """

    def __init__(self, config: Mapping[str, Any], *, host: Optional[Mapping[str, Any]] = None,
                 project_ids: tuple = ()) -> None:
        self.config, self.host = config, host
        self.project_ids = tuple(project_ids)
        self.store = None
        self._owns_store = False

    def __enter__(self) -> "HostSession":
        from herzchen.kernel.store import Store
        from otto.attention import due_record_contribution, issue_store_due_record_port
        from otto.portfolio.herzchen_binding import HerzchenBindingConfig, ProjectReadGrant
        from otto.portfolio.intake import OttoPortfolio
        from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
        target = self.config["store"]
        shared = _SERVICE_STORE.get()
        if shared is not None:
            self.store = shared
        else:
            path = Path(target["path"])
            for part in (path, *path.parents):
                if part.exists() and stat.S_ISLNK(part.lstat().st_mode):
                    raise PermissionError("Store path contains a symbolic link")
            info = path.stat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or [info.st_dev, info.st_ino] != target["device_inode"]):
                raise PermissionError("Store custody or identity changed since it was attached")
            self.store = Store.open(path, authority=target["authority"], expected_domains=host_domains(),
                                    expected_domain_digest=target["domain_descriptor_digest"])
            self._owns_store = True
        try:
            authority, actor = target["authority"], self.config["owner"]["actor"]
            self.binding = HerzchenBindingConfig(authority, self.config["owner"]["credential_ref"])
            self.actor = self.binding.authenticated_actor(actor)
            grant = None
            if self.project_ids:
                grant = ProjectReadGrant(self.actor, self.project_ids, "otto.host-owner.v1", "v1")
            orchestration = {}
            if self.host is not None and self.host.get("root_assignment_ref"):
                # The host's own portfolio: its principal creates and orchestrates
                # there; no other host's principal is admitted to it.
                orchestration = {"portfolio_ref": ResourceRef.from_dict(self.host["portfolio_ref"]),
                                 "main_assignment_ref": ResourceRef.from_dict(self.host["root_assignment_ref"]),
                                 "expected_main_principal": self.host["principal"],
                                 "allowed_creator_ids": (self.host["principal"],),
                                 "privileged_actor_ids": (self.host["principal"],)}
            self.owner = PortfolioOwnerBootstrap(self.store, binding=self.binding, owner_actor=actor,
                project_read_grant=grant, folder_transport_request_bytes=256 * 1024 * 1024, **orchestration)
            # Transcripts are stored once, by digest; Due records and their events
            # carry a small reference (digest, bytes, media type) instead.
            from otto.agents.retained_native import RetainedNativeBodies
            self.native_bodies = RetainedNativeBodies.on_files(native_body_root(self.config), self.actor)
            self.due_port = issue_store_due_record_port(self.store.domain_handler((due_record_contribution(),)),
                                                        self.actor, native_bodies=self.native_bodies)
            self.portfolio = OttoPortfolio(self.owner.consumer_operations())
            return self
        except BaseException:
            if self._owns_store:
                self.store.close()
            raise

    def __exit__(self, *_: Any) -> None:
        if self.store is not None and self._owns_store:
            self.store.close()

    # -- composed services --------------------------------------------------
    def root_assignment(self) -> Any:
        if self.host is None:
            raise ValueError("no host selected")
        ref = ResourceRef.from_dict(self.host["root_assignment_ref"])
        return self.owner.assignments.get(ResourceRef(ref.authority, ref.kind, ref.id))

    def host_principal(self) -> str:
        if self.host is None:
            raise ValueError("no host selected")
        return self.host["principal"]

    def service(self, run_path: Optional[str] = None) -> Any:
        """The maintained manager-journey service, bound to this host's owner.

        The invoking ottoctl process holds the Store writer lock as the owner
        account; that is the trusted owner input for owner-context and
        project-authoring commands (no manager-accessible file lane exists).
        """
        from types import SimpleNamespace
        from otto.portfolio.manager_journey_service import ManagerJourneyService
        state = {"orchestrator_assignment_ref": (self.host or {}).get("root_assignment_ref"),
                 "external_execution_tool_entrypoint": None}
        server = SimpleNamespace(owner=self.owner, portfolio=self.portfolio, state=state,
                                 due_port=self.due_port, native_bodies=self.native_bodies,
                                 _execution=lambda **kw: None,
                                 _save_state=lambda: None, handle=self._unsupported)
        home = Path(self.config["home"])
        return ManagerJourneyService(server=server, host=None, run_path=run_path or home, workspace=home,
                                     authoring_authorizer=lambda request: self.owner.owner_actor)

    @staticmethod
    def _unsupported(request: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"outcome": "unavailable", "provider_called": False,
                "reason": "command requires the running owner service (`ottoctl service run`)",
                "command": request.get("command")}

    def execution_application(self, adapter: Any, *, manager_actor: Optional[str] = None) -> Any:
        from otto.agents.claude_adapter import ClaudeNativeResultVerifier
        verifier = ClaudeNativeResultVerifier() if getattr(adapter, "adapter_identity", "").startswith(
            "otto.adapter.claude-code") else None
        options = {"native_result_verifier": verifier} if verifier is not None else {}
        from otto.portfolio.help_delivery import BoundHelpDelivery
        from otto.portfolio.owner_issue_loop import OwnerIssueReaders
        delivery = BoundHelpDelivery(readers=OwnerIssueReaders(self.owner.consumer_operations(), self.due_port))
        return self.owner.execution_application(due_port=self.due_port, adapter=adapter, issue_delivery=delivery,
                                                manager_actor=manager_actor or self.actor.actor,
                                                native_bodies=self.native_bodies, **options)


def json_out(value: Any) -> str:
    def default(item: Any) -> Any:
        if hasattr(item, "to_dict"):
            return item.to_dict()
        if isinstance(item, (set, frozenset, tuple)):
            return list(item)
        return str(item)
    return json.dumps(value, indent=2, sort_keys=True, default=default, ensure_ascii=False)
