# Review C: the gaps between where we are and where we want to be

**Question.** Between the current state (the code base, the plan's tasks and the spec) and the end state in `15-in-short.md`, what's missing, ambiguous or wrong? Ask:
- Will executing the plan actually produce the end state the owner wants?
- Where are the gaps in the design (e.g. attach, model roles, the advisor, packs, the spec folder → tasks, worktrees and landing, recovery)?
- Where do the plan's reuse assumptions not match the code (e.g. does Otto's landing code or the validators lift out cleanly; what does the pack work actually contain)?
- What has the owner asked for that the plan doesn't deliver, or delivers only implicitly? Check `12-minimal-design.md` and the owner statements quoted in `13`/`14`.

**Output**
1. **A gap table:** gap, why it matters, evidence (a file or line), the smallest fix, and which task owns it (or a new task).
2. **The top 5 gaps** that would stop us reaching the end state.
3. **Ambiguities the owner must decide,** with a recommended answer for each.
4. **Reuse assumptions that are wrong,** with the corrected estimate.
5. **Verdict:** does the plan as written reach the end state? If not, list the minimum changes.
