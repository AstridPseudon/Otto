"""Exact closed source cutover retains its prior crash allowance and history."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from otto.hostctl.supervision import prepare_planned_maintenance, maintenance_restart_limit
from otto.portfolio.execution_host import ExecutionHost


class PlannedMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.old = Path(self.temp.name) / 'prior.json'
        self.new = self.old.with_name('successor.json')
        self.custody = dict(ordinary_exit_status=0, store_closed=True, owner_alive=False,
            supervisor_alive=False, native_active_or_uncertain=0, holds=[], in_flight=[])

    def original(self, codes=(0,), maximum=2):
        codes = iter(codes)
        class Process:
            pid = 123
            def wait(self, timeout): return next(codes)
        return ExecutionHost.supervise(argv=['/usr/bin/true'], receipt_path=self.old,
            source_identity={'source_commit': 'old'}, reconcile=lambda _: {'ready': True},
            disposition=lambda: 'active', request_stop=lambda _: None,
            max_restarts=maximum, restart_delay=.001, max_restart_delay=.001,
            process_factory=lambda *a, **k: Process())

    def arguments(self):
        return dict(old_path=self.old, new_path=self.new,
            expected_policy_sha256=hashlib.sha256(self.old.read_bytes()).hexdigest(),
            expected_exits={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.old.parent.glob(self.old.name + '.exit-*.json')},
            source_identity={'source_commit': 'new', 'manifest_sha256': 'pin'},
            request_key='planned-upgrade-once', custody=self.custody)

    def test_clean_upgrade_replay_one_launch_and_old_bytes_immutable(self):
        self.original()
        original = {p.name: p.read_bytes() for p in self.old.parent.glob('prior.json*')}
        args = self.arguments()
        transition = prepare_planned_maintenance(**args)
        self.assertEqual(transition['automatic_restart_budget'],
            dict(original_max=2, previously_consumed=0, remaining=2))
        self.assertEqual(prepare_planned_maintenance(**args), transition)
        policy = json.loads(self.new.read_text())
        intent = dict(argv=policy['argv'], metadata=policy['source_identity'], supervision_path=str(self.new))
        self.assertEqual(maintenance_restart_limit(intent), 2)
        calls = []
        class Process:
            pid = 124
            def wait(self, timeout): return 0
        values = {k: policy[k] for k in ('argv','source_identity','max_restarts','restart_delay','max_restart_delay')}
        for _ in range(2):
            result = ExecutionHost.supervise(**values, receipt_path=self.new, resume=True,
                reconcile=lambda _: {'ready': True}, disposition=lambda: 'active', request_stop=lambda _: None,
                process_factory=lambda *a, **k: calls.append(a) or Process())
            self.assertEqual(result['outcome'], 'closed')
        self.assertEqual(len(calls), 1)
        for name, data in original.items(): self.assertEqual((self.old.parent/name).read_bytes(), data)
        with self.assertRaises(PermissionError):
            prepare_planned_maintenance(**{**args, 'source_identity': {'source_commit':'changed'}})
        with self.assertRaises(PermissionError):
            prepare_planned_maintenance(**{**args, 'request_key':'another'})

    def test_prior_crash_consumption_carries_across_multiple_upgrades(self):
        self.original((9,0))
        first = prepare_planned_maintenance(**self.arguments())
        self.assertEqual(first['automatic_restart_budget']['remaining'],1)
        policy=json.loads(self.new.read_text())
        class Process:
            pid=125
            def wait(self,timeout):return 0
        ExecutionHost.supervise(**{k:policy[k] for k in ('argv','source_identity','max_restarts','restart_delay','max_restart_delay')},
            receipt_path=self.new,resume=True,reconcile=lambda _: {'ready':True},
            disposition=lambda:'active',request_stop=lambda _:None,process_factory=lambda *a,**k:Process())
        second=prepare_planned_maintenance(old_path=self.new,new_path=self.new.with_name('third.json'),
            expected_policy_sha256=hashlib.sha256(self.new.read_bytes()).hexdigest(),
            expected_exits={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.new.parent.glob(self.new.name+'.exit-*.json')},
            source_identity={'source_commit':'third'},request_key='next-upgrade',custody=self.custody)
        self.assertEqual(second['automatic_restart_budget'],dict(original_max=2,previously_consumed=1,remaining=1))

    def test_exhaustion_unknown_missing_tail_live_custody_and_changed_cas_refuse(self):
        self.original((9,9,9))
        with self.assertRaises(PermissionError): prepare_planned_maintenance(**self.arguments())
        self.assertFalse(self.new.exists())
        # A separately constructed clean lineage proves each refusal before seed.
        for p in self.old.parent.glob('prior.json*'): p.unlink()
        self.original()
        args=self.arguments()
        for change in ({'owner_alive':True},{'supervisor_alive':True},{'native_active_or_uncertain':1},
                {'holds':['unknown']},{'in_flight':['request']},{'store_closed':False}):
            with self.assertRaises(PermissionError):
                prepare_planned_maintenance(**{**args,'custody':{**self.custody,**change}})
        with self.assertRaises(PermissionError):prepare_planned_maintenance(**{**args,'expected_exits':{}})
        with self.assertRaises(PermissionError):prepare_planned_maintenance(**{**args,'expected_policy_sha256':'bad'})
        path=next(self.old.parent.glob('prior.json.exit-*')); raw=json.loads(path.read_text())
        raw['exit_status']=None;path.write_text(json.dumps(raw))
        with self.assertRaises(PermissionError):prepare_planned_maintenance(**self.arguments())
        self.assertFalse(self.new.exists())

    def test_preparation_lost_response_or_partial_seed_does_not_issue_another_lineage(self):
        self.original();args=self.arguments()
        transition=prepare_planned_maintenance(**args)
        self.new.unlink()  # The durable transition was committed before seed publication.
        self.assertEqual(prepare_planned_maintenance(**args),transition)
        policy=json.loads(self.new.read_text())
        intent=dict(argv=policy['argv'],metadata=policy['source_identity'],supervision_path=str(self.new))
        self.assertEqual(maintenance_restart_limit(intent),2)
        with self.assertRaises(PermissionError):
            prepare_planned_maintenance(**{**args,'new_path':self.new.with_name('different.json')})
        prior_exit=next(self.old.parent.glob('prior.json.exit-*'));prior_exit.write_text('{}')
        with self.assertRaises(PermissionError):maintenance_restart_limit(intent)


if __name__ == '__main__': unittest.main()
