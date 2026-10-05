# Qualified Codex metadata reader

The exact-session reader admits only explicitly qualified binary SHA256 values.
CLI 0.158.0 (`788a818fbb9596869c7a487554507cb8bdca17584b8671112b23f9e225ba35c8`)
and desktop CLI 0.159.2
(`50ac633af64851511f9bbc71032cdae7f1ba20b3234c189687d61ba846c354c5`),
and packaged daemon CLI 0.159.2
(`16593cc2f422d5f398a8e40f550ebbaf1245392528957be342c295920a300704`)
are qualified. Version labels or installation paths alone do not confer trust.

Both 0.159.2 binaries were qualified on 2026-10-05 through actual read-only lookups
of the issued worker session. The reader sent only `initialize`, `initialized`,
and `thread/read` with `includeTurns=false`. The returned session matched exactly
and its trace path passed the existing regular-file, root, and symlink fences.
No transcript, provider invocation, or task work was requested. JSON-RPC identity,
response IDs, session identity, empty turns, bounds, and process cleanup remain
enforced for all qualified binaries.

For durable installed composition, select the complete versioned package at
`~/.codex/packages/app-server-daemon/releases/0.159.2-aarch64-apple-darwin/bin/codex`
after validating its digest. Retain that package's resources and pathdirs. The
desktop application path and `current` symlinks can change on update; they should
not serve as an immutable launcher pin. Changing a package remains an explicit
qualification/adoption operation.

Before a role invocation, the owner composition can preflight its exact selected
launcher against the already-issued session:

```python
from otto.agents.codex_host_reader import CodexAppServerThreadReader
reader = CodexAppServerThreadReader(launcher=absolute_launcher)
metadata = reader(issued_session_id)
```

An `unsupported_cli_identity` failure occurs before the metadata process starts.
Check the installed binary digest and select a qualified build, or qualify a new
digest with an actual metadata lookup and protocol rejection tests. Do not remove
the digest fence or admit binaries by reported version. Preserve any UNKNOWN
role occurrence and inspect its process/admission evidence before choosing public
reassignment with a distinct intent; fixing the reader does not authorize blind
replay of that occurrence or prove successful model execution.

Focused verification from the source checkout:

```sh
PYTHONPATH=src "$PYTHON" -m unittest tests.test_codex_host_reader tests.test_workspace_write_native_attribution tests.test_manager_bootstrap_recovery -q
```
