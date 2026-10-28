# Otto program: purpose and shape

Otto is intended to be one local service through which Claude, Codex, and future agent hosts work safely across projects. People author plans once in Otto. Otto admits reviewed tasks, dispatches those whose dependencies are met, gives each an isolated lab, runs checks, and lands passing work on the project’s line. Managers handle questions and exceptions; routine work and acceptance are owned by the service. The goals are more concurrent work without memory pressure, fewer idle resources, and less heavy compute per accepted task. [PLAN.md §1–3](portfolio/PLAN.md)

The architecture has three layers, with dependencies pointing down:

- **Herzchen model** owns typed work records, dependencies, admission, assessment, evidence, documents, and capacity. This replaces parsed tasklists and filesystem mirrors as sources of truth.
- **Herzchen fleet** runs agents: host adapters, sessions, isolated labs, dispatch, process custody, worker tools, a shared runner, and landing. It is reusable by other products.
- **Otto product** provides project and manager policy, roles, reviews and approvals, the `otto` command, install, and upgrade. It composes the lower layers; they do not depend on Otto.

The consolidation creates one path for each core job: one work schema and evidence-backed acceptance, one pool for agent turns and heavy commands, one owner transport, one lab lifecycle, and one dispatch/landing path. Workers use four tools—`task`, `check`, `ask`, `done`—with clear next steps on refusal. [PLAN.md D2–D15; AGENT-UX.md]

Milestones: **take ownership** of canonical source and bootstrap tooling; **build edition 1** in isolated labs and prove it through a staging Otto; then **CUTOVER**, saving and verifying active projects in the new Otto before moving clients. Staging stages cover boot, planning, dispatch, real work, landing, management, dogfooding, and multi-agent use, followed by a whole-edition review. SLIM, EFFECTS, PACKS, HARNESS3, THROUGHPUT, ASTRIDFLEET, and PROCLIFE are follow-on cleanup and efficiency projects, gated on edition 1. [PLAN.md §3, §14, §16; projects/program/tasklist.md; projects/{slim,effects,packs,harness3,throughput,astrid-fleet,process-lifecycle}/tasklist.md]

In source, the boundary appears in `source/otto/src/herzchen/domains/` (work and assessment), `source/otto/src/herzchen/kernel/` (shared primitives), `source/otto/src/herzchen/fleet/` (execution), and `source/otto/src/otto/` (product/composition), especially `herzchen/fleet/{hosts,runner,tools}/` and `otto/hostctl/`. [PLAN.md D14]
