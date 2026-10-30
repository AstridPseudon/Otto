# Your task: critic pass (over-engineering and evidence check)
**Do only this task. Ignore the `briefs/` folder and any other task descriptions in the workspace; they belong to other analysts.**
Inputs: the three drafts `out/w3-retro.md`, `out/w3-principles.md`, `out/w3-structure.md`, plus the lens reports `out/w2-*.md` for evidence. Check raw data where needed.

The owner repeatedly pushed back on over-engineering and process growth. Review the drafts like that owner would:
1. **Over-engineering:** which roles, entities, fields, loops, gates or rules could be cut or merged with no loss? Propose the smallest version that still prevents each observed failure. Be concrete ("drop field X", "merge Y into Z").
2. **Evidence check:** list claims or principles that are unsupported, overstated, contradicted by the data, or generalised from a single instance. Say what the evidence actually shows.
3. **Gaps:** important lessons in the lens reports that none of the drafts captured.
4. **Contradictions** between the three drafts.
Output a numbered list per section, each item with a recommended edit. Max ~2,500 words.
