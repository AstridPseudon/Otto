## Findings

### 1. A queued runner command can launch before the owner claims custody

**Evidence:** [product_service.py:1237](/private/tmp/otto-audit-tree/src/otto/hostctl/product_service.py:1237) constructs and starts the runner; [runner.py:218](/private/tmp/otto-audit-tree/src/herzchen/fleet/runner/runner.py:218) pumps retained queued runs, reaching process launch at [runner.py:297](/private/tmp/otto-audit-tree/src/herzchen/fleet/runner/runner.py:297). The shared host claims its owner file later, at [execution_host.py:1074](/private/tmp/otto-audit-tree/src/otto/portfolio/execution_host.py:1074).

**Scenario:** A prior run leaves a queued command at a still-valid commit. On restart, `runner_core.start()` launches it. An explicit stop arriving before the next composition checkpoint, or a later host socket-bind failure, prevents the owner from serving. The command may already have changed the checkout. **Inference:** a startup reported as stopped or refused can therefore have executed a queued side effect.

**Why it matters:** A command runs without the owner-file custody that is meant to bound its lifetime and recovery.

**Proposed fix row — RUNNERCUSTODY (xhard):** Claim a non-serving owner custody phase before runner reconciliation or pumping; admit commands only after project recovery is installed. **Acceptance:** retain a queued command, stop or refuse startup immediately before host serving, and assert that it never launches; a successful restart launches it once. **Plausible mistake:** starting the host’s request threads early would admit new work before retained Due recovery.

### 2. Runner construction kills processes and rewrites results before custody

**Evidence:** [runner.py:74](/private/tmp/otto-audit-tree/src/herzchen/fleet/runner/runner.py:74) calls `reconcile()` inside `__init__`. For a retained `running` record, [runner.py:194](/private/tmp/otto-audit-tree/src/herzchen/fleet/runner/runner.py:194) resumes process-tree termination and writes an `unknown` result; it also cleans unmatched latches at line 211. Product composition invokes this constructor at [product_service.py:1237](/private/tmp/otto-audit-tree/src/otto/hostctl/product_service.py:1237), before the owner-file claim.

**Scenario:** An earlier runner left a live recorded process. A new startup obtains the Store lock, constructs the runner, kills that process and changes its result, then refuses during project composition or host start. No new host ever holds the owner file.

**Why it matters:** The kill and evidence transition cannot be undone by startup refusal. The Store lock excludes another writer to that Store, but does not establish host custody.

**Proposed fix row — RUNNERRECOVERYORDER (xhard):** Move destructive runner reconciliation behind the non-serving custody claim; keep its record read before any queued launch. **Acceptance:** with a retained running process, force a preclaim startup refusal and verify its process and result remain unchanged; a claimed restart performs fenced cleanup once. **Plausible mistake:** postponing the recovery read until after queued jobs start could run them beside an unresolved old process.

### 3. Normal close can release custody while a recorded worker survives

**Evidence:** [execution_host.py:2051](/private/tmp/otto-audit-tree/src/otto/portfolio/execution_host.py:2051) discards the termination-result map, then removes the owner file at line 2063. [claude_cli.py:109](/private/tmp/otto-audit-tree/src/otto/agents/claude_cli.py:109) returns `False` when birth cannot be verified or signalling fails; even `True` means the signal was sent, not that the group is gone.

**Scenario:** A recorded worker group remains live and `killpg` fails or its birth cannot be read. Graceful `close()` still unlinks the owner locator and finishes. **Inference:** this is a normal-close sibling of ORPHANWORKER’s forced-stop case.

**Why it matters:** A worker can continue provider or repository effects after its owner has declared custody released.

**Proposed fix row — CLOSEKILL (xhard):** Require a birth-fenced post-signal census before clean release; retain an explicit unresolved custody record and degraded close outcome when absence cannot be proved. **Acceptance:** inject a live recorded group for which termination fails; close must not report clean release, and recovery must retain its identity. **Plausible mistake:** treating a successful `killpg` call as proof that descendants exited.

### 4. Owner cleanup continues after the owner file is removed

**Evidence:** [execution_host.py:2063](/private/tmp/otto-audit-tree/src/otto/portfolio/execution_host.py:2063) removes the owner file. Only afterward does [product_service.py:1492](/private/tmp/otto-audit-tree/src/otto/hostctl/product_service.py:1492) close the worker facade and call `runner.stop()`. That stop terminates live heavy runs and writes `unknown/interrupted` results at [runner.py:224](/private/tmp/otto-audit-tree/src/herzchen/fleet/runner/runner.py:224) and [runner.py:360](/private/tmp/otto-audit-tree/src/herzchen/fleet/runner/runner.py:360). Store close and its seal follow at product_service.py:1500.

**Scenario:** A standalone heavy run is active when shutdown begins. Host children finish, so `host.close()` removes `owner.json`; the heavy run remains active until the subsequent runner stop. A crash in that interval leaves it running without the owner locator.

**Why it matters:** Shutdown’s physical cleanup occurs outside host custody, and a crash makes that gap durable.

**Proposed fix row — CLOSEORDER (xhard):** Separate “drain and join host requests” from “release owner locator”; stop and reconcile the runner and facade between those phases, then release the locator. **Acceptance:** pause shutdown after host requests join with a live heavy run and assert the locator remains until runner custody is resolved. **Plausible mistake:** stopping the runner before admitted worker landing checks finish would turn valid results into interruptions.

