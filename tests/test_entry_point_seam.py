"""The production entry point's location seam: install/controller/shared_operating_service.py.

Each live location (controller folder C, PRIVATE, the sibling controllers VC and PC, the host
installation home) can be moved by an environment variable. With none set, the entry point must
resolve exactly the paths it did before the seam, because the live install is deployed from this
file. These tests never import the module: importing it imports the live controller's code. They
evaluate the seam's own assignments from the syntax tree instead, with a stand-in `os.environ`.
"""
import ast
import subprocess
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "install" / "controller" / "shared_operating_service.py"
BEFORE_SEAM = "9739a29"  # the entry point as deployed before the seam
SEAM_NAMES = {"C": "OTTO_CONTROLLER_DIR", "PRIVATE": "OTTO_PRIVATE_DIR", "VC": "OTTO_VISION_CONTROLLER_DIR",
              "PC": "OTTO_ASTRID_CONTROLLER_DIR", "HOST_HOME": "OTTO_HOST_HOME"}
LIVE_ROOTS = ("/Users/hannahomalley/Documents/Codex", "/Users/hannahomalley/.codex", "/Users/hannahomalley/.otto")


def before_source():
    r = subprocess.run(["git", "show", "%s:install/controller/shared_operating_service.py" % BEFORE_SEAM],
                       cwd=ROOT, text=True, capture_output=True)
    if r.returncode:
        raise AssertionError("cannot read the pre-seam entry point at %s: %s" % (BEFORE_SEAM, r.stderr))
    return r.stdout


def evaluate(tree, names, env):
    """Run the module-level assignments to `names`, in order, with os.environ replaced by `env`."""
    assigns = [n for n in tree.body if isinstance(n, ast.Assign) and len(n.targets) == 1
               and isinstance(n.targets[0], ast.Name) and n.targets[0].id in names]
    space = {"Path": Path, "os": types.SimpleNamespace(environ=dict(env))}
    exec(compile(ast.Module(body=assigns, type_ignores=[]), str(ENTRY), "exec"), space)
    return {name: str(space[name]) for name in names if name in space}


def old_host_home(tree):
    """The pre-seam host installation home: the argument of the load_host_installation(...) call."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "load_host_installation":
            return str(eval(compile(ast.Expression(node.args[0]), "old", "eval"), {"Path": Path}))
    raise AssertionError("no load_host_installation call in the pre-seam entry point")


class EntryPointSeam(unittest.TestCase):
    def setUp(self):
        self.new = ast.parse(ENTRY.read_text())
        self.old = ast.parse(before_source())

    def test_defaults_equal_the_pre_seam_literals(self):
        old = evaluate(self.old, {"C", "PRIVATE", "VC", "PC"}, {})
        old["HOST_HOME"] = old_host_home(self.old)
        new = evaluate(self.new, set(SEAM_NAMES), {})
        self.assertEqual(new, old)

    def test_empty_overrides_fall_back_to_the_defaults(self):
        new = evaluate(self.new, set(SEAM_NAMES), {})
        empty = evaluate(self.new, set(SEAM_NAMES), {v: "" for v in SEAM_NAMES.values()})
        self.assertEqual(empty, new)

    def test_overrides_move_every_location_to_the_temp_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {var: "%s/%s" % (tmp, name) for name, var in SEAM_NAMES.items()}
            moved = evaluate(self.new, set(SEAM_NAMES), env)
            self.assertEqual(moved, {name: "%s/%s" % (tmp, name) for name in SEAM_NAMES})

    def test_moving_only_the_controller_moves_its_siblings_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            moved = evaluate(self.new, {"C", "VC", "PC"}, {"OTTO_CONTROLLER_DIR": tmp + "/a/b/controller"})
            self.assertTrue(moved["VC"].startswith(tmp), moved)
            self.assertTrue(moved["PC"].startswith(tmp), moved)

    def test_no_live_path_remains_outside_an_override_default(self):
        parents = {child: node for node in ast.walk(self.new) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(self.new):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and node.value.startswith(LIVE_ROOTS)):
                continue
            parent = parents[node]
            behind_override = (isinstance(parent, ast.BoolOp) and isinstance(parent.op, ast.Or)
                               and parent.values[-1] is node and isinstance(parent.values[0], ast.Call)
                               and ast.unparse(parent.values[0]).startswith("os.environ.get('OTTO_"))
            self.assertTrue(behind_override, "live path at line %d is not behind an override" % node.lineno)


if __name__ == "__main__":
    unittest.main()
