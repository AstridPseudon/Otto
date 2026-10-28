Design for `canon/main` (`b635c936`). The change belongs at the Claude adapter’s owner-binding step. The gateway and owner queue already provide the transport boundary and synchronous callback result.

1. **Write the regression test first** at [tests/test_claude_manager_admission.py:145](${TRANSFER_ROOT}/source/otto/tests/test_claude_manager_admission.py:145), alongside the existing synthetic manager test. It uses the real `NativeProcessCallerIngress.observe` and `ClaudeCliTransport.run`, with the existing Python process standing in for the model.

2. **Capture the observer while binding on the owner lane** at [claude_adapter.py:349](${TRANSFER_ROOT}/source/otto/src/otto/agents/claude_adapter.py:349). On the copied, manager-role adapter with a caller socket, set `bound.native_process_observer = ExecutionHost.owner_callback(self.native_process_observer)`. Leave worker copies without caller registration. `OwnerRuntime._invoke` calls this binding step on the owner before the gateway enters `adapter_transport`.

3. **Use that captured observer** at [claude_adapter.py:447](${TRANSFER_ROOT}/source/otto/src/otto/agents/claude_adapter.py:447). Pass `self.native_process_observer` into `_compose_on_process` without wrapping it again. That composer already calls registration before the PINALL process hook; [claude_cli.py:377](${TRANSFER_ROOT}/source/otto/src/otto/agents/claude_cli.py:377) waits for its cleanup result before writing stdin. Keep exact-process cleanup with the observer. This does not require a process-scope redesign.

**First failing test — `test_native_binding_is_built_on_owner_before_input_with_concurrent_worker_preparation`:**

```python
def test_native_binding_is_built_on_owner_before_input_with_concurrent_worker_preparation(self):
    import threading
    from otto.agents.claude_adapter import _compose_on_process
    from otto.portfolio.execution_host import ExecutionHost
    from otto.portfolio.identity_context import HostCallerBinding
    from otto.portfolio.native_caller_ingress import NativeProcessCallerIngress

    host = ExecutionHost(directory=Path(self.state) / "obsowner",
                         handler=lambda request: {}, bounded_transports=True)
    host.start()
    self.addCleanup(host.close)
    owner_thread = host._owner_request(threading.get_ident)
    authorization = {"status": "authorized",
                     "physical_session_id": "manager-native-session"}
    constructed, registered, received = [], [], []

    def binding_factory(auth):
        self.assertEqual(threading.get_ident(), owner_thread)
        self.assertEqual(auth, authorization)
        binding = HostCallerBinding(
            self.f.actor, self.assignment.ref, 1,
            self.adapter.adapter_identity, auth["physical_session_id"],
            "obsowner-schedule")
        constructed.append(binding)
        return binding

    ingress = NativeProcessCallerIngress(binding_factory)
    adapter = ClaudeWorkerAdapter(
        owner="manager", source=self.root, worktree=self.root,
        launcher_pin=self.manager_t.pin, state_root=self.state,
        requested_model="claude-haiku-5-5", requested_reasoning="medium",
        transport=self.worker_t, roles=("worker", "manager"),
        manager_transport=self.manager_t,
        native_caller_socket=self.root + "/caller.sock",
        native_process_observer=ingress.observe)

    def bind_on_owner():
        bound = adapter.bind_owner_authorization(
            lambda *args: {}, verifier=lambda *args: {},
            role="manager", profile="workspace-write")
        prepare_worker = ExecutionHost.owner_callback(
            lambda: adapter.bind_owner_authorization(
                lambda *args: {}, verifier=lambda *args: {},
                role="worker", profile="workspace-write"))
        return bound, prepare_worker

    bound, prepare_worker = host._owner_request(bind_on_owner)
    gate = threading.Barrier(2)
    prepared = {}

    def concurrent_prepare():
        gate.wait()
        try:
            prepared["adapter"] = prepare_worker()
        except BaseException as exc:
            prepared["error"] = exc

    worker = threading.Thread(target=concurrent_prepare)
    worker.start()

    def model():
        gate.wait()
        observer = ExecutionHost.owner_callback(bound.native_process_observer)
        composed = _compose_on_process(observer, authorization, None)

        def on_process(process):
            cleanup = composed(process)
            with ingress._lock:
                self.assertEqual(len(constructed), 1)
                self.assertEqual(set(ingress._live), {process.pid})
                self.assertIs(ingress._live[process.pid][2], constructed[0])
            registered.append(process.pid)
            return cleanup

        def on_input(turn):
            self.assertEqual(len(registered), 1)
            received.append(turn)

        return self.manager_t.run(
            "Read status", session="manager-native-session",
            on_process=on_process, on_input=on_input)

    completion = host._owner_request(
        lambda: ExecutionHost.adapter_transport(model))
    done = threading.Event()
    completion.then(lambda value: done.set(), lambda error: done.set())
    done.wait()
    worker.join()
    if completion.error:
        raise completion.error
    if "error" in prepared:
        raise prepared["error"]
    self.assertEqual(completion.value["outcome"], "succeeded")
    self.assertEqual(len(constructed), 1)
    self.assertEqual(len(received), 1)
    self.assertEqual(prepared["adapter"]._role, "worker")
    self.assertEqual(ingress._live, {})
```

**Delete:** the late `ExecutionHost.owner_callback(...)` call at `claude_adapter.py:451`. Do not add another registry or lock.

**Plausible mistake:** queue registration and let transport proceed. The test checks the exact live binding *when the process hook returns*, before `ClaudeCliTransport` can write stdin, then checks that the stand-in emitted its input event. On current code it fails earlier and deterministically: `binding_factory` runs on the transport thread, so its owner-thread assertion fails without a dictionary-race timing check.

**D19:** no existing assertion needs to change. The manager observer and cleanup expectations in `test_claude_manager_admission.py:158–159`, the worker-without-observer expectation in `test_capacity_pool.py:513`, and concurrent manager-turn expectations remain valid.

**Stale row detail:** [native_caller_ingress.py:185](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/native_caller_ingress.py:185) adds worker schedule candidates; actual binding construction is at lines 97–116. The Codex adapter already captures its observer during owner binding at `herzchen_adapter.py:179–188`; the missing capture is on the Claude path. `PINALL`, `PROCLIFE`, and `OBSOWNER` are task labels, not names present in `canon/main`. No files were changed and no tests were run.