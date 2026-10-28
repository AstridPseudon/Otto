## Design

Line numbers refer to `canon/main`.

1. [tests/test_otto_open_release.py:118](${TRANSFER_ROOT}/source/otto/tests/test_otto_open_release.py:118) → Add the regression test below to `OwnerRouteTests` first. Its real owner service runs with directory B as the process cwd; the actual `client_main` runs in a subprocess with directory A as its cwd.
2. [src/otto/portfolio/cli.py:1689](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/cli.py:1689) → Replace `_absolute_directories(words)` with one client-path normalizer that retains its `--directory` handling. For `save`, rebuild the forwarded argv from the already parsed `file`, `actor`, `request_id`, and `format`, applying `str(Path(parsed.file).absolute())` to the filename. Rebuilding from parsed values handles options before the positional filename.
3. [src/otto/portfolio/cli.py:1759](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/cli.py:1759) → Forward that normalized argv. This follows the existing `ottoctl` save behavior at [src/otto/hostctl/portfolio.py:115](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/portfolio.py:115); the owner reads the forwarded path at [src/otto/portfolio/cli.py:1217](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/cli.py:1217).

## Failing test to write first

Add this method inside `OwnerRouteTests` in `tests/test_otto_open_release.py`:

```python
def test_relative_save_reads_caller_file_and_returns_its_stale_diff(self):
    import os
    import subprocess
    import sys

    root = Path(self.bundle).parent
    caller, owner_dir = root / "caller-A", root / "owner-B"
    caller.mkdir()
    owner_dir.mkdir()

    def document(label, title, project_ref=None):
        value = {
            "project": {"title": title, "outcome": label + " outcome"},
            "tasks": [{
                "id": label,
                "title": title + " task",
                "instructions": label + " instructions",
                "acceptance": label + " done",
            }],
        }
        if project_ref is not None:
            value["project_ref"] = project_ref
        return value

    caller_file = caller / "project.json"
    caller_file.write_text(json.dumps(document("A", "A initial")), encoding="utf-8")
    (owner_dir / "project.json").write_text(
        json.dumps(document("B", "B initial")), encoding="utf-8")

    source = Path(__file__).resolve().parents[1] / "src"
    entry = (
        f"import sys; sys.path.insert(0, {str(source)!r}); "
        "from otto.portfolio.cli import client_main; "
        "raise SystemExit(client_main())"
    )

    def save(request_id):
        process = subprocess.run(
            [sys.executable, "-c", entry, "--home", self.home,
             "--portfolio", PORTFOLIO, "save", "--request-id", request_id,
             "project.json", "--actor", OWNER],
            cwd=caller, capture_output=True, text=True,
        )
        return process.returncode, json.loads(process.stdout)

    previous_cwd = Path.cwd()
    try:
        os.chdir(owner_dir)
        code, first = save("caller-first")
        self.assertEqual((code, first["outcome"]), (0, "saved"), first)
        self.assertEqual(set(first["task_refs"]), {"A"})

        code, shown = self.otto(
            "show", "project", "--project-ref",
            json.dumps(first["project_ref"]), "--actor", OWNER)
        self.assertEqual(code, 0, shown)
        self.assertEqual(
            [task["authored"]["instructions"] for task in shown["tasks"]],
            ["A instructions"],
        )

        caller_file.write_text(
            json.dumps(document("A", "A current", first["project_ref"])),
            encoding="utf-8",
        )
        code, current = save("caller-current")
        self.assertEqual((code, current["outcome"]), (0, "saved"), current)

        caller_file.write_text(
            json.dumps(document("A", "A stale", first["project_ref"])),
            encoding="utf-8",
        )
        code, conflict = save("caller-stale")
        self.assertEqual((code, conflict["outcome"]), (4, "conflict"), conflict)
        self.assertEqual(
            conflict["diff"]["project"]["title"],
            {"file": "A stale", "current": "A current"},
        )
        self.assertEqual(
            conflict["diff"]["tasks"]["changed"][0]["fields"]["title"],
            {"file": "A stale task", "current": "A current task"},
        )
    finally:
        os.chdir(previous_cwd)
```

## Delete

Delete the old `_absolute_directories` helper and its call when replacing them with the single client-path normalizer. There is no duplicate save-path normalizer to remove from `ottoctl`.

## Plausible mistake

Changing `words[1]` assumes the filename immediately follows `save`. The test places `--request-id` before `project.json`; that implementation would rewrite the option instead of the file. Leaving the filename relative makes the owner read B’s valid file, so the first task assertion fails.

## Existing expectations and D19

No existing test assertion needs to change; this adds a test. No D19 decision is needed.

## Stale parts of the row

A successful save returns refs, not a diff; the diff is returned for a stale-base conflict ([herzchen_binding.py:2383–2411](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/herzchen_binding.py:2383)). Also, save-file `documents` are accepted but dropped by `sheet_from_seed` ([sheet.py:815–845](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/work/sheet.py:815)). Exact document persistence therefore needs separate work before it can be an acceptance assertion for SAVEPATH. I found no `INSTALLCUTOVER` reference on `canon/main`.