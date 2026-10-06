"""Status uses the real serialized owner/pump, never a concurrent SQLite reader."""
import json,sqlite3,tempfile,threading,time,unittest
from pathlib import Path
from otto.portfolio.execution_host import ExecutionHost
class StatusCustodyTests(unittest.TestCase):
 def wait(self,path):
  deadline=time.monotonic()+4
  while not path.exists() and time.monotonic()<deadline:time.sleep(.01)
  self.assertTrue(path.exists());return json.loads(path.read_text())
 def test_status_during_native_wait_is_served_on_owner_before_native_returns(self):
  with tempfile.TemporaryDirectory() as directory:
   d=Path(directory);identities={};queried=threading.Event();connection=sqlite3.connect(':memory:',check_same_thread=False)
   def handler(r):
    if r['command']=='start-manager':
     identities['owner']=threading.get_ident()
     def native():
      identities['native']=threading.get_ident();(d/'request-bbbb.json').write_text(json.dumps({'command':'status'}))
      if not queried.wait(3):raise AssertionError('status blocked admitted native wait')
      return {'outcome':'succeeded'}
     return ExecutionHost.external_call(native)
    identities['status']=threading.get_ident();value=connection.execute('select 17').fetchone()[0];queried.set();return {'outcome':'read','value':value}
   host=ExecutionHost(directory=d,handler=handler)
   try:
    host.start();(d/'request-aaaa.json').write_text(json.dumps({'command':'start-manager'}));self.assertEqual(self.wait(d/'response-bbbb.json')['value'],17);self.assertEqual(self.wait(d/'response-aaaa.json')['outcome'],'succeeded');self.assertEqual(identities['status'],identities['owner']);self.assertNotEqual(identities['status'],identities['native'])
   finally:host.close();connection.close()
 def test_status_waits_for_finite_owner_query_instead_of_overlapping_connection(self):
  with tempfile.TemporaryDirectory() as directory:
   d=Path(directory);entered=threading.Event();release=threading.Event();queried=threading.Event();active=False
   def handler(r):
    nonlocal active
    if r['command']=='finite-query':
     active=True;entered.set();release.wait(3);active=False;return {'outcome':'read'}
    self.assertFalse(active,'status overlapped shared SQLite owner query');queried.set();return {'outcome':'read'}
   host=ExecutionHost(directory=d,handler=handler)
   try:
    host.start();(d/'request-aaaa.json').write_text(json.dumps({'command':'finite-query'}));self.assertTrue(entered.wait(2));(d/'request-bbbb.json').write_text(json.dumps({'command':'status'}));self.assertFalse(queried.wait(.15));release.set();self.assertEqual(self.wait(d/'response-bbbb.json')['outcome'],'read');self.assertEqual(self.wait(d/'response-aaaa.json')['outcome'],'read')
   finally:release.set();host.close()
if __name__=='__main__':unittest.main()