### 5. Startup rewrites recovery state before it knows it can own the host

**Evidence:** Before `host.start()` at [product_service.py:51](/private/tmp/otto-audit-tree/src/otto/hostctl/product_service.py:51), composition catches up the Store history projection at [product_service.py:1225](/private/tmp/otto-audit-tree/src/otto/hostctl/product_service.py:1225), rewrites project service state at [product_service.py:1318](/private/tmp/otto-audit-tree/src/otto/hostctl/product_service.py:1318), and calls startup recovery at [product_service.py:1349](/private/tmp/otto-audit-tree/src/otto/hostctl/product_service.py:1349). Recovery can save a terminal Due at [execution.py:1473](/private/tmp/otto-audit-tree/src/otto/portfolio/execution.py:1473). The Store’s clean-close marker is also consumed during opening at [store.py:925](/private/tmp/otto-audit-tree/src/herzchen/kernel/store.py:925).

**Scenario:** A retained successful Due needs finalization, but a pre-existing socket path makes `host.start()` fail. Composition has already finalized the Due and rewritten its service state; the process reports startup refusal without ever claiming a serving host. The Store writer lock makes these writes exclusive, but the owner-file boundary comes later.

**Why it matters:** Startup refusal does not mean owner recovery state was left untouched. This is distinct from COMPOSE’s requirement to reconcile *before admission*.

**Proposed fix row — STARTUPCLAIM (xhard):** Establish owner-file custody without opening request intake, then perform projection, view writes and Due recovery; serve only after those finish. Keep Store admission’s one-use marker semantics explicit. **Acceptance:** force host-claim refusal with a recoverable Due and assert its revision and project state are unchanged; successful startup still reconciles before the first request. **Plausible mistake:** claiming and serving in one step exposes unreconciled Due records.

### 6. Stale-owner removal has a claim race

**Evidence:** [execution_host.py:1031](/private/tmp/otto-audit-tree/src/otto/portfolio/execution_host.py:1031) reads and judges a stale owner file; lines 1069–1071 unlink the owner file and socket, and only line 1074 uses `O_EXCL` to claim the path.

**Scenario (inference from this interleaving):** Two direct `ExecutionHost.start()` calls read the same stale locator. A unlinks it, claims the path and binds its socket. B then executes its already-decided unlink, removing A’s new owner file and socket, and can claim the now-empty path. Two hosts can serve one directory. Normal product startups against the *same Store* are serialized by its writer lock; this race concerns direct hosts or configurations whose host directory is shared across distinct Store locks.

**Why it matters:** The custody locator and reachable socket can cease to identify the serving host.

**Proposed fix row — ATOMICOWNERCLAIM (xhard):** Serialize stale eviction and new claim as one directory-scoped ownership operation, including socket replacement. **Acceptance:** race two starters against a stale locator; exactly one serves, and the loser cannot remove the winner’s file or socket. **Plausible mistake:** an inode recheck immediately before `unlink` still leaves a check-to-unlink race.

## Checked and sound

- Current landed-lab cleanup follows result publication and acceptance ([owner_runtime.py:1124](/private/tmp/otto-audit-tree/src/otto/agents/owner_runtime.py:1124)); startup sweep requires captured Due evidence and line ancestry ([product_service.py:388](/private/tmp/otto-audit-tree/src/otto/hostctl/product_service.py:388), [labs.py:403](/private/tmp/otto-audit-tree/src/herzchen/fleet/labs.py:403)). The old LABCAPTURE ordering is not re-reported.
- `LabFleet` construction does not update Git refs; landed ref deletion and lab removal occur in the owner’s sweep path ([labs.py:384](/private/tmp/otto-audit-tree/src/herzchen/fleet/labs.py:384)).
- Other preclaim constructor effects found were private directory creation or mode tightening, runner seal-key creation, and command/tool socket binding or stale-socket unlink ([retained_native.py:72](/private/tmp/otto-audit-tree/src/otto/agents/retained_native.py:72), [store.py:38](/private/tmp/otto-audit-tree/src/herzchen/fleet/runner/store.py:38), [owner_bootstrap.py:678](/private/tmp/otto-audit-tree/src/otto/portfolio/owner_bootstrap.py:678), [product_service.py:427](/private/tmp/otto-audit-tree/src/otto/hostctl/product_service.py:427), [server.py:95](/private/tmp/otto-audit-tree/src/herzchen/fleet/tools/server.py:95)). They belong in STARTUPCLAIM’s inventory; no separate data-loss scenario was established.
- Bootstrap updates a ref and cleans its dedicated staging checkout before starting the owner ([staging.sh:85](/private/tmp/otto-audit-tree/ops/bootstrap/staging.sh:85)); this is staging setup, outside the owner’s canonical line.
- Closed status is deliberately written after host and Store release ([project_service.py:290](/private/tmp/otto-audit-tree/src/otto/hostctl/project_service.py:290)); it uses a cached projection.

## Not checked

- No tests, processes or Otto commands were run under the read-only brief. The races and failure injections above are source-derived scenarios, not observed executions.
- Arbitrary runner `argv` and dynamically injected callbacks were not enumerated; their launch and custody boundaries were traced, but their possible downstream file and Git effects depend on the supplied command.