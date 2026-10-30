# Review B: the minimal, elegant testing approach

**Question.** What's the smallest testing approach that makes us genuinely confident the end state works? It has to cover:
- the three hard invariants: an atomic check-in, one session per seat, and messages that survive a crash;
- the 11 acceptance behaviours in spec §B6;
- the pilot.

Look at how Otto tests today: `otto/otto/tests`, the test layout, fixtures, fakes, sizes and run time, and the labs that are about proof or testing (LANDPROOF, PROOFDOC, TESTPATCH, DISTURB, REALSTAGE3). Look at what oh-my-pi provides for testing (fake or local models, RPC tests, the omp-rpc client tests) and what Astrid does.

**Output**
1. **The approach in about 10 lines:** layers, what runs where, and what's real vs faked.
2. **The fake harness:**
   - should there be a fake omp process speaking the RPC protocol, or an omp local or fake model?
   - how do we inject crashes around admission and commit?
   - how do we test against a real omp without using up subscriptions?
3. **The test list:** each §B6 behaviour and each hard invariant mapped to one or a few named tests. Give their layer and rough size.
4. **The live tests:** what the S0 trial and the vertical slice prove with real logins, how often they run, and their cost.
5. **What to reuse from Otto's tests** (as specs or as code), and what to throw away.
6. **What NOT to test,** where tests would be over-engineering.
7. **The CI shape on one machine:** the commands, run time and gates.
8. **A change to the plan's tasks or estimates** if testing needs one.
