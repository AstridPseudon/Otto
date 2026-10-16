"""The production composition's ExecutionHost call must bind and really start.

compose() in install/controller/shared_operating_service.py builds the manager
host with one ExecutionHost(...) call. This test reads that call from source,
so a constructor change that breaks the composition fails here, not at startup.
"""
import ast
import inspect
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from otto.portfolio.execution_host import ExecutionHost

SOURCE = Path(__file__).resolve().parents[1] / "install" / "controller" / "shared_operating_service.py"
NOT_LITERAL = object()


def composition_keywords():
    """The keyword names of the one ExecutionHost(...) call, literal values where ast allows."""
    tree = ast.parse(SOURCE.read_text(), filename=str(SOURCE))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and getattr(node.func, "id", getattr(node.func, "attr", None)) == "ExecutionHost"]
    if len(calls) != 1:
        raise AssertionError("expected exactly one ExecutionHost(...) call in %s, found %d" % (SOURCE, len(calls)))
    call = calls[0]
    if call.args:
        raise AssertionError("ExecutionHost(...) in %s must pass keywords only" % SOURCE)
    keywords = {}
    for keyword in call.keywords:
        if keyword.arg is None:
            raise AssertionError("ExecutionHost(**...) in %s cannot be checked statically" % SOURCE)
        try:
            keywords[keyword.arg] = ast.literal_eval(keyword.value)
        except (ValueError, TypeError, SyntaxError):
            keywords[keyword.arg] = NOT_LITERAL
    return keywords


class CompositionHostTests(unittest.TestCase):
    def test_every_composition_keyword_binds_to_the_constructor(self):
        keywords = composition_keywords()
        self.assertTrue(keywords, "the composition passes keywords to ExecutionHost")
        signature = inspect.signature(ExecutionHost.__init__)
        try:
            signature.bind(None, **keywords)
        except TypeError as error:
            self.fail("ExecutionHost(...) in %s no longer binds to its constructor: %s" % (SOURCE, error))

    def test_composed_host_builds_holds_and_starts(self):
        keywords = composition_keywords()
        root = Path(tempfile.mkdtemp(prefix="otto-compose-"))
        self.addCleanup(shutil.rmtree, root, True)
        socket_dir = Path(tempfile.mkdtemp(prefix="otto-sock-", dir="/tmp"))
        self.addCleanup(shutil.rmtree, socket_dir, True)
        kwargs = {}
        for name, value in keywords.items():
            if value is not NOT_LITERAL:
                kwargs[name] = value
            elif name == "directory":
                kwargs[name] = root
            elif name == "handler":
                kwargs[name] = lambda request: None
            elif name == "owner_path":
                kwargs[name] = root / "owner.json"
            elif name == "socket_path":
                kwargs[name] = socket_dir / "s.sock"
                self.assertLess(len(os.fsencode(str(kwargs[name]))), 100, "AF_UNIX paths must stay under 100 bytes")
            else:
                self.fail("ExecutionHost(...) keyword %r is not a literal and this test has no value for it; "
                          "add one deliberately in test_host_startup_composition.py" % name)
        host = ExecutionHost(**kwargs)
        closed = []

        def close():
            if not closed:
                closed.append(True)
                host.close()
        self.addCleanup(close)  # runs before the temp dirs are removed, even if start() fails
        host.hold_admission()
        host.start()
        close()
        self.assertTrue(host.dispatch_held)
        self.assertEqual(host.capacity.snapshot()["policy"]["turn_units"], 6)

    def test_source_has_no_manager_turn_limit(self):
        self.assertNotIn("manager_turn_limit", SOURCE.read_text(),
                         "the manager turn cap is gone; the composition must not pass it")


if __name__ == "__main__":
    unittest.main()
