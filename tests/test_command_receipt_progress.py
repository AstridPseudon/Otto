"""Finite owner progress never implies failure, replay permission or effects."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from otto.portfolio.execution_host import ExecutionHost
from otto.portfolio.manager_journey_client import read_command_status, wait_command_response

class CommandReceiptProgressTests(unittest.TestCase):
    def test_retained_queued_request_is_pending_and_wait_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'request-abc.json').write_text('{"command":"finish-task"}')
            receipt=read_command_status(root,'abc')
            self.assertEqual(receipt['outcome'],'pending')
            self.assertFalse(receipt['retry']); self.assertNotIn('effects_started',receipt)
            start=time.monotonic(); self.assertEqual(wait_command_response(root,'abc',timeout_seconds=.05),receipt)
            self.assertLess(time.monotonic()-start,.5)
            self.assertIsNone(read_command_status(root,'def'))
            with self.assertRaises(ValueError):read_command_status(root,'bad-handle')

    def test_processing_receipt_precedes_finite_effect_and_terminal_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); entered=threading.Event(); release=threading.Event(); calls=[]
            def handle(request):
                calls.append(request); entered.set(); release.wait(3)
                return {'outcome':'completed','task_completion_recorded':True}
            host=ExecutionHost(directory=root,handler=handle); host.start()
            try:
                (root/'request-abc.json').write_text('{"command":"finish-task"}')
                self.assertTrue(entered.wait(2))
                progress=read_command_status(root,'abc')
                self.assertEqual(progress['request_state'],'processing')
                self.assertFalse(progress['retry']); self.assertNotIn('provider_called',progress)
                self.assertEqual(wait_command_response(root,'abc',timeout_seconds=.05),progress)
                release.set()
                deadline=time.monotonic()+2
                while not (root/'response-abc.json').exists() and time.monotonic()<deadline:time.sleep(.01)
                response=wait_command_response(root,'abc',timeout_seconds=.1)
                self.assertEqual(response['outcome'],'completed')
                self.assertTrue(read_command_status(root,'abc')['terminal'])
                self.assertEqual(len(calls),1)
                self.assertFalse((root/'pending-abc.json').exists())
            finally:release.set(); host.close()
