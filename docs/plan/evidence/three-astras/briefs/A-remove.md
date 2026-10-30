# Review A: what to remove or simplify

**Question.** What in the current code base doesn't fit where we're going, and should be removed, simplified or left behind? Go through Otto's integrated code (`otto/otto/src/otto`: list modules with their size), its tests, `controller/`, `install/`, `ops/`, the lab and project branches, the Megado pack work, and our plan repo. Also check the plan itself (13/14/15) for anything that's still heavier than it needs to be.

**Output**
1. **A table, one row per module, folder or branch:** keep as is, lift and simplify (into what), keep only as a behaviour spec or reference, or leave behind. Include a one-line reason and the rough line count.
2. **The top 10 removals or simplifications by impact,** each with what replaces it (often oh-my-pi, or nothing).
3. **Things the plan still carries that it could drop,** and anything we'd lose that matters.
4. **Removals we should NOT make,** and why.
5. **A clean-up sequence** that's safe for the frozen Otto repo (tags and archives, never deleting history).
