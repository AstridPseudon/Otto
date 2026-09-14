# OTT-04 whole-task catalogue assessment — 2026-09-14

Status: **manager evidence complete for root acceptance; no gate decision is
made here**. The original implementation, durable-host continuation, replay/CAS
correction, and amendment interrupted-stage correction are retained as separate
increments. This assessment joins their applicability without rewriting the
historical incomplete receipt or claiming OTT-06/real-agent qualification.

## Catalogue identity and custody

The governing task is `OTT-04`, “Implement durable attention and continuity,”
from the immutable v11.2 catalog. It requires OTT-03, delivers
`src/otto/attention.py` and `tests/otto/test_continuity.py`, and owns C19, C21,
C32, C33, and C34. Its acceptance requires restart-safe attention, exact
replay and recovery, manager-controlled amendment behavior, honest unavailable
host handling, and a finite shared boundary. The catalog explicitly defers a
real-agent rehearsal to OTT-06.

Accepted source pins used by the current proof are:

| input | pin |
| --- | --- |
| Otto current source | `6f9099ba54e5b866c1f4c0ea5f6b17405748b6aa`, tree `c6120ad219a2eae4a3f39fa441c679f6be4fab41` |
| Otto source correction | `5332885d6dfba8af89c3f10d3311714d744b9c42`, tree `66db6877fb490850bc05723d782fcee3eabbd722` |
| Accepted Herzchen source | `b68d8f59712275229c24757664ca30d807d39e4a`, tree `ee1614fc37fdd096fb9640702e124e28a391d170` |
| Accepted Herzchen wheel | SHA-256 `2681daaeb673cd636050c3805977a01a670ed6bcfc113fe9d85903af5eeae9bc` |
| Current Otto wheel | SHA-256 `f2fffb0d51a0e38a674dd04171d4df20a2bbca3a6bc21bbe84d043db1826aee4` |

The current correction evidence is under
`work/ott-04-amendment-replay-xhard-20260914/`. Its result, raw source and
installed observations, test receipt, launch manifest, and hashes are retained
there. The previous 53-source/53-installed campaign, durable continuation, EX-
HOST lineage, and expected-CAS proof remain historical inputs rather than being
silently replaced.

## Criterion mapping

| criterion | retained/current evidence | manager assessment |
| --- | --- | --- |
| C19 — responsibility and continuity | Historical `work/ott-04-result-20260914.md`; durable continuation raw observations; current amendment observation. Due records retain owner, invocation identity, return condition, in-flight state, and outstanding decisions across close/reopen. Exact retry returns the original logical result; unknown/crashed delivery remains reconcile/resume with no relaunch. | **Supported by current product and retained proof.** A qualified external agent launcher or real-host smoke is outside OTT-04 and remains OTT-06. |
| C21 — efficient persistent attention | Historical source/installed 53/53 campaign; the accepted continuation tests and raw observations cover one-off plus 3-hour and 90-minute intervals, missed-slot coalescing, durable anchors, one in-flight request, one attention view, and no automatic action. Current amendment result preserves `dispatch: false` and `automatic_action: false`. | **Supported.** No second scheduler, cron engine, polling loop, or automatic task prioritisation was added. |
| C32 — actionable waiting and recoverable attention | `work/ott-04-result-continuation-20260914.md`, EX-HOST supplement, cursor tests, due-record raw observations, and current interrupted-stage raw observation. Cursor reads are not acknowledgment; duplicate/gap/unknown states remain recoverable; owner, missing handoff, return condition, decision, and original anchors survive restart. | **Supported.** The later host qualification boundary is explicit and not inferred from fixture-only launcher mechanics. |
| C33 — trustworthy public mutation effects | Expected-CAS raw source/installed observations plus current raw source/installed amendment observations. First amendment commits decision/plan/route/attention with four events and no dispatch. Exact retry replays all stages with zero new events. Same-key changed input raises `InputChangedError` with zero event/state delta. Interrupted plan recovery replays persisted decision/plan and commits route/attention once after fresh client/store reopen. | **Supported by current installed evidence.** The final current wheel runs the two real-product checks with both Python path overrides unset and all imports from the disposable venv’s site-packages. |
| C34 — shared implementation and product boundaries | EX-HOST lineage supplement, finite `DueRecordPort` and serialized amendment port audits, current installed origins, and accepted Herzchen command-port lineage. Consumer objects expose only finite JSON endpoints; Store, DomainHandler, SQLite path, generic writer, callback, and private inbox/journal remain owner-side. | **Supported.** The expanded due record is justified by the accepted `IntervalController` schema gap; no second timer authority was introduced. |

