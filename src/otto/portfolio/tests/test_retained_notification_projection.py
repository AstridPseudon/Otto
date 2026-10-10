"""Retained callbacks remain discoverable without reopening native bodies."""
import json
from pathlib import Path
import tempfile
import unittest
from otto.portfolio.retained_projection import finite_summary, read_projection, write_preparation_checkpoint

class UnreadableBody(dict):
    def items(self):
        raise AssertionError('native body was walked')
    def __iter__(self):
        raise AssertionError('native body was walked')

class NotificationProjectionTests(unittest.TestCase):
    def test_exact_notification_handles_in_fixed_slots(self):
        handle='a'*64
        notification={'outcome':'admitted','retained_handle':handle,'response_path':'/owner/response-'+handle+'.json','next_command':'command-status','provider_called':False,'retry_provider':False}
        summary=finite_summary({'request_id':'b'*64,'manager_result_notification':notification,'task_settlement_notification':notification,'raw_result':UnreadableBody({'nested':notification}),'arbitrary_notification':notification})
        self.assertEqual(summary['manager_result_notification'],notification)
        self.assertEqual(summary['task_settlement_notification'],notification)
        self.assertEqual(summary['request_id'],'b'*64)
        self.assertNotIn('raw_result',summary)
        self.assertNotIn('arbitrary_notification',summary)

    def test_notification_field_bounds_and_types(self):
        summary=finite_summary({'manager_result_notification':{'retained_handle':['a'*64], 'response_path':'x'*513,'next_command':{'evil':'command'},'outcome':'pending','stderr':'x'*1000000}})
        self.assertEqual(summary,{'manager_result_notification':{'outcome':'pending'}})
        value={}
        for _ in range(20):value={'task_settlement_notification':value}
        self.assertLess(len(json.dumps(finite_summary(value))),300)

    def test_huge_native_body_bounded_status_and_foreign_binding_denied(self):
        binding={'principal':'owner','assignment_ref':{'id':'assignment','revision':'rev-3'},'generation':1,'project_ref':{'id':'project'},'task_ref':{'id':'D03'}}
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'callback.json'
            write_preparation_checkpoint(p,{'result':{'context_digest_verified':True},'manager_result_notification':{'retained_handle':'a'*64,'next_command':'command-status'},'raw_result':{'stdout':'x'*2000000}},binding=binding)
            view=read_projection(p,expected_binding=binding)
            self.assertEqual(view['summary']['manager_result_notification']['retained_handle'],'a'*64)
            self.assertLess(view['io_work']['metadata_bytes_read'],2000)
            self.assertEqual(view['io_work']['payload_bytes_read'],0)
            self.assertEqual(view['io_work']['payload_bytes_parsed'],0)
            self.assertEqual(view['io_work']['payload_bytes_hashed'],0)
            for altered in ({**binding,'generation':2},{**binding,'principal':'foreign'},{**binding,'project_ref':{'id':'foreign'}}):
                with self.assertRaises(PermissionError):read_projection(p,expected_binding=altered)
            self.assertGreater(p.with_name('callback.detail.json').stat().st_size,2000000)

if __name__=='__main__':unittest.main()
