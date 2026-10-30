# Review J: a programmatic end-to-end journey test, as minimal as possible

**The owner asks:** how do we programmatically test the **end-to-end journey**, in as minimal a way as possible?

The journey is the owner's real path through the tool:
1. install → `otto init` (advisor and orchestrator) → `otto project new` from a spec folder;
2. the orchestrator starts a manager;
3. the manager checks the spec out, plans tasks and dispatches workers, one of them a **specialist role** (e.g. sense-checker);
4. a worker uses an omp sub-agent, submits, and the manager accepts;
5. landing (done only once landed);
6. a spec change mid-work;
7. an advisor consultation, both requested and scheduled;
8. a restart during delivery;
9. `otto status` shows the truth throughout.

Read spec B6 and B7 and `16-three-reviews.md` §2 (the testing design already agreed), plus what oh-my-pi offers. Check its loopback fake provider (`packages/coding-agent/test/rpc-wire/fake-openai-server.ts`), mock models, and the `omp-rpc` client tests.

**Answer:**
1. **The shape:**
   - Is the journey **one** scripted test (a scenario), or a few?
   - What runs for real: the installed wheel, the real `otto run`, the real omp binary, SQLite, Git?
   - What's scripted: the model replies?
   - How do scripted "agents" actually act? For example, the scripted provider returns tool calls that run `otto …` CLI commands and edit files, so the agents drive the tool exactly as real ones would.
2. **The script format:** the smallest way to write the agents' scripted behaviour per role and step, so it stays readable and doesn't become a framework. Give a concrete example for 2–3 steps.
3. **Assertions:** what to check at each step, and how. Prefer observable outcomes (status output, Git state, database rows read through the CLI) over internals.
4. **Time and determinism:**
   - the clock for schedules;
   - waiting on `session_settled` without sleeps;
   - the expected run time;
   - how to keep it from becoming flaky.
5. **Crash and restart inside the journey:** where to kill, and what to assert after.
6. **The live variant:** the same journey with real models. What changes (assertions on outcomes, not wording)? How often does it run? Can it be the pilot's backbone?
7. **The minimal file layout and size** (lines of code), and what we must **not** build.
8. **Fit with the plan:** which task owns it (D3? a new task?), the days, and its dependencies.

**Output:** a concrete design that a worker could start on tomorrow, with the example script, the assertion list, the layout and the plan change.
