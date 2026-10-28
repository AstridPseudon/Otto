# North Star: the Otto program

One Otto for every host, where many agents work at once for little cost, and every plan has exactly one copy.

**Enduring properties:**
- **Plans are typed records in Otto.** Files are checkouts or generated views, never a second source.
- **Each running task has its own lab.** Passing work lands on the project's line, one at a time, after its check passes on exactly that commit.
- **One capacity pool, one runner.** An idle agent costs nothing, and nothing polls.
- **A worker can check its work during its turn, but can never produce its own acceptance.**
- **A manager per project,** woken only for judgment.
- **Herzchen holds the product-neutral model and the agent fleet; Otto is the product.** Imports point down only.

**Anti-patterns:**
- mirrors and second copies;
- polling;
- hard-coded caps;
- free-text acceptance;
- a client able to stop the shared service;
- process paperwork that costs more than it protects.