## Original-step coverage

The implementation uses accepted shared attention, packet, receipt, event,
cursor, work-sheet, assignment, and owner-side Store operations. The durable
record carries recipient, instruction, profile, anchor, interval/due state,
last-covered slot, invocation identity, stop state, owner, missing handoff,
return condition, outstanding decisions, in-flight request, and last result.
One-off and two interval values use the same state machine; missed intervals
coalesce, stale writes and changed input are typed zero-delta failures, and
reopening resumes the same request.

Manager-selected amendments use the normal public plan, assignment-route, and
attention operations. A review notification remains distinct from an enacted
manager decision. The current replay correction records a complete decision
manifest before partial stages, classifies public receipts as committed or
replayed, accepts unchanged views on exact retry, and recovers a committed
plan after owner interruption without duplicate route or attention events.
Owner, usage, budget, and running input pins remain preserved. No dispatch or
automatic manager/task/budget creation is inferred from readiness, attention,
or replay.

## Evidence and exact validation

Current raw evidence:

| artifact | SHA-256 |
| --- | --- |
| `work/ott-04-amendment-replay-xhard-20260914/result.json` | `581c66e10992b146dc3e778ead017ffe4dcae56d41bf916bdc68ab50d5e80617` |
| `work/ott-04-amendment-replay-xhard-20260914/result.md` | `7bc41049a2e0fb2ff7e04b461d6685876079737ebbca85d0a24d707d4b2e6640` |
| `work/ott-04-amendment-replay-xhard-20260914/observation-source.json` | `870a27a28b361b077d72ecb9db6a620e32c33ef0e994e67197f708d1d5bdf751` |
| `work/ott-04-amendment-replay-xhard-20260914/observation-installed.json` | `1143aac32f10d5045847501bc1ecc59e315102347236deab4f9d800dad3d9690` |
| `work/ott-04-amendment-replay-xhard-20260914/test-receipt.json` | `732b4e0daa8c8be2b93f70d57726752362fbac489456fe060cedba7e28961a63` |

The current source selection passed 3 focused tests. The installed selection
passed 2 real-product tests with `PYTHONPATH` and `PYTHONHOME` unset; origins
for Otto, Otto attention, Herzchen, and Herzchen command ports are all under
the proof venv’s `site-packages`. The historical 53/53 campaign remains
untouched and was not rerun for this correction.

The XHARD launch command explicitly requested `gpt-5.6-sol` with
`model_reasoning_effort=high`. The CLI emitted a prior-Luna/current-Sol
warning, while the host-fixed resumed thread reported that it could not switch
its active model. The request, warning, and worker statement are retained in
the launch manifest/result; this assessment does not claim independently
attested Sol execution or silently relabel the worker as Sol.

## EX-HOST and later-task boundary

The accepted Herzchen `IntervalController` remains the reuse lineage for
anchor, logical slot, coalescing, one in-flight request, and restart behavior.
OTT-04 stores its larger required due record through one owner-side public
Store contribution because the accepted Herzchen schema cannot carry all Otto
fields. Two timer records would create competing authorities, so no second
controller was introduced.

No real external agent launch, crash reconciliation against a configured host,
or OTT-06 fresh-agent/two-project rehearsal is claimed here. Those remain
explicit later qualification work, together with the later Astrid/G-OTTO
transfer boundaries. The current evidence is sufficient for the OTT-04
catalogue scope and is submitted to root for the canonical acceptance decision.
