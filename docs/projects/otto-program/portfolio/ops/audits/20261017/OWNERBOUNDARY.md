## Findings

### 1. Draining leaves queued owner completions unresolved

**Evidence:** [execution_host.py:800](/private/tmp/otto-audit-tree/src/otto/portfolio/execution_host.py:800) creates a completion for an admitted execution. The start pump returns immediately when `_closing` is set ([line 894](/private/tmp/otto-audit-tree/src/otto/portfolio/execution_host.py:894)); `begin_drain` sets that flag ([line 2079](/private/tmp/otto-audit-tree/src/otto/portfolio/execution_host.py:2079)). A socket consumer waits without a deadline for the completion ([line 1447](/private/tmp/otto-audit-tree/src/otto/portfolio/execution_host.py:1447)), while `close` joins admitted connection threads ([line 2035](/private/tmp/otto-audit-tree/src/otto/portfolio/execution_host.py:2035)).

**Scenario:** Worker A occupies the last turn slot; a socket request admits B, which remains queued. Drain begins before A finishes. B is never started or resolved. Its socket thread waits forever, and graceful close waits for that thread. This can prevent an owner from stopping cleanly.

**Proposed fix row — xhard:** Settle every queued, never-started execution with a held, no-effects result during drain; preserve its retained request for explicit recovery. Acceptance: with capacity one, admit A and queue B through a socket, begin drain, finish A, and show B receives a held response and `close()` returns. A plausible bad fix would start B during drain or discard its durable request.

### 2. A deferred file-receipt failure permits the request to be dispatched again

**Evidence:** For a deferred result, the file consumer writes a pending marker and attaches `complete` ([execution_host.py:1602](/private/tmp/otto-audit-tree/src/otto/portfolio/execution_host.py:1602)). If terminal receipt writing fails, `complete` records the exception but leaves the request and pending marker in place, then removes the active-file fence ([lines 1610–1625](/private/tmp/otto-audit-tree/src/otto/portfolio/execution_host.py:1610)). The next scan admits any request whose token is no longer active and whose response is absent ([lines 1533–1536](/private/tmp/otto-audit-tree/src/otto/portfolio/execution_host.py:1533), [1571](/private/tmp/otto-audit-tree/src/otto/portfolio/execution_host.py:1571)).

**Scenario:** A deferred command performs its effect and settles; writing `response-…json` raises `OSError` (for example, a full disk). The callback swallows the exception, no terminal answer appears, and the next pump invokes the handler for the same request again. Whether a domain key prevents a repeated external effect depends on that handler; the second invocation itself follows from the code.

**Proposed fix row — xhard:** Retain a failed-publication fence and retry publication from the settled value or exact durable readback, without redispatching the handler. Acceptance: inject a terminal-write failure after settlement, restore writes, and obtain one terminal receipt with exactly one handler invocation, including across owner restart. A plausible bad fix would retry the command rather than its receipt.

### 3. Worker `done` releases its authority outside the owner lane

**Evidence:** The facade serves concurrent connection threads ([server.py:63](/private/tmp/otto-audit-tree/src/herzchen/fleet/tools/server.py:63)). `_OwnerExecutorPort` marshals the landing call to the owner, but calls `settle_assignment` only **after** that call returns ([product_service.py:227](/private/tmp/otto-audit-tree/src/otto/hostctl/product_service.py:227)). Settlement changes the dispatch record and revokes its token ([line 879](/private/tmp/otto-audit-tree/src/otto/hostctl/product_service.py:879), [dispatch.py:225](/private/tmp/otto-audit-tree/src/herzchen/fleet/dispatch.py:225)). The owner pump can take another queued call immediately after signaling the first ([execution_host.py:1704](/private/tmp/otto-audit-tree/src/otto/portfolio/execution_host.py:1704)); a `worker-check` runs a check against the lab ([landing.py:59](/private/tmp/otto-audit-tree/src/herzchen/fleet/landing.py:59)).

**Scenario (inference from the permitted thread interleaving):** While `done` is landing, another connection validates the same live token and queues `check`. The owner finishes `done`, signals its facade thread, and processes `check` before that thread revokes the token. A check executes after the final landing. The registry and token book have their own locks, but the settlement is outside the serialized owner operation.

**Proposed fix row — normal:** Perform successful `done` settlement inside the owner operation before its waiter is signaled, and recheck current grant state when each queued tool call enters that operation. Acceptance: hold the facade thread immediately after the owner completes `done`, queue a check with the same token, and verify that no post-landing check runs.

## Checked and sound

- `_owner_request` queues work for the bounded owner pump and propagates operation exceptions to its waiter ([execution_host.py:335](/private/tmp/otto-audit-tree/src/otto/portfolio/execution_host.py:335), [1704](/private/tmp/otto-audit-tree/src/otto/portfolio/execution_host.py:1704)).
- `adapter_transport` captures provider values or exceptions on the owner lane and decrements its external-wait count in `finally` ([execution_host.py:973](/private/tmp/otto-audit-tree/src/otto/portfolio/execution_host.py:973)).
- `owner_callback` marshals admitted native callbacks to the owner and explicitly rejects late callbacks ([execution_host.py:1683](/private/tmp/otto-audit-tree/src/otto/portfolio/execution_host.py:1683)).
- The additional `after_owner` consumers inspected defer their result transformations; the `serve.py` premature `.get` is already covered by **OWNERCOMPLETION** ([serve.py:654](/private/tmp/otto-audit-tree/src/otto/hostctl/serve.py:654)).

## Not checked

- No tests or live owner were run, as required. The drain and receipt outcomes are source-derived; the post-landing check requires the stated thread interleaving.
- `OrchestratorLanePump` has deferred publication code but no production constructor found in this checkout, so its runtime integration was not assessed.