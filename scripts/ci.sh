#!/usr/bin/env bash
# The CI gate: build the wheel, install it into a fresh environment, and test the
# installed package. It grows into the full suite (unit, acceptance, omp
# compatibility) as D3 lands; see docs/plan/13-spec.md B7.
# A skip, an empty collection or a hang is a failure.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3}
rm -rf dist .ci-venv
"$PY" -m venv .ci-venv
.ci-venv/bin/pip install -q --upgrade pip build pytest
.ci-venv/bin/python -m build --wheel --outdir dist . >/dev/null
.ci-venv/bin/pip install -q --force-reinstall dist/*.whl
# Run from outside the source tree, so tests use the installed wheel, not src/.
cd .ci-venv
./bin/otto --version
./bin/python -m pytest -q -p no:cacheprovider ../tests/unit
