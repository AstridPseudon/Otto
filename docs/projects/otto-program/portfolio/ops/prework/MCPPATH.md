## Design

1. [tests/test_tools.py:647](${TRANSFER_ROOT}/source/otto/tests/test_tools.py:647) → Add the regression below first. It runs the **actual grant from `OwnerFleetRegistry.grant_for_due`**, connects to a real facade, and makes `task` calls from labs with package and standard-library shadows. It patches no product method.
2. [src/otto/hostctl/product_service.py:813](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/product_service.py:813) → Prefix this server’s args with `"-I"`: `("-I", "-m", "herzchen.fleet.tools.stdio_server", ...)`. Keep the configured absolute interpreter, socket, token environment, and tool list. Use `-I` even on Python 3.11: the Claude environment inherits `PYTHONPATH` at [claude_cli.py:339](${TRANSFER_ROOT}/source/otto/src/otto/agents/claude_cli.py:339), which `-P` alone would still honor. The configured interpreter must have Otto in its own site-packages, as the [host onboarding instructions](${TRANSFER_ROOT}/source/otto/docs/host-onboarding.md:17) already prescribe.

## Failing test to write first

Add `test_worker_mcp_runs_installed_server_despite_lab_shadows` to [tests/test_tools.py](${TRANSFER_ROOT}/source/otto/tests/test_tools.py:647):

```python
def test_worker_mcp_runs_installed_server_despite_lab_shadows(tmp_path, sock_dir):
    import threading
    from types import SimpleNamespace as NS
    from herzchen.contracts import ResourceRef
    from herzchen.domains.work.admission import authoring_stamp
    from otto.hostctl.product_service import OwnerFleetRegistry

    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True)
    python = venv / "bin" / "python"
    purelib = subprocess.check_output(
        [str(python), "-I", "-c",
         "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
        text=True,
    ).strip()
    (Path(purelib) / "herzchen").symlink_to(
        Path(SRC_DIR) / "herzchen", target_is_directory=True
    )

    repo = tmp_path / "repo"
    repo.mkdir()
    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    git("init", "-b", "main")
    (repo / "README").write_text("fixture\n")
    git("add", "README")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "-m", "seed")

    project_ref = ResourceRef("test", "work.project", "p", "p1")
    task_ref = ResourceRef("test", "work.task", "t", "r1")
    assignment_ref = ResourceRef("test", "wrk.assignment", "a", "a1")
    payload = {
        "kind": "task", "fields": {}, "dependencies": [],
        "project_ref": project_ref.to_dict(),
        "metadata_namespaces": {"otto.plan": {"repo": "repo", "branch": "main"}},
    }
    payload["metadata_namespaces"]["work.admission"] = authoring_stamp(
        "r1", payload, "reviewer"
    )
    task = NS(ref=task_ref, payload=payload)
    project = NS(ref=project_ref, payload={"tasks": [task_ref.to_dict()]})
    assignment = NS(ref=assignment_ref, generation=1, role="executor",
                    principal="worker", scope=task_ref)
    registry = object.__new__(OwnerFleetRegistry)
    registry.owner = NS(
        graph=NS(current=lambda ref: project if ref.kind == "work.project" else task),
        assignments=NS(get=lambda ref: assignment),
    )
    registry.config = {"python": str(python), "store": {"authority": "test"},
                       "repositories": {"repo": str(repo)}}
    registry.tokens = TokenBook()
    token = registry.tokens.issue("a", "worker")
    registry.records = {"a": NS(assignment="a", task=task, admitted_revision="r1",
                                state="launched", role="worker", token=token)}
    registry.dispatcher = NS()
    registry._due_keys, registry._due_bindings = {}, {}
    registry._lock = registry._pair_lock = threading.RLock()
    registry.facade_server = object()
    registry.facade_socket = str(sock_dir / "facade.sock")
    registry.views_provider = lambda: {}
    due = {"schedule_id": "run", "role": "worker", "recipient": "worker",
           "assignment_ref": assignment_ref.to_dict(), "generation": 1,
           "target": {"task_ref": task_ref.to_dict(),
                      "assignment_ref": assignment_ref.to_dict()}}

    owner = FakeOwner({"effective-context": {"task": "t"}})
    facade = ToolFacade(TOOL_SPECS, {"worker": ("task",)}, owner,
                        registry.tokens, FeedbackLedger())
    frame = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": "task", "arguments": {}}}
    with FacadeServer(facade, str(registry.facade_socket)):
        for shadow in ("package", "stdlib"):
            lab = tmp_path / shadow
            lab.mkdir()
            if shadow == "package":
                package = lab / "herzchen" / "fleet" / "tools"
                package.mkdir(parents=True)
                for directory in (package.parent.parent, package.parent, package):
                    (directory / "__init__.py").write_text("")
                (package / "stdio_server.py").write_text(
                    'raise SystemExit("LAB_SHADOW")\n'
                )
            else:
                (lab / "json.py").write_text('raise SystemExit("LAB_SHADOW")\n')
            registry._pairs = {("repo", "main"): (
                NS(names=lambda: ("t",), get=lambda name: NS(path=lab)), object()
            )}
            grant = registry.grant_for_due(due)
            server = grant.servers[0]
            env = {**os.environ, "PYTHONPATH": str(lab),
                   grant.token_env: grant.token}
            result = subprocess.run(
                [server.command, *server.args], cwd=lab, env=env,
                input=json.dumps(frame) + "\n", capture_output=True,
                text=True, timeout=10,  # Hang guard only.
            )
            assert result.returncode == 0, result.stderr
            reply = json.loads(result.stdout)
            payload = json.loads(reply["result"]["content"][0]["text"])
            assert payload["ok"] is True
            assert payload["kind"] == "task"
            assert payload["result"] == {"task": "t"}
    assert [call["assignment"] for call in owner.calls] == ["a", "a"]
```

## Deletion, mistake, and decisions

Delete the unisolated production argument sequence at [product_service.py:814](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/product_service.py:814); add no second launcher or import-path helper.

A plausible mistake is adding only `-P`. The test deliberately puts each shadow on `PYTHONPATH` as well as in the lab cwd, so that implementation still loads `LAB_SHADOW`. Before any fix, `-m` loads a lab shadow and the `task` response fails.

**Existing expectations requiring D19:** None. The direct `-m` launches in [test_tools.py:238](${TRANSFER_ROOT}/source/otto/tests/test_tools.py:238) are manually constructed, product-neutral transport tests; the product grant change does not alter their assertions. The hard-coded MCP config in [test_perch.py:604](${TRANSFER_ROOT}/source/otto/tests/test_perch.py:604) is likewise a fixture, not the product grant.

**Row corrections:** `-P` does not exclude inherited `PYTHONPATH`, so it cannot establish the stated “always” outcome by itself. [pyproject.toml:9](${TRANSFER_ROOT}/source/otto/pyproject.toml:9) still permits Python 3.9, making a 3.11-only `-P` solution incomplete. [claude_cli.py:372](${TRANSFER_ROOT}/source/otto/src/otto/agents/claude_cli.py:372) proves Claude starts in the lab; the MCP child’s inherited cwd is an inference, not an explicit Otto setting. This was a read-only design review; I ran no tests.