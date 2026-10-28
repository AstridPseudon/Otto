# Opus complexity review (15 Oct): verdict and minimal plan (condensed)

**Verdict:** the plan points the right way but builds too much. On this setup the renders die because of one specific loop, and the live line shows that taking it away is enough. About 4 focused days of mostly deleting code covers the four failures (renders dying under load, hosts stuck, orphan pods billing, leaked processes), against the 12 days planned.

**Main reasons:**
- **The cause is one loop.** Main calls `observe_tree` every 50 ms during the render (generic_host.py:7857–7860), through a census with a 1.0 s cap that trips the host-wide latch. The live line has the same latch and a teardown census, but no in-run observation, and it works.
- **Non-reaping status is expensive here.** `os.waitid` does not exist in macOS CPython (verified on 3.9 and 3.11), so every reaping call site would need kqueue or ctypes plumbing.
- **The general ledger is premature.** It needs a v30 schema, store transitions, an API and adapters (about +1k lines), and deletes nothing in return. Per-backend rules give about 90% of the value. Revisit it with a second remote provider or multi-machine scheduling.
- **The plan as written is roughly net-flat.** Only about 1,300 of custody_broker's 3,933 lines are the ordinary-command path; the rest have other callers. The minimal plan is about −2.3k to −2.8k lines against about +350.

**Do not:**
- build the obligations table or its state machine;
- build a per-resource-class policy object;
- add a new Scope/Lease API layer;
- build the host control endpoint, singleton lock or drain/replace, or rework VibeComfy;
- do Linux or container acceptance, cgroups or Job Objects;
- add VRAM quantities or health checks;
- retrofit non-reaping status;
- prune pods by name prefix (the default prefix "pod" would hit unrelated pods);
- repeat the multi-film ritual on every step; one gate run per step is enough.
