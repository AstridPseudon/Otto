"""Exact selector semantics and bounded JSON parsing on disposable identities."""
import json
import tempfile
import unittest
from pathlib import Path
from herzchen.contracts import ResourceRef
from herzchen.kernel.store import Store

class IdentityRefPrefilterTests(unittest.TestCase):
 def test_non_candidates_avoid_json_parse_and_embedded_matches_do_not_authorize(self):
  with tempfile.TemporaryDirectory() as d:
   store=Store.create(Path(d)/'fixture.sqlite',authority='owner')
   try:
    def put(n,p):return store.put_identity(ResourceRef('owner','otto.due-record',n,'rev-1'),p)
    wanted='01a12866-8bf8-7c70-a35e-e8b8257d51c2'
    put('large-foreign',{'target':{'native_adapter':'other'},'body':'x'*(37700000)})
    put('embedded-history',{'target':{'native_adapter':'other'},'history':wanted})
    match=put('exact',{'target':{'native_adapter':'codex'},'authorization':{'session':wanted}})
    parsed=[]
    def extract(raw,path):
     parsed.append(len(raw));v=json.loads(raw)
     for key in path[2:].split('.'):v=v.get(key) if isinstance(v,dict) else None
     return v if isinstance(v,(str,int,float)) else None
    store._connection.create_function('json_extract',2,extract)
    refs=store.find_identity_refs(kind='otto.due-record',payload_matches={('target','native_adapter'):'codex',('authorization','session'):wanted})
    self.assertEqual(refs,(match.ref,));self.assertTrue(parsed);self.assertLess(sum(parsed),1000)
    self.assertFalse(store.find_identity_refs(kind='otto.due-record',payload_matches={('authorization','session'):'never-issued'}))
   finally:store.close()
 def test_encoded_unicode_quotes_and_wrong_json_type_remain_exact(self):
  with tempfile.TemporaryDirectory() as d:
   store=Store.create(Path(d)/'fixture.sqlite',authority='owner')
   try:
    value='café "quoted" \\ newline\n'
    good=store.put_identity(ResourceRef('owner','test','good','rev-1'),{'field':value})
    store.put_identity(ResourceRef('owner','test','wrong-path','rev-1'),{'nested':{'field':value}})
    store.put_identity(ResourceRef('owner','test','wrong-type','rev-1'),{'field':7,'history':'7'})
    self.assertEqual(store.find_identity_refs(kind='test',payload_matches={('field',):value}),(good.ref,))
    self.assertEqual(store.find_identity_refs(kind='test',payload_matches={('field',):'7'}),())
   finally:store.close()
