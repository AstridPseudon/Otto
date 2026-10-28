DEFECTS — LIVENESS only partially delivers its row; the findings below remain on `canon/main` at `eb9b6cdf`.

1. **High: installed-supervisor failures still exit 0; successful exits now become errors.**  
   `service run` selects the installed-supervisor branch at `src/otto/hostctl/cli.py:850`. That branch returns `supervisor-failed` for a nonzero child exit, or `closed` without `owner_exit_requested` for zero (`src/otto/hostctl/supervision.py:280`). The CLI therefore maps failure to 0 and success to an error (`src/otto/hostctl/cli.py:1123`). The former omission preserves precisely the supervisor failure described by LIVENESS.
   **Fix — normal:** normalize both service implementations’ exit contracts in these files; preserve failure and explicit-stop information. Test the real dispatch path with a fake subprocess boundary returning failure and a requested-stop success. The landed test replaces `LOCAL_COMMANDS["service","run"]` with a fabricated result (`tests/test_otto_show_status.py:121`), hiding this mismatch.

2. **High: native socket and launched file-lane clients still bypass the published-state check.**  
   `otto ask` calls the socket directly (`src/otto/portfolio/cli.py:1735`); launched native commands do likewise (`src/otto/hostctl/manager_client.py:81`). A closed owner yields generic connection guidance without its closure time, reason or restart command (`src/otto/portfolio/caller_client.py:106`). The file branch submits before checking liveness (`src/otto/hostctl/manager_client.py:87`); its wait only polls receipts until timeout (`src/otto/portfolio/manager_journey_client.py:201`). For example, a launched `start-manager` request against a closed owner remains queued and waits out the deadline.
   **Fix — normal:** extend the published-state check and closure response across these entry points, preserving retained-request uncertainty after submission. Test closed published status through both `ask` and the launched file branch: no submission or deadline wait, and actionable closure details.

3. **Medium: a socket timeout is falsely announced as owner death.**  
   Every `OSError` or `ValueError` during a wait becomes `owner_down` (`src/otto/portfolio/caller_client.py:71`). This includes a receive timeout while the owner remains alive, malformed JSON and oversized responses. The socket has an explicit timeout at line 95; none of these conditions proves closure.
   **Fix — normal:** distinguish disconnection from timeout and protocol failure in `caller_client.py`. Add deterministic socket-boundary tests for a timeout and malformed response, asserting neither reports confirmed owner death; retain the genuine disconnect regression.

4. **Medium: restart guidance breaks for service homes containing spaces.**  
   `with_lane_advice` interpolates the home without shell quoting (`src/otto/hostctl/service.py:89`, `:91`, `:105`). A home such as `/srv/Otto Home` produces a command whose arguments cannot parse correctly.
   **Fix — normal:** build one shell-safe command with `shlex.join`, deleting the duplicate owner/client construction. Test that shell-splitting the displayed command preserves the complete home argument.

5. **Medium: the active-wait regression does not test active-wait release.**  
   The fixture starts with `draining=True` and makes the cursor reader return immediately regardless of its timeout (`tests/test_ask_socket_wait.py:82`, `:94`). It patches the product’s `authorize_caller` method at line 95. Removing the new bounded wait at `src/otto/portfolio/manager_journey_service.py:1850` leaves this test passing, although a real pending wait can then remain blocked for its full requested duration.
   **Fix — normal:** use an authenticated fixture and a controlled reader boundary that transitions into draining during the wait. Verify bounded release without wall-clock sleeps; reverting the bounded-read behavior must fail the regression.

By inspection, all five added tests fail against the parent for at least one changed assertion, but the drain test misses the polling change and the exit test misses actual service results. No added timer waits or assertions recomputing the implementation’s calculation were found. No substantial over-engineering was established beyond the duplicate command construction above.

Three parallel Luna reviews supplied the legwork; I checked the cited claims against `canon/main`. No tests or Otto commands were run, and no files were changed.