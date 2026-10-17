# PL5 installed-owner cold-agent comparison

**Status: needs the gate.** No installed-owner baseline or PL5 result was measured in this restricted clone. The manager was instructed not to start an Otto owner or staging run, and no installed entry point/owner session is available here. No timing, tool count, transcript, or outcome is claimed.

## Paired measurement protocol

Run the same prompt and fixture once against the parent install and once against the PL5 install, using a cold agent given only that install's role introduction and entry point. Present a retained run/occurrence whose cleanup state is `unknown`, then ask the agent to identify the affected scope and choose a safe next action.

Record for each arm:

- elapsed time from prompt to safe action;
- exact verbs/tool calls and retained run/occurrence handles read;
- whether the agent identified the correct scope and read its exact status;
- whether it followed `next_action` by waiting or reconciling;
- whether it avoided a new request key, duplicate dispatch, or provider retry;
- transcript and gate receipt reference.

The PL5 outcome passes only if the agent identifies the same unresolved scope, uses the indicated recovery path, and does not retry the provider work. Keep the fixture, prompt, and allowed tool surface identical between baseline and result.
