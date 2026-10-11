"""Unrelated retained result bodies must not enter relation JSON parsing."""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from herzchen.contracts import ResourceRef
from herzchen.kernel.store import Store
from herzchen.domains.work.sheet import _ProjectSheetEngine

class SheetRelationPrefilterTests(unittest.TestCase):
 def test_prefilter_bounds_parse_without_granting_embedded_or_foreign_relations(self):
  with tempfile.TemporaryDirectory() as d:
   store=Store.create(Path(d)/'tiny.sqlite',authority='owner')
   try:
    wanted=ResourceRef('owner','wrk.assignment','assignment-café-"quoted"','rev-3')
    def put(n,p):return store.put_identity(ResourceRef('owner','wrk.result',n,'rev-1'),p)
    put('foreign-large',{'assignment':{'authority':'owner','kind':'wrk.assignment','id':'elsewhere'},'body':'x'*1000000})
    good=put('good',{'assignment':wanted.to_dict()})
    put('historical',{'assignment':{**wanted.to_dict(),'revision':'rev-1'}})
    put('embedded',{'assignment':{'authority':'owner','kind':'wrk.assignment','id':'elsewhere'},'history':wanted.to_dict()})
    put('wrong-authority',{'assignment':{**wanted.to_dict(),'authority':'foreign'}})
    put('wrong-kind',{'assignment':{**wanted.to_dict(),'kind':'work.task'}})
    put('substring',{'assignment':{**wanted.to_dict(),'id':wanted.id+'-suffix'}})
    parsed=[]
    def extract(raw,path):
     parsed.append(len(raw));v=json.loads(raw)
     for k in path[2:].split('.'):v=v.get(k) if isinstance(v,dict)else None
     return json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list))else v
    store._connection.create_function('json_extract',2,extract)
    engine=object.__new__(_ProjectSheetEngine)
    engine._ProjectSheetEngine__writer=SimpleNamespace(connection=store._connection,authority='owner')
    rows=engine._related_rows(('wrk.result',),'assignment',(wanted,))
    self.assertEqual([r['id']for r in rows],['good','historical'])
    self.assertTrue(parsed);self.assertLess(max(parsed),1000)
    self.assertEqual(engine._related_rows(('wrk.result',),'assignment',()),())
   finally:store.close()
 def test_document_subject_legacy_and_association_paths_stay_exact(self):
  with tempfile.TemporaryDirectory() as d:
   store=Store.create(Path(d)/'tiny.sqlite',authority='owner')
   try:
    wanted=ResourceRef('owner','work.project','project','rev-2')
    for n,p in [('association',{'association':{'subject':wanted.to_dict()}}),('legacy',{'subject':wanted.to_dict()}),('embedded',{'subject':{'id':'foreign'},'history':wanted.to_dict()})]:
     store.put_identity(ResourceRef('owner','dat.association',n,'rev-1'),p)
    engine=object.__new__(_ProjectSheetEngine)
    engine._ProjectSheetEngine__writer=SimpleNamespace(connection=store._connection,authority='owner')
    self.assertEqual([r['id']for r in engine._related_rows(('dat.association',),'document_subject',(wanted,))],['association','legacy'])
   finally:store.close()
