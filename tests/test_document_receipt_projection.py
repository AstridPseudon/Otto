import unittest
from types import SimpleNamespace
from otto.portfolio.herzchen_binding import FiniteWorkOperations, HerzchenBindingConfig
from herzchen.contracts import ResourceRef
from otto.portfolio.tests import test_portfolio_direction as fixtures

class DocumentReceiptProjectionTests(unittest.TestCase):
    def operation(self, reader):
        return FiniteWorkOperations(port=object(),reader=reader,binding=HerzchenBindingConfig('owner','credential'))
    def receipt(self, **changes):
        value={'operation':'dat.content.document.create','target':ResourceRef('owner','dat.content.document','doc').to_dict(),'event_ids':['wanted','missing']};value.update(changes);return value
    def test_document_subject_is_filtered_before_hydration_and_missing_ids_stay_missing(self):
        calls=[]
        class Reader:
            def list_events(inner, **kw):
                calls.append(kw)
                self.assertEqual(kw,{'subjects':(ResourceRef('owner','dat.content.document','doc'),)})
                return (SimpleNamespace(event_id='other'),SimpleNamespace(event_id='wanted'))
        self.assertEqual(self.operation(Reader())._events_for(self.receipt()),['wanted'])
        self.assertEqual(len(calls),1)
    def test_foreign_or_non_document_target_is_rejected_before_read(self):
        class Reader:
            def list_events(inner, **kw):raise AssertionError('unexpected event read')
        for target in [ResourceRef('foreign','dat.content.document','doc'),ResourceRef('owner','due.record','doc')]:
            with self.subTest(target=target),self.assertRaises(ValueError):self.operation(Reader())._events_for(self.receipt(target=target.to_dict()))
    def test_empty_receipt_avoids_reads(self):
        class Reader:
            def list_events(inner, **kw):raise AssertionError('unexpected read')
        self.assertEqual(self.operation(Reader())._events_for(self.receipt(event_ids=[])),[])
    def test_other_operation_keeps_existing_projection_order(self):
        calls=[]
        class Reader:
            def list_events(inner, **kw):
                calls.append(kw)
                return (SimpleNamespace(event_id='second'),SimpleNamespace(event_id='first'))
        self.assertEqual(self.operation(Reader())._events_for(self.receipt(operation='work.sheet.apply',event_ids=['first','second'])),['second','first'])
        # The receipt's own subject filters the read; a shared Store's whole history is not decoded.
        self.assertEqual(calls,[{'subjects':(ResourceRef('owner','dat.content.document','doc'),)}])
    def test_missing_subject_event_does_not_expand_to_global_history(self):
        calls=[]
        class Reader:
            def list_events(inner, **kw):
                calls.append(kw)
                if not kw:
                    raise AssertionError('global event hydration forbidden')
                return (SimpleNamespace(event_id='first'),)
        self.assertEqual(self.operation(Reader())._events_for(self.receipt(operation='work.sheet.apply',event_ids=['first','second'])),['first'])
        self.assertEqual(len(calls),1)
    def test_real_owner_document_commit_and_exact_replay_keep_receipt_events(self):
        f=fixtures.PortfolioDirectionTests();f.setUp();self.addCleanup(f.doCleanups)
        from otto.portfolio.intake import OttoPortfolio
        _,_,_,project=f.setup_portfolio();app=OttoPortfolio(f.owner.consumer_operations())
        original=app.operations._owner_reader
        class Probe:
            def __getattr__(inner,name):return getattr(original,name)
            def list_events(inner,**kw):
                self.assertIn('subjects',kw)
                self.assertTrue(all(x.kind=='dat.content.document' for x in kw['subjects']))
                return original.list_events(**kw)
        app.operations._owner_reader=Probe()
        args=dict(actor=f.actor.actor,request_id='bounded-doc-projection',document_id='bounded-doc',content={'text':'actual content'},role='source')
        first=app.create_document(project.ref,**args);self.assertEqual(first['outcome'],'created',first)
        replay=app.create_document(project.ref,**args);self.assertEqual(replay['outcome'],'replayed',replay)
        self.assertEqual(first['event_ids'],replay['event_ids']);self.assertEqual(first['event_ids'],first['receipt']['event_ids']);self.assertEqual(len(first['event_ids']),1)
        conflict=app.create_document(project.ref,**{**args,'content':{'text':'changed'}});self.assertEqual(conflict['outcome'],'error');self.assertEqual(conflict['error']['code'],'replay_conflict')
if __name__=='__main__':unittest.main()
