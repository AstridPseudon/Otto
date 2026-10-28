The landing gate refused your lab with a new reproduced failure:
- `tests/test_fleet_custody.py::test_landed_done_revokes_before_facade_waiter_resumes`

The gate reproduced it 3/3 alone and BASE passed 0/3. Fix this regression in your lab after the requested fresh rebase. Preserve the task outcome and all assertions; run the exact focused test plus directly affected checks. Do not broaden the check to unrelated tests. Report its cause and green results. Leave work for the launcher.

No other worker owns files at this moment. Do not touch `production/`, Stores, `~/.otto`, `~/.codex`, Codex project configuration, or anything outside this lab. Follow the original brief's Codex rules word for word: never stash or switch commits, don't run `ottoctl`, and every sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.
