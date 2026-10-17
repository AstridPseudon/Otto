# Role, assurance and accounting configuration

Preserve the seven Megado slots: coordinator, worker_normal, worker_xhard, reviewer_normal, reviewer_xhard, oracle, final_reviewer. They are replaceable responsibility bindings, not kernel enums. This edition routes normal implementation to Luna High, normal independent review to Luna Extra High, XHARD implementation/review to Sol High, and selected holistic/oracle judgment to Astra High. A portfolio may bind its coordinator to Astra Low and project coordinators to Luna Extra High. These instance choices do not change responsibilities.

The adopted model/stage/budget declaration is `run.json` (JSON) in file mode. Its template is `templates/run.json` (Codex profile, the default) or `templates/run.claude.json` (Claude Code host), selected by the host you run on. An existing run's `run.yaml` (JSON content) is still read. The run `mode` is `planning_only`, `setup_not_activated` or `delivery`. In native mode it is a versioned configuration record rendered by the shared work tools. Do not maintain two editable authorities. Select modes, models and review policy before applicable dispatch; no field hot-swaps running agents.

A stage identifies its actual trigger, task/criterion scope, criteria source/revision, lens, reviewer role and maximum real invocations. An acceptance boundary may explicitly be tests-and-owner-judgment with a conditional model-review allowance; no model PASS is fabricated for that path. Existing required stages remain required. For new substantial delivery, explicitly configure one final independent review by the profile's `final_reviewer` (Astra High on Codex, Opus on Claude Code) before activation, following project-lifecycle.md; planning-only work creates no active review stage. Existing instance choices and budgets remain binding. Use pragmatic-review.md to select zero/one/two distinct intermediate risks, not time/file-count formulas. Requested limits resolve to authorised scopes/pools; a template supplies no grant.

The oracle default is at most three responses per coherent effort unless explicitly changed. Resumption and follow-up responses count; memory does not replace current evidence. Manager runs can reference a parent's shared pool instead of allocating private ones. State consultation triggers separately from the allowance: an unbounded useful-advice budget does not require consultation for every failed local check. A run should grant the complete in-scope correction loop, retaining explicit user limits and operational uncertainty boundaries. Tests, repeated assessments, scheduled process checks and oracle calls are not interchangeable; declare their purpose and actual charging. Periodic checks are absent by default and enabled only by an adopted instance instruction. The 3h/12h schedules of one delivery are not mandatory Megado behavior.

Budget scaling: three fits one coherent effort. For a long multi-phase or multi-repo run, set a budget per phase or milestone (name the phases) and a total. A cheaper coordinator escalates more, so budget for that. Scheduled oracle checks are declared and counted separately from decision calls. Review-stage allowances are per stage, with an explicit repeat allowance. Revisit budgets at milestones; never silently top up or reset them.

Uncertain invocation outcomes remain held/charged. Request keys and frozen input references prevent accidental duplicate calls; changed arguments under an old key are conflicts. A proved pre-dispatch failure may release an unused reservation. Policy amendments retain actual use and exact previous decisions; new stage names cannot replenish an equivalent scope.

The manager decides what to do. Tools may refuse an expired authoring token, wrong authority, unmet required decision, missing input or exhausted limit. They need not judge intellectual difficulty, invent dependencies or execute a template as a program.

## Glossary: user words → slots

| User word | Slot or mechanism |
| --- | --- |
| manager, lead, coordinator | `coordinator` |
| orchestrator, "you" (the persistent session the user talks to), judge | `oracle` (plus its own `scheduled_checks`) |
| worker, implementer | `worker_normal` or `worker_xhard`, by route |
| reviewer, critic | `reviewer_normal` or `reviewer_xhard` |
| final review | `final_reviewer` |
| advisor | the project-advisor protocol (`protocols/project-advisor.json`) |

An "orchestrator check every N hours" is a `scheduled_checks` entry owned by the oracle, not the project-advisor cadence; the advisor protocol defaults to +1h/+3h then 6-hourly and is inactive unless adopted. A scheduled check needs a real host scheduler (Codex automations; Claude Code: CronCreate, `/loop` or `/schedule`) and stays inactive until activation. A Claude Code subagent that waits on its children can show as "completed"; check its retained handles, not its status line.
