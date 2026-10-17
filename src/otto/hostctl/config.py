"""The one Otto installation on this machine, and the hosts that joined it.

There is ONE Store (one authority) and one owner service principal. Each agent
CLI host (Codex, Claude Code, ...) joins it as its own orchestrator principal
with its own portfolio responsibility and adapter registry; hosts never get a
second Store or borrow another host's principal.

``installation.json`` (in ``OTTO_HOME``, default ``~/.otto``) records paths,
names and pins only; it holds no secret. The Store itself may live elsewhere
(for example where an existing owner created it); the installation points to it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import pwd
import socket
from typing import Any, Mapping, Optional

SCHEMA = "otto.installation.v1"
CLIENT_SCHEMA = "otto.host-client.v1"
HOST_KINDS = ("claude-code", "codex")
# A client may point at a Store anywhere, but never keeps its OWN runtime
# files (sockets, IPC, receipts) inside another host's receiving trees.
FORBIDDEN_RUNTIME_PREFIXES = ("~/Documents/Codex", "~/.codex/owner-services", "/tmp/otto-", "/private/tmp/otto-")


class HostConfigError(ValueError):
    pass


def otto_home(explicit: Optional[str] = None, *, environ: Optional[Mapping[str, str]] = None) -> Path:
    """--home > OTTO_HOME > ~/.otto."""
    env = os.environ if environ is None else environ
    value = explicit or env.get("OTTO_HOME") or "~/.otto"
    return Path(os.path.expanduser(value)).absolute()


def host_kind(explicit: Optional[str] = None, *, environ: Optional[Mapping[str, str]] = None) -> Optional[str]:
    env = os.environ if environ is None else environ
    value = explicit or env.get("OTTO_HOST_KIND")
    if value is not None and value not in HOST_KINDS:
        raise HostConfigError("unknown host kind " + repr(value) + "; known: " + ", ".join(HOST_KINDS))
    return value


def config_path(home: Path) -> Path:
    return home / "installation.json"


def forbidden_runtime(path: str | Path) -> bool:
    text = os.path.realpath(os.path.expanduser(str(path)))
    for prefix in FORBIDDEN_RUNTIME_PREFIXES:
        if prefix.startswith("~"):
            expanded = os.path.realpath(os.path.expanduser(prefix))
            if text == expanded or text.startswith(expanded + "/"):
                return True
        elif text.startswith(prefix):
            return True
    return False


def new_installation(home: Path, *, store_path: str, authority: str, owner_actor: str,
                     credential_ref: str, python: str, operator_actor: Optional[str] = None,
                     repositories: Optional[Mapping[str, str | Path]] = None) -> dict[str, Any]:
    operator_actor = operator_actor if operator_actor is not None else pwd.getpwuid(os.geteuid()).pw_name
    for name, value in (("owner_actor", owner_actor), ("authority", authority), ("credential_ref", credential_ref)):
        if not isinstance(value, str) or not value.strip() or value != value.strip() or "/" in value:
            raise HostConfigError(name + " must be exact nonblank text without '/'")
    if (not isinstance(operator_actor, str) or not operator_actor.strip()
            or operator_actor != operator_actor.strip() or "/" in operator_actor):
        raise HostConfigError("operator_actor must be exact nonblank text without '/'")
    if operator_actor == owner_actor:
        raise HostConfigError("operator principal must differ from the owner service actor")
    if forbidden_runtime(home):
        raise HostConfigError("refusing an Otto home inside another host's receiving tree: " + str(home))
    repo_paths: dict[str, str] = {}
    for name, local_path in (repositories or {}).items():
        if not isinstance(name, str) or not name or name != name.strip() or "\x00" in name:
            raise HostConfigError("repository names must be exact nonblank text")
        if not isinstance(local_path, (str, Path)) or not str(local_path).strip() or "\x00" in str(local_path):
            raise HostConfigError("repository path for " + repr(name) + " must be nonblank path text")
        repo_paths[name] = str(Path(os.path.expanduser(str(local_path))).absolute())
    account = pwd.getpwuid(os.geteuid())
    return {
        "schema": SCHEMA,
        "home": str(home),
        "machine": {"hostname": socket.gethostname(), "account": account.pw_name, "uid": os.geteuid()},
        "store": {"path": str(Path(store_path).absolute()), "authority": authority},
        "owner": {"actor": owner_actor, "credential_ref": credential_ref,
                  "note": "The owner service principal holds the Store for every host. Hosts act as their own "
                          "principals; none borrows another's."},
        "operator": {"actor": operator_actor},
        "hosts": {},
        # Owner-local checkout map used by composed services. A missing or
        # empty map admits no repository for fleet assignment work.
        "repositories": repo_paths,
        "python": python,
    }


def host_entry(kind: str, *, principal: str, launcher: Optional[str], qualified_versions: list[str],
               model_profile: str, conversation: Optional[str] = None) -> dict[str, Any]:
    if kind not in HOST_KINDS:
        raise HostConfigError("host kind must be one of " + ", ".join(HOST_KINDS))
    if not isinstance(principal, str) or not principal.strip() or "/" in principal:
        raise HostConfigError("host principal must be exact nonblank text without '/'")
    from otto.agents.host_profiles import host_entry as packed_host_entry
    try:
        host_policy = packed_host_entry(kind, model_profile=model_profile)
    except ValueError as exc:
        raise HostConfigError(str(exc)) from exc
    settings = dict(host_policy["adapter_settings"])
    settings["launcher"] = launcher
    if kind == "claude-code":
        settings["qualified_versions"] = list(qualified_versions)
    adapters = {host_policy["adapter"]: settings}
    # Without a native session id the orchestrator's conversation is its receipt
    # mailbox: help is retained for inspection (`ottoctl help read`), not pushed.
    return {"kind": kind, "principal": principal, "model_profile": model_profile, "adapters": adapters,
            "conversation": conversation or (kind + ":receipt-mailbox:" + principal)}


def load(home: Path) -> dict[str, Any]:
    path = config_path(home)
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError:
        raise HostConfigError("no Otto installation at " + str(home) + "; run `ottoctl install` "
                              "(see `ottoctl install --help`)")
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise HostConfigError(str(path) + " is not an " + SCHEMA + " document")
    for key in ("store", "owner", "operator", "hosts", "home"):
        if key not in value:
            raise HostConfigError(str(path) + " lacks " + key)
    operator = value["operator"].get("actor") if isinstance(value["operator"], Mapping) else None
    if (not isinstance(operator, str) or not operator.strip() or operator != operator.strip()
            or "/" in operator or operator == value["owner"].get("actor")
            or any(entry.get("principal") == operator for entry in value["hosts"].values())):
        raise HostConfigError(str(path) + " has an invalid or shared operator principal")
    if Path(value["home"]) != home:
        raise HostConfigError("installation belongs to " + value["home"] + ", not " + str(home))
    repositories = value.setdefault("repositories", {})
    if not isinstance(repositories, dict):
        raise HostConfigError(str(path) + " repositories must be an object mapping repo names to local paths")
    for name, local_path in repositories.items():
        if (not isinstance(name, str) or not name or name != name.strip() or "\x00" in name
                or not isinstance(local_path, str) or not local_path.strip() or "\x00" in local_path):
            raise HostConfigError(str(path) + " contains an invalid repository name or local path")
    if value.get("machine", {}).get("uid") != os.geteuid():
        raise HostConfigError("installation belongs to another account")
    return value


def map_repository(home: Path, name: str, local_path: str | Path) -> dict[str, Any]:
    """Add or update one owner-local repository checkout mapping."""
    config = load(home)
    if not isinstance(name, str) or not name or name != name.strip() or "\x00" in name:
        raise HostConfigError("repository names must be exact nonblank text")
    if not isinstance(local_path, (str, Path)) or not str(local_path).strip() or "\x00" in str(local_path):
        raise HostConfigError("repository path for " + repr(name) + " must be nonblank path text")
    config.setdefault("repositories", {})[name] = str(Path(os.path.expanduser(str(local_path))).absolute())
    write(home, config, replace=True)
    return config["repositories"]


def host(config: Mapping[str, Any], kind: Optional[str]) -> Mapping[str, Any]:
    """The joined host this command acts for (explicit, OTTO_HOST_KIND, or the only one)."""
    hosts = config.get("hosts") or {}
    chosen = host_kind(kind)
    if chosen is None:
        if len(hosts) != 1:
            raise HostConfigError("name the host (--host or OTTO_HOST_KIND); joined: " + (", ".join(hosts) or "none"))
        chosen = next(iter(hosts))
    if chosen not in hosts:
        raise HostConfigError(chosen + " is not admitted to this Otto; the owner admits it with `ottoctl service admit-host --host " + chosen + "`")
    return hosts[chosen]


def write(home: Path, value: Mapping[str, Any], *, replace: bool = False) -> Path:
    path = config_path(home)
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    temporary = path.with_name(".installation.json.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    if not replace and path.exists():
        os.unlink(temporary)
        raise HostConfigError(str(path) + " already exists")
    os.replace(temporary, path)
    return path


# -- host clients ---------------------------------------------------------------
# A host's client home holds only client.json (which host principal, which
# lane) and its lanes. It names no Store path: a client never opens the Store.

def client_path(home: Path) -> Path:
    return home / "client.json"


def load_client(home: Path) -> dict[str, Any]:
    path = client_path(home)
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError:
        raise HostConfigError("no admitted host at " + str(home) + "; the owner admits a host with "
                              "`ottoctl --home <service home> service admit-host --host <kind> --client-home "
                              + str(home) + "`")
    if not isinstance(value, dict) or value.get("schema") != CLIENT_SCHEMA or not isinstance(value.get("hosts"), dict):
        raise HostConfigError(str(path) + " is not an " + CLIENT_SCHEMA + " document")
    return value


def client_host(client: Mapping[str, Any], kind: Optional[str]) -> Mapping[str, Any]:
    hosts = client.get("hosts") or {}
    chosen = host_kind(kind)
    if chosen is None:
        if len(hosts) != 1:
            raise HostConfigError("name the host (--host or OTTO_HOST_KIND); admitted here: " + (", ".join(hosts) or "none"))
        chosen = next(iter(hosts))
    if chosen not in hosts:
        raise HostConfigError(chosen + " is not admitted at this client home")
    return dict(hosts[chosen], kind=chosen)


def write_client(home: Path, kind: str, entry: Mapping[str, Any]) -> Path:
    path = client_path(home)
    try:
        value = load_client(home)
    except HostConfigError:
        value = {"schema": CLIENT_SCHEMA, "hosts": {}}
    value["hosts"][kind] = dict(entry)
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    temporary = path.with_name(".client.json.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    return path
