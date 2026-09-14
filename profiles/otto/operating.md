# Otto operating profile: bounded handoff and launcher custody

This profile is a small reusable cue card for OTT-02 launcher adapters and OTT-05 repository/integration work. It carries the adopted P01 follow-through lessons into the maintained Otto development repository. It does not create a control store, scheduler, test stage, or acceptance gate.

The control root is the portfolio that invoked the work. The Otto checkout is a disposable candidate or owned development checkout. Never treat the package seed, a pinned Astrid/Runtime source checkout, or the live controller as a writable development destination.

## One brief before one handoff

A brief and its generated custody record travel together. The brief must name:

- the absolute control root, candidate checkout/worktree, baseline commit and tree, and allowed source paths;
- the public command entrypoint, original caller fields, logical key, operation/target/resource/schema/payload/actor, and the owner transaction plus receipt/event boundary;
- the intended outcome, the exact source/input manifest, the acceptance observation, and the return condition;
- the requested model, reasoning effort, write mode, and actual process/session identifier once launched.

A compact example is:

```yaml
control_root: /absolute/portfolio/root
candidate_worktree: /absolute/portfolio/owned-worktree
baseline: {commit: <commit>, tree: <tree>}
allowed_paths: [src/otto/..., tests/otto/...]
route: {model: <known-model>, reasoning: <known-effort>, write_mode: isolated-branch}
command:
  public_entrypoint: <adapter command or method>
  caller: {actor: <original-actor>, session: <session-id>}
  logical_key: <same-key-used-by-the-fixture>
  operation: <operation>
  target: <target>
  resource: <resource>
  schema: <schema>
  payload_digest: <digest>
  owner_boundary: <transaction/receipt/event owner>
inputs:
  - path: <absolute-or-root-relative-input>
    commit: <commit-if-versioned>
    tree: <tree-if-versioned>
    sha256: <recorded-sha256>
acceptance: <observable-result-and-exact-receipt-or-event-locator>
return_condition: <terminal-handoff-or-explicit-blocker>
```

The caller and actor in this record are the original authenticated values. A launcher or adapter must not invent a worker actor merely to satisfy an owner-prefix check, and a command must not bypass its public port through raw SQL, a broad store, or a private helper.

## Valid harness setup and command observation

Use one current matrix. Before the first action, capture an immediate baseline for the same logical key: fresh read, row/event/receipt counts, and the current revision/version/token where applicable. Then prove a successful first action through the real public command path. A changed request uses the same logical key and a deliberately changed operation, target, payload, or actor; it must be rejected with no durable delta when rejection is expected.

Record the command phase explicitly:

1. setup and input validation;
2. public command invocation;
3. owner transaction and durable receipt/event result;
4. fresh read or restart read;
5. changed-input, stale-token, foreign-descriptor, or replay check.

A harness setup failure is not a product pass or failure: classify missing dependencies, an invalid fixture, an unavailable optional provider, and a stale/queued process separately. A valid fixture that reaches the public command and fails is a product defect. An unresolved current row makes the current matrix nonzero. Do not sum separate supplement counts into a synthetic acceptance total.

For descriptor inventories, the matrix must bijectively match the independent persisted candidate inventory. If a supported row is removed, retain its historical row key and the exact invariant/reason for removal. The current authoritative set and the historical set are separate facts.

## Queue, resume, and terminal custody

A queued request is only a request. It is not evidence that work ran or that an amendment was applied. Before reporting a handoff, inspect the process/session status and its output. If the work is terminal and a required amendment remains, explicitly resume that terminal context with one consolidated continuation brief; do not send another queued message and infer execution. Preserve the original launch receipt, amendment text, baseline, and process/session lineage.

One writer owns a checkout at a time. A resumed worker gets the exact baseline and allowed paths from the custody record. A new worker or checkout is required only when ownership or the source pin changes. Do not infer a collision from a shared parent PID, stale output, or a quiet terminal; verify the actual writer and checkout.

## Launch profile and input manifest

The launcher records the known model and reasoning effort it actually requested, the write mode, absolute cwd, control root, and candidate worktree. The requested profile in prose is not proof of the profile that ran. The custody record must include the process/session id or an explicit terminal/no-process observation.

Before a campaign starts, compare the full input manifest with the checkout and artifacts that will be used. Include every source commit/tree, fixture or test file, package/wheel and its SHA-256, result/receipt input, and any accepted integration commit. An omitted, changed, truncated, or contradictory current hash blocks the campaign until the manifest is corrected. The report is generated from that same manifest, so it cannot silently describe a different candidate.

```text
preflight:
  verify absolute control root and candidate cwd
  verify baseline commit/tree and allowed-path ownership
  verify requested model/reasoning/write-mode binding
  verify every manifest path exists and every SHA-256 matches
  verify the first command has an immediate baseline and a valid same-key fixture
launch:
  record actual process/session and immutable stdout/result path
  observe terminal status before claiming a handoff
report:
  cite public command phase, fresh/restart read, exact receipt/event locator,
  current matrix rows, and every unresolved or skipped row with its reason
```

Adoption is verified in the existing planned work: OTT-02 `src/otto/cli.py`, `src/otto/agents/`, `tests/otto/test_adapters.py`, and `tests/otto/test_host_adapter_usage.py` exercise the public launcher/host path; OTT-05 `src/otto/engineering/`, `profiles/otto/operating.md`, and `tests/otto/test_release_records.py` record custody, source manifests, and partial promotion. Until those tasks execute against a candidate, this file is reusable guidance only and makes no installed-origin, gate, or product-readiness claim.

## OTT-05 repository and release boundary

The shipped `otto.engineering` boundary records repository custody and exact
candidate source sets as explicit typed records. A repository has one stable
custodian and a selected process profile; the profile carries only `hourly` or
`12-hour` cadence data. It does not create a scheduler, queue, allowance,
automatic promotion, publication, or deployment.

Candidate selection, required checks, manager decision, merge observation,
source promotion, package publication, and deployment are separate public
commands. Their authorities and receipts are distinct. A completed merge only
records the observed target-head change; publication and deployment remain
`not_performed` until their own commands are explicitly authorised.

Every mutation carries the expected target head, record version, edit token,
and (when applicable) the exact source-set digest. Stale, changed, duplicate,
conflicting, and unknown outcomes are typed and do not claim a release. A
partial promotion names completed, pending, and unknown steps and may only be
resumed by the same repository owner. The JSON snapshot is an explicit caller
choice for persistence; importing or constructing the boundary performs no
release action.
