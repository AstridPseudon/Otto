# OTT-04 catalog assessment — 2026-09-14

This manager assessment maps the accepted OTT-04 scope to the current
source and installed receipts. It separates the owned attention/continuity
product proof from the later real-agent host qualification.

| Criterion | Current evidence | Assessment |
| --- | --- | --- |
| C19 | `real-observation-installed.json` and `test_continuity.py` show one owner, one in-flight request, exact retry, unknown/reconcile without relaunch, restart of the same request, and no duplicate delivery. | Otto continuity is proven. An actual external agent launcher/host rehearsal was not run here and remains an OTT-06/later host qualification boundary. |
| C21 | The same `DurableAttention` path proves one-off, three-hour and ninety-minute intervals, missed-slot coalescing, durable anchors, and a single attention view. The amendment observation reports `dispatch: false` and `automatic_action: false`. | Pass for persistent attention and manager-controlled follow-through. |
| C32 | Durable records persist owner, missing-handoff/return condition, outstanding decision, in-flight request, cursor-related continuity, and exact event/receipt identities across reopen. | Pass for recoverable waiting and stable attention; no readiness is treated as business action. |
| C33 | `StoreDueRecordPort` uses `Store.register_domain_handler` and public mutation/read/receipt operations. Fresh observations show event/receipt linkage, exact replay with delta zero, changed-input rejection with delta zero, stale-CAS rejection with delta zero, and amendment before/action/fresh-after receipts. | Pass for the owned public mutations; source affected file has 8 passing tests and the installed real-product selection has 2 passing tests with site-packages origins. |
| C34 | Consumer sees only finite `DueRecordPort`/serialized amendment methods. Store, SQLite paths, domain handlers, generic writers, and callback engines remain trusted host state. The EX-HOST supplement records reuse of accepted `IntervalController` semantics and the reason for one expanded record. | Pass for the owned shared boundary and extraction lineage. |

The preserved historical campaign is 53 source / 53 installed from
`work/ott-04-result-20260914.md`. The fresh continuation implementation is
`e69d90f995ff58ed3306e48c1fba28562d608972`; fresh evidence is commit
`ac85ba906cbc5b7a56638bd735a924c6aae2b5a3`. The fresh installed wheel is
`8e3ad556abb80f6125f79813ceff40203e37e9562223359842c91243f0238642` and
the accepted Herzchen wheel is
`2681daaeb673cd636050c3805977a01a670ed6bcfc113fe9d85903af5eeae9bc`.

This assessment does not convert the preserved no-host-launch boundary into
a live-agent claim. The later OTT-06 rehearsal and AST integration remain
separate tasks.
