#!/usr/bin/env python3.11
"""Rebuild the file digests of install/runtime-manifest.json from the source tree.

  install/build_manifest.py [--rev REV] [--check MANIFEST]

Two sections are digested, one sha256 per tracked file:
  files        under src/, keyed by path relative to src/
  entrypoints  under install/controller/, keyed by path relative to it

--rev REV reads each file as committed at REV (git ls-tree and git show).
Without --rev the working tree is read, for the tracked files only.

Without --check, prints {"files": ..., "entrypoints": ...} as JSON.
With --check MANIFEST, compares every digest the manifest lists and exits 1 on any
mismatch or missing file. Tracked files the manifest does not list are reported,
not failed: the manifest covers a subset of src/ (the vision pack and vision content
are not in it).
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECTIONS = {"files": "src", "entrypoints": "install/controller"}


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True).stdout


def tracked(rev, prefix):
    if rev is None:
        out = git("ls-files", "-z", "--", prefix)
    else:
        out = git("ls-tree", "-r", "--name-only", "-z", rev, "--", prefix)
    return [p.decode() for p in out.split(b"\0") if p]


def content(rev, path):
    if rev is None:
        return (ROOT / path).read_bytes()
    return git("show", f"{rev}:{path}")


def digests(rev):
    built = {}
    for section, prefix in SECTIONS.items():
        strip = len(prefix) + 1
        built[section] = {
            path[strip:]: hashlib.sha256(content(rev, path)).hexdigest()
            for path in tracked(rev, prefix)
        }
    return built


def compare(built, manifest_path):
    manifest = json.loads(Path(manifest_path).read_text())
    failed = False
    for section in SECTIONS:
        listed = manifest[section]
        have = built[section]
        matched = 0
        for rel, want in sorted(listed.items()):
            if rel not in have:
                print(f"missing: {section}/{rel}")
                failed = True
            elif have[rel] != want:
                print(f"mismatch: {section}/{rel} built {have[rel][:12]} manifest {want[:12]}")
                failed = True
            else:
                matched += 1
        unlisted = sorted(set(have) - set(listed))
        print(f"{section}: {matched}/{len(listed)} listed digests match; "
              f"{len(unlisted)} tracked file(s) not in the manifest")
    return 1 if failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--rev", help="read the files as committed at this revision")
    parser.add_argument("--check", metavar="MANIFEST", help="compare against this manifest")
    args = parser.parse_args(argv)

    built = digests(args.rev)
    if args.check is None:
        json.dump(built, sys.stdout, indent=1, sort_keys=True)
        print()
        return 0
    return compare(built, args.check)


if __name__ == "__main__":
    sys.exit(main())
