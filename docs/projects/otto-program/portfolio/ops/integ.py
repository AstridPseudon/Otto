#!/usr/bin/env python3
"""One integration run instead of one gate run per task (the orchestrator, 18 Oct 2026).

Merges every checked lab onto canon/main in order (one "Land <TASK>: <TASK>" merge commit each, so ready.py
and history read as before), runs the whole suite once, compares failures with canon, and bisects each new
failure over the merge sequence to the task that introduced it. Pushing stays a separate, explicit step.

    python3 ops/integ.py build TASK [TASK ...]      worktree labs/_integ on branch integ/run, merged in order
    python3 ops/integ.py suite [--jobs N] [FILE ...] all tests/test_*.py by default; ops/integ/runs/<file>.txt
    python3 ops/integ.py base FILE [...]             the same files on canon/main (labs/_integbase)
    python3 ops/integ.py bisect FILE ID [ID ...]     first merge in the sequence where any ID fails
    python3 ops/integ.py drop TASK [...]             rebuild without these tasks (same order otherwise)
"""
import concurrent.futures, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

OPS = Path(__file__).resolve().parent
OTTO = Path.home() / "Developer/otto-claude-host/otto"
LABS = OTTO.parent / "labs"
WT, BASE_WT, BISECT_WT = LABS / "_integ", LABS / "_integbase", LABS / "_integbisect"
OUT = OPS / "integ"
STATE = OUT / "state.json"
PY = "/opt/homebrew/bin/python3.11"
FAIL = re.compile(r"^(FAILED|ERROR|SUBFAILED\([^)]*\)) (\S+)", re.M)


def git(*args, cwd=OTTO, check=True):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r


def worktree(path, ref):
    if path.exists():
        git("worktree", "remove", "--force", str(path), check=False)
        shutil.rmtree(path, ignore_errors=True)
    git("worktree", "prune")
    git("worktree", "add", "--detach", str(path), ref)


def build(tasks):
    OUT.mkdir(exist_ok=True)
    base = git("rev-parse", "canon/main").stdout.strip()
    worktree(WT, base)
    merged, dropped = [], []
    for t in tasks:
        r = git("merge", "--no-ff", "--no-edit", "-m", f"Land {t}: {t}", f"lab/{t}", cwd=WT, check=False)
        if r.returncode:
            git("merge", "--abort", cwd=WT, check=False)
            dropped.append({"task": t, "reason": (r.stdout + r.stderr).strip().splitlines()[-1:]})
        else:
            merged.append({"task": t, "sha": git("rev-parse", "HEAD", cwd=WT).stdout.strip()})
    git("branch", "-f", "integ/run", "HEAD", cwd=WT)
    STATE.write_text(json.dumps({"base": base, "order": tasks, "merged": merged, "dropped": dropped}, indent=1))
    print(f"base {base[:8]}; merged {len(merged)}: {' '.join(m['task'] for m in merged)}")
    for d in dropped:
        print(f"DROPPED {d['task']}: {d['reason']}")


def run_file(tree, f, out):
    tmp = tempfile.mkdtemp(prefix="i.", dir="/tmp")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=f"src:tests:{tree}/ops/bootstrap",
               PYTEST_ADDOPTS="-p otto_gate_exit --continue-on-collection-errors", TMPDIR=tmp, OTTO_LAND_TMPDIR=tmp)
    with open(out, "w") as fh:
        rc = subprocess.run([PY, "-m", "pytest", "-q", "-rfE", "-p", "no:cacheprovider", f], cwd=tree, env=env,
                            stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT).returncode
    shutil.rmtree(tmp, ignore_errors=True)
    text = Path(out).read_text(errors="replace")
    ids = sorted(set(m.group(2) for m in FAIL.finditer(text)))
    if rc not in (0, 5) and not ids:
        ids = [f"{f}::exit-{rc}"]
    return f, ids


def suite(tree, files, jobs, tag):
    runs = OUT / f"runs-{tag}"
    runs.mkdir(parents=True, exist_ok=True)
    files = files or sorted(str(p.relative_to(tree)) for p in (tree / "tests").glob("test_*.py"))
    result = {}
    with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
        futs = [pool.submit(run_file, tree, f, runs / (Path(f).name + ".txt")) for f in files]
        for fut in concurrent.futures.as_completed(futs):
            f, ids = fut.result()
            result[f] = ids
            print(f"{'FAIL' if ids else 'ok  '} {f} {len(ids)}", flush=True)
    summary = OUT / f"summary-{tag}.json"
    old = json.loads(summary.read_text()) if summary.exists() else {}
    old.update(result)
    summary.write_text(json.dumps(old, indent=1, sort_keys=True))
    failing = {f: ids for f, ids in result.items() if ids}
    print(f"{tag}: {len(result)} files, {len(failing)} failing")


def bisect(f, ids):
    st = json.loads(STATE.read_text())
    seq = [st["base"]] + [m["sha"] for m in st["merged"]]
    lo, hi = 0, len(seq) - 1  # seq[lo] passes (canon), seq[hi] fails (head)
    wt = LABS / f"_integbisect-{Path(f).stem}"  # one per file, so several bisects run at once
    while hi - lo > 1:
        mid = (lo + hi) // 2
        worktree(wt, seq[mid])
        _, got = run_file(wt, f, OUT / f"bisect-{Path(f).stem}.txt")
        bad = any(i in got for i in ids) or any(g.endswith("::exit-1") for g in got if not ids)
        print(f"  {seq[mid][:8]} ({st['merged'][mid - 1]['task']}): {'fails' if bad else 'passes'}", flush=True)
        lo, hi = (lo, mid) if bad else (mid, hi)
    git("worktree", "remove", "--force", str(wt), check=False)
    print(f"CULPRIT {st['merged'][hi - 1]['task']} for {f}: {' '.join(ids)}")


def main(argv):
    if not argv:
        raise SystemExit(__doc__)
    cmd, rest = argv[0], argv[1:]
    if cmd == "build":
        build(rest)
    elif cmd == "drop":
        st = json.loads(STATE.read_text())
        build([t for t in st["order"] if t not in rest])
    elif cmd in ("suite", "base"):
        jobs = 3
        if rest[:1] == ["--jobs"]:
            jobs, rest = int(rest[1]), rest[2:]
        if cmd == "base":
            worktree(BASE_WT, json.loads(STATE.read_text())["base"])
        suite(WT if cmd == "suite" else BASE_WT, rest, jobs, "head" if cmd == "suite" else "base")
    elif cmd == "bisect":
        bisect(rest[0], rest[1:])
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
