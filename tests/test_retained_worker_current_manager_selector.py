"""An adopted manager selects its current entrance without rewriting worker parent."""
import copy
import unittest
from types import SimpleNamespace
from otto.portfolio.manager_journey_service import ManagerJourneyService


def ref(kind, ident, rev=None):
    return {'authority':'owner','kind':kind,'id':ident,'revision':rev}


class RetainedWorkerCurrentManagerSelectorTests(unittest.TestCase):
    def fixture(self):
        assignment=ref('wrk.assignment','manager','rev-2')
        project=ref('work.project','project','rev-1')
        worker={'principal':'worker','model':'gpt-5.6-luna','reasoning':'high',
                'schedule_id':'worker-original','manager_schedule_id':'old-parent'}
        state={'manager':'manager','assignment_ref':assignment,'manager_generation':1,
               'project_ref':project,'schedule_id':'current-manager',
               'manager_continuation':{'schedule_id':'current-manager'},'workers':{'D04':worker}}
        current={'schedule_id':'current-manager','role':'manager','recipient':'manager',
                 'target':{'project_ref':project},'assignment_ref':assignment,'generation':1,
                 'stop_state':'active','completion_state':'none','in_flight_request':None}
        old=copy.deepcopy(current);old.update(schedule_id='old-parent',assignment_ref=ref('wrk.assignment','manager','rev-1'),stop_state='completed',completion_state='succeeded')
        rows={'current-manager':current,'old-parent':old,'worker-original':{'target':{}}}
        calls=[]
        class App:
            def synchronize_manual_manager_occurrence(self,*,schedule_id):
                self.assert_current(schedule_id);calls.append(('sync',schedule_id))
            def assert_current(self,schedule):
                if schedule!='current-manager':raise AssertionError('stale historical parent selected')
            def start(self,*,schedule_id):
                calls.append(('start',schedule_id));return {'outcome':'started','schedule_id':schedule_id}
        service=object.__new__(ManagerJourneyService)
        service.server=SimpleNamespace(state=state,due_port=SimpleNamespace(read_due=lambda sid:rows.get(sid)))
        service.commands=SimpleNamespace(_authorize=lambda:None)
        service._execution=lambda **kwargs:App()
        request={'command':'start-retained-worker','task':'D04','principal':'worker','schedule_id':'worker-original'}
        return service,request,rows,calls,worker

    def test_old_parent_uses_current_prepared_or_settled_manager(self):
        for terminal in(False,True):
            with self.subTest(terminal=terminal):
                service,request,rows,calls,worker=self.fixture();before=copy.deepcopy(worker);old=copy.deepcopy(rows['old-parent'])
                if terminal:rows['current-manager'].update(stop_state='completed',completion_state='succeeded')
                result=service(request)
                self.assertEqual(result['outcome'],'started')
                self.assertEqual(calls,[('sync','current-manager'),('start','worker-original')])
                self.assertEqual(worker,before);self.assertEqual(rows['old-parent'],old)

    def test_foreign_or_generation_or_stale_current_reject_before_start(self):
        changes=[{'recipient':'foreign'},{'generation':2},{'assignment_ref':ref('wrk.assignment','foreign','rev-2')},
                 {'target':{'project_ref':ref('work.project','foreign','rev-1')}},
                 {'assignment_ref':ref('wrk.assignment','manager','rev-1')}]
        for change in changes:
            with self.subTest(change=change):
                service,request,rows,calls,worker=self.fixture();rows['current-manager'].update(change)
                with self.assertRaises(PermissionError):service(request)
                self.assertEqual(calls,[])

    def test_stale_or_foreign_worker_handle_rejects(self):
        service,request,rows,calls,worker=self.fixture();request['principal']='foreign'
        with self.assertRaises(PermissionError):service(request)
        self.assertEqual(calls,[])
