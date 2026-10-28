All locations below are on `canon/main`. This is a read-only implementation design; I did not run tests or Otto commands.

## 1. Design, in implementation order

1. `src/herzchen/fleet/landing.py:102–113,143–145,225–230` → After `_checkpoint`, record `lab.head()` **before** rebase. Return it as `checkpoint_commit` alongside the existing rebased `commit` in the successful `done` result. Keep runner checks and landing tied to the rebased commit. The existing `LandingOwnerPort` and `ToolFacade` already carry the owner’s `done` result into the native tool result (`src/herzchen/fleet/tools/facade.py:89–93,194–217`).

2. `src/otto/agents/claude_adapter.py:442–464` → Record the lab’s starting HEAD and clean status before the useful worker turn. For a landed turn, require one successful, parseable `mcp__otto__done` result; verify its checkpoint commit descends directly from that starting HEAD and its landed commit equals the lab’s current HEAD. A dirty starting lab or missing binding cannot establish this turn’s file provenance.

3. `src/otto/agents/claude_adapter.py:50–108` → Replace the reverse, Write-only selection with an ordered inventory of successful `Write` and `Edit` calls. Normalize every `file_path` through the existing workspace and protected-path rules. For landed work, compare the **starting and checkpoint commits**, with rename detection disabled: every changed path must be named by a successful file tool call. Reject deletions, symlinks, nonregular Git entries, escaped paths, and the existing 16-file/64-KiB limit violations. Read each final blob from `checkpoint_commit`, never from the rebased or landed tree. Preserve ordered tool IDs in its artifact evidence; a last `Write` must equal its UTF-8 `content`. Replay the bounded Write/Edit inputs against the starting blob and require the checkpoint bytes to match, so an unreported change to even the *same* path cannot be delivered. Fail closed for an unsupported Edit input shape. Keep the current bounded live-file path only for turns that did not land.

4. `src/otto/agents/claude_adapter.py:120–123,155–169,215–231` → Admit an Edit-only artifact, bind the checkpoint SHA, tool IDs, final bytes, and digest into the existing result/context digest, and have the verifier check them. Update the Write-only source label. Do not change `unknown` or `retry_allowed: False` on capture failure (`:488–494`).

5. `tests/test_external_owner_execution.py:136–394` → Add real-owner, fake-Claude-stream cases for Edit-only; Write then Edit on one file; and a Write to a file whose **different lines** are auto-merged by landing rebase. Each must assert the retained artifact is the pre-rebase checkpoint bytes, the owner Due succeeds, and the landed lab is swept. Add an extra changed file with no successful file-tool call and assert capture fails and the lab stays. Then run the orchestrator’s stage-3 journey. Use the existing model/process injection seam, not a patch to `transport.run`.

## 2. First failing test

Add this smallest red test to `OwnerTests` in `src/otto/agents/tests/test_claude_binding.py`. It exercises the real owner with a fake Claude process; the landed cases above follow it.

```python
def test_actual_owner_captures_successful_edit_only(self):
    Path(self.root, "answer.txt").write_text("before\n")
    script = r'''
import json, os, sys
frame = json.loads(sys.stdin.readline())
prompt = frame["message"]["content"][0]["text"]
session = frame.get("session_id") or "native-session"
init = prompt.startswith("Initialize this session only.")
cwd = os.getcwd()
def emit(value):
    print(json.dumps(value), flush=True)
emit({"type": "system", "subtype": "init", "session_id": session,
      "cwd": cwd, "model": "gpt-test", "permissionMode": "bypassPermissions",
      "tools": [] if init else ["Edit", "Glob", "Grep", "Read", "Write"],
      "mcp_servers": [], "plugins": [], "skills": [], "slash_commands": []})
emit({"type": "user", "uuid": "input-init" if init else "input-work",
      "session_id": session,
      "message": {"role": "user", "content": [{"type": "text", "text": prompt}]}})
if not init:
    path = os.path.join(cwd, "answer.txt")
    emit({"type": "assistant", "uuid": "assistant-1", "session_id": session,
          "message": {"role": "assistant", "model": "gpt-test",
                      "content": [{"type": "tool_use", "id": "edit-1",
                                   "name": "Edit",
                                   "input": {"file_path": path,
                                             "old_string": "before\n",
                                             "new_string": "after\n"}}]}})
    with open(path, "w") as stream:
        stream.write("after\n")
    emit({"type": "user", "uuid": "tool-result-1", "session_id": session,
          "message": {"role": "user",
                      "content": [{"type": "tool_result",
                                   "tool_use_id": "edit-1",
                                   "is_error": False, "content": "edited"}]}})
emit({"type": "result", "subtype": "success", "is_error": False,
      "session_id": session, "uuid": "result-init" if init else "result-work",
      "result": "READY" if init else "Edited artifact.",
      "usage": {"input_tokens": 11, "output_tokens": 4}})
'''
    self.t.process_factory = lambda command, **kwargs: subprocess.Popen(
        [sys.executable, "-c", script], **kwargs)
    result = self.app.assign_and_start(**self.request)
    self.assertEqual(result["outcome"], "succeeded", result)
    due = self.f.port.read_due(result["schedule_id"])
    view = result_view(due)
    self.assertTrue(view["required_capture"])
    artifact = read_captured_artifact(
        due, artifact_ref=view["artifacts"][0]["ref"])
    self.assertEqual(base64.b64decode(artifact["content_base64"]), b"after\n")
```

## 3. Delete

Delete the reverse Write-only artifact loop and its universal live-byte comparison at `src/otto/agents/claude_adapter.py:69–105`; retain the last-Write check inside the new ordered verification. Delete the landed path’s dependence on the live-file descriptor read. Update stale “Read/Write” and “Write artifacts” comments at `src/otto/agents/claude_adapter.py:3,120`, `src/otto/agents/claude_cli.py:3`, and `src/herzchen/fleet/landing.py:97–99`.

## 4. Plausible mistake

Capturing `git diff` as the artifact inventory or reading the landed tree would include a file with no successful tool call, or the other worker’s auto-merged bytes. The extra-file negative rejects the former; the auto-merge case compares the captured digest and bytes to the pre-rebase checkpoint and rejects the latter.

## 5. Existing test decisions (D19)

- `tests/test_external_owner_execution.py:330–394` expects deletion of the live file *after landing* to prevent capture. Immutable checkpoint capture makes that expectation obsolete. Record a D19 decision to replace this with the uncalled-extra-file negative.
- `tests/test_landing.py:391–417` treats post-landing live bytes as the capture source and supplies no checkpoint receipt. Record a D19 decision to change that assertion to checkpoint bytes.
- The positive owner cases at `tests/test_external_owner_execution.py:136–328` start with an unrelated dirty `one.txt` and simulate `done` by wrapping `transport.run`. Their setup must start from a clean commit and emit a real fake-model `done` tool result. Their success and cleanup assertions remain valid.

## 6. Row corrections

The cited failure path is current. Its stage-3 claim that **every** worker using Edit settles unknown is too broad: a successful Write to file A followed by Edit to file B can currently settle successfully while silently omitting B. Also, landing presently returns only the rebased commit; the pre-rebase checkpoint SHA is available briefly at `landing.py:105–113` but is not retained.