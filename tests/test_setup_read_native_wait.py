"""Only finite setup read enters the same owner lane during a native wait."""
import argparse,json,tempfile,threading,time,unittest
from pathlib import Path
from otto.portfolio.execution_host import ExecutionHost
from otto.portfolio.manager_journey_client import add_manager_journey_parsers
class SetupReadNativeWaitTests(unittest.TestCase):
 def test_setup_read_is_pumped_while_activation_and_preparation_are_held(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);threads={};seen=[];finished=threading.Event()
   parser=argparse.ArgumentParser();commands=parser.add_subparsers(dest='command',required=True)
   add_manager_journey_parsers(commands)
   installed_read=vars(parser.parse_args(['operating-setup','--operation','read']))
   self.assertEqual(installed_read,{'command':'operating-setup','operation':'read','setup':None,'request_key':None})
   requests=[installed_read,{'command':'operating-setup','operation':'read'},
             {'command':'operating-setup','operation':'activate'},
             {'command':'operating-setup','operation':'prepare','setup':{}},
             {'command':'operating-setup','operation':'read','request_key':'mutating-extra'},
             {'command':'operating-setup','operation':'read','setup':{}},
             {'command':'operating-setup','operation':'read','project_ref':None}]
   def handler(request):
    if request['command']=='start-manager':
     threads['owner']=threading.get_ident()
     def native():
      threads['native']=threading.get_ident()
      for i,r in enumerate(requests):(root/f'request-{i+1:064x}.json').write_text(json.dumps(r))
      deadline=time.monotonic()+3
      while time.monotonic()<deadline:
       if all((root/f'response-{i+1:064x}.json').exists() for i in range(len(requests))):finished.set();return {'outcome':'succeeded'}
       time.sleep(.01)
      raise AssertionError('nested setup inspection self-waited')
     return ExecutionHost.external_call(native)
    seen.append(request);threads['reader']=threading.get_ident();return {'outcome':'read','provider_called':False,'effects_started':False}
   host=ExecutionHost(directory=root,handler=handler)
   try:
    host.start();(root/('request-'+'a'*64+'.json')).write_text(json.dumps({'command':'start-manager'}))
    self.assertTrue(finished.wait(5));self.assertEqual(seen,requests[:2])
    self.assertEqual(threads['owner'],threads['reader']);self.assertNotEqual(threads['owner'],threads['native'])
    for i in range(2):self.assertEqual(json.loads((root/f'response-{i+1:064x}.json').read_text())['outcome'],'read')
    for i in range(2,len(requests)):
     value=json.loads((root/f'response-{i+1:064x}.json').read_text());self.assertEqual(value['outcome'],'held');self.assertFalse(value['effects_started']);self.assertFalse(value['provider_called'])
   finally:host.close()
if __name__=='__main__':unittest.main()
