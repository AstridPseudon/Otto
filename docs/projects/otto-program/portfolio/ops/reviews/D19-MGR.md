# D19 decision: MGR, tests/test_host_neutral_defaults.py:157-160 (the orchestrator, 17 Oct 2026)

**Decision: LAND.** No Opus call was made.

- **What changes:** the role-guidance test asserted that Codex's guidance contains `Documents/Codex`. It now asserts that it doesn't, and it is renamed to say that manager guidance is host-neutral and can name the installed command.
- **Why it's right:** MGR's row says one short, host-neutral base manager brief replaces the hard-coded Codex guidance, which embeds a `~/Documents/Codex` controller path (`operating_brief.py:25-49`). The old assertion pinned exactly what the row removes. The test still checks that a Claude host names its own installed command.
- **Scope:** this assertion and the test's name.
