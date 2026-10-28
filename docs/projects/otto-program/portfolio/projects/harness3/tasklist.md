# Tasklist: HARNESS-3: a real third agent through HOSTKIT

Routes are normal or xhard (Megado). Deps are task ids in this project. Sizes are focused days (2 in all, 0 XHARD).

| id | route | est (d) | deps | outcome | acceptance evidence | xhard justification | stream | status |
|---|---|---|---|---|---|---|---|---|
| H31 | normal | 0.25 | — | **Choose the harness** (the user picks, e.g. another CLI agent); its tool and session model recorded. | decision recorded | — | harness3 | not started |
| H32 | normal | 1.0 | H31 | **Implement it through HOSTKIT:** launch, resume, tools (MCP), fence, parse and models, as host data in the packs. | SKEL passes with the new host | — | harness3 | not started |
| H33 | normal | 0.5 | H32 | **Clean up:** no `claude`, `codex` or new-host names outside fleet/hosts and the packs. | grep is clean; suites green | — | harness3 | not started |
| H34 | normal | 0.25 | H32 | **Measure** cost and seconds per accepted task against Claude and Codex on the same three tasks. | the comparison recorded | — | harness3 | not started |
