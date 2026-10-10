"""End-to-end regressions for configured Events final1 findings, disposable owners only."""
import hashlib,json,unittest
from unittest.mock import patch
from test_project_history import ProjectHistoryTests as _ReaderFixture
from test_events_history import HistoryTests as _HistoryFixture
from herzchen.kernel import ProjectHistoryGrant
from herzchen.kernel.project_history import CursorError,ProjectionMaintenanceError,ProjectHistoryProjection
from herzchen.contracts import ResourceRef
from herzchen.domains.work.batches import ProjectBatches
from otto.portfolio.observability_views import ObservabilityViews

class ReaderCorrectionTests(unittest.TestCase):
    setUp=_ReaderFixture.setUp
    def test_issued_cursor_roundtrip_and_cross_mode_rejection(self):
        for i in range(4):self.graph.revise(self.project,title=str(i),logical_request_key='revision-'+str(i))
        p=self.reader.read(projects=[self.project.ref],limit=1);seen=[]
        for _ in range(10):
            seen.extend(x['facet_id'] for x in p['rows'])
            if not p['next_cursor']:break
            p=self.reader.read(projects=[self.project.ref],limit=1,snapshot=p['snapshot'],cursor=p['next_cursor'])
        self.assertEqual(len(seen),5);self.assertEqual(len(set(seen)),5)
        a=self.reader.read_state(projects=[self.project.ref],limit=1)
        if a['next_cursor']:
            with self.assertRaises(CursorError):self.reader.read(projects=[self.project.ref],snapshot=a['snapshot'],cursor=a['next_cursor'])
    def test_empty_partial_page_advances_exact_snapshot(self):
        row=list(self.store.connection.execute('SELECT * FROM project_history LIMIT 1').fetchone())
        # Disposable projection-only fixture, never production source mutation.
        with self.store.transaction() as tx:
            for i in range(1,1006):
                v=list(row);v[1]='facet-'+str(i);v[3]=i;v[15]='target' if i==1005 else 'other'
                tx.execute('INSERT INTO project_history VALUES('+','.join('?' for _ in v)+')',v)
        a=self.reader.read(projects=[self.project.ref],filters={'facet_type':'target'},limit=1)
        self.assertTrue(a['partial']);self.assertFalse(a['rows']);self.assertTrue(a['next_cursor'])
        b=self.reader.read(projects=[self.project.ref],filters={'facet_type':'target'},limit=1,snapshot=a['snapshot'],cursor=a['next_cursor'])
        self.assertEqual(len(b['rows']),1);self.assertEqual(b['rows'][0]['facet_index'],1005)
    def dated_project(self,key,active,closed=None):
        with patch('herzchen.kernel.store._now',return_value='2026-10-01T00:00:00Z'):
            p=self.graph.create_project(title=key,logical_request_key=key)
            if active:p=self.graph.set_lifecycle(p.ref,'active',logical_request_key=key+'-active')
        if closed:
            with patch('herzchen.kernel.store._now',return_value=closed):p=self.graph.set_lifecycle(p.ref,'completed',logical_request_key=key+'-closed')
        return p
    def test_latest_predecessor_overlap_and_no_current_head_substitution(self):
        ended=self.dated_project('ended',True,'2026-10-02T00:00:00Z')
        overlap=self.dated_project('overlap',True,'2026-10-04T00:00:00Z')
        late=self.dated_project('late',False)
        with patch('herzchen.kernel.store._now',return_value='2026-10-06T00:00:00Z'):
            self.graph.set_lifecycle(late.ref,'active',logical_request_key='late-activate')
        g=ProjectHistoryGrant(self.actor,(ended.id,overlap.id,late.id),'test','interval')
        r=self.store.project_history_reader(grant=g);p=r.read(active_during=('2026-10-03T00:00:00Z','2026-10-05T00:00:00Z'))
        self.assertEqual({v['id']for v in p['matched_projects']},{overlap.id});self.assertTrue(p['coverage']['active_discovery_complete'])
        self.assertLessEqual(p['coverage']['active_candidates_examined'],len(g.project_ids)*3 if hasattr(g,'project_ids') else 9)
    def test_state_carry_in_exclusive_end_late_facts_and_overview_completion(self):
        with patch('herzchen.kernel.store._now',return_value='2026-10-01T00:00:00Z'):
            a=self.graph.create_task(self.project.ref,title='carry',logical_request_key='carry');a=self.graph.revise(a,lifecycle='active',logical_request_key='carry-active')
            b=self.graph.create_task(self.project.ref,title='other',logical_request_key='other')
        kw=dict(projects=[self.project.ref],from_at='2026-10-03T00:00:00Z',to_at='2026-10-05T00:00:00Z',limit=1)
        v=ObservabilityViews(self.reader);p=v.read('overview',**kw);fixed=p['snapshot'];seen=[];pages=0
        for _ in range(10):
            seen.extend(x['subject_ref']['id'] for x in p['historical_state']['rows']);pages+=1
            if not p['continuation']['next_cursor']:break
            p=v.read('overview',snapshot=fixed,cursor=p['continuation']['next_cursor'],**kw)
        self.assertLess(pages,10);self.assertIn(a.id,seen);self.assertEqual(len(seen),len(set(seen)))
        with patch('herzchen.kernel.store._now',return_value='2026-10-05T00:00:00Z'):
            self.graph.revise(a,lifecycle='completed',logical_request_key='at-exclusive-end')
        p=self.reader.read_state(projects=[self.project.ref],from_at=kw['from_at'],to_at=kw['to_at'],limit=20)
        carry=next(x for x in p['rows']if x['subject_ref']['id']==a.id);self.assertEqual(carry['summary']['after']['fields']['lifecycle'],'active')
        self.assertEqual(carry['state_as_of_before'],'2026-10-05T00:00:00.000000Z');self.assertGreater(p['io_work']['summary_bytes_hydrated'],0)
        with patch('herzchen.kernel.store._now',return_value='2026-10-04T00:00:00Z'):
            self.graph.revise(b,lifecycle='active',logical_request_key='late-recorded-fact')
        old=self.reader.read_state(projects=[self.project.ref],from_at=kw['from_at'],to_at=kw['to_at'],snapshot=fixed,limit=20)
        br=next(x for x in old['rows']if x['subject_ref']['id']==b.id);self.assertEqual(br['summary']['after']['fields']['lifecycle'],'pending')

    def test_large_negative_activity_discovery_advances_boundedly(self):
        self._activity_discovery_fixture(False)
    def test_activity_beyond_first_budget_is_not_silently_excluded(self):
        self._activity_discovery_fixture(True)
    def _activity_discovery_fixture(self, late_active):
        template=list(self.store.connection.execute("SELECT * FROM project_history WHERE subject_kind='work.project' AND subject_id=? LIMIT 1",(self.project.id,)).fetchone())
        with self.store.transaction() as tx:
            tx.execute('DELETE FROM project_history')
            for i in range(5002):
                row=list(template);row[1]='discovery-'+str(i);row[3]=i
                row[13]='2026-10-01T00:00:00.000000Z' if i==0 else '2026-10-04T00:00:00.000000Z'
                status='active' if late_active and i==5001 else 'pending'
                row[18]=json.dumps({'before':{'exists':True,'fields':{'lifecycle':'pending'}},'after':{'fields':{'lifecycle':status}},'coverage':'captured'})
                tx.execute('INSERT INTO project_history VALUES('+','.join('?' for _ in row)+')',row)
        evaluations=[]
        self.store.connection.create_function('json_extract',2,lambda *_:evaluations.append(1))
        kwargs=dict(projects=[self.project.ref],active_during=('2026-10-03T00:00:00Z','2026-10-05T00:00:00Z'),limit=1)
        page=self.reader.read(**kwargs);snapshot=page['snapshot'];examined=[];cursors=[]
        for _ in range(10):
            examined.append(page['coverage']['active_candidates_examined'])
            self.assertLessEqual(examined[-1],1000)
            self.assertLessEqual(page['io_work']['metadata_candidates_examined'],1000)
            if page['coverage']['active_discovery_complete']:break
            self.assertTrue(page['partial']);self.assertFalse(page['rows']);self.assertTrue(page['next_cursor'])
            self.assertGreater(page['coverage']['active_summary_bytes_hydrated'],0)
            cursors.append(page['next_cursor'])
            page=self.reader.read(snapshot=snapshot,cursor=page['next_cursor'],**kwargs)
        else:self.fail('discovery did not finish its exact snapshot')
        self.assertGreater(len(cursors),1);self.assertEqual(len(cursors),len(set(cursors)))
        self.assertEqual(sum(examined),5002);self.assertEqual(evaluations,[])
        self.assertEqual({x['id'] for x in page['matched_projects']},{self.project.id} if late_active else set())
        if late_active:
            more=self.reader.read(snapshot=snapshot,cursor=page['next_cursor'],**kwargs)
            self.assertTrue(more['coverage']['active_discovery_complete'])
            self.assertEqual(more['coverage']['active_candidates_examined'],0)
            self.assertNotEqual(more['rows'][0]['facet_id'],page['rows'][0]['facet_id'])
        # The subject path follows discovery with its own continuation mode.
        state=self.reader.read_state(**kwargs)
        for _ in range(10):
            self.assertLessEqual(state['io_work']['metadata_candidates_examined'],1000)
            if state['coverage']['active_discovery_complete']:break
            self.assertFalse(state['rows']);state=self.reader.read_state(snapshot=state['snapshot'],cursor=state['next_cursor'],**kwargs)
        self.assertTrue(state['coverage']['active_discovery_complete'])
        self.assertEqual(bool(state['rows']),late_active)
    def test_exact_carry_in_detail_and_older_filtered_terminal_negatives(self):
        from herzchen.kernel.project_history import AuthorizationError
        with patch('herzchen.kernel.store._now',return_value='2026-10-01T00:00:00Z'):
            task=self.graph.create_task(self.project.ref,title='carry-detail',logical_request_key='carry-detail')
            task=self.graph.revise(task,lifecycle='active',logical_request_key='carry-detail-active')
            closed=self.graph.create_task(self.project.ref,title='closed-detail',logical_request_key='closed-detail')
            closed=self.graph.revise(closed,lifecycle='completed',logical_request_key='closed-detail-end')
        kw=dict(projects=[self.project.ref],from_at='2026-10-03T00:00:00Z',to_at='2026-10-05T00:00:00Z')
        page=self.reader.read_state(**kw);carry=next(x for x in page['rows'] if x['subject_ref']['id']==task.id)
        detail=self.reader.detail(carry['facet_id'],snapshot=page['snapshot']);self.assertEqual(detail['facet_id'],carry['facet_id'])
        older=self.store.connection.execute('SELECT facet_id FROM project_history WHERE subject_id=? AND facet_id<>? ORDER BY recorded_at LIMIT 1',(task.id,carry['facet_id'])).fetchone()[0]
        terminal=self.store.connection.execute('SELECT facet_id FROM project_history WHERE subject_id=? ORDER BY source_append_position DESC LIMIT 1',(closed.id,)).fetchone()[0]
        for facet in (older,terminal):
            with self.assertRaises(AuthorizationError):self.reader.detail(facet,snapshot=page['snapshot'])
        filtered=self.reader.read_state(filters={'facet_type':'never'},**kw)
        with self.assertRaises(AuthorizationError):self.reader.detail(carry['facet_id'],snapshot=filtered['snapshot'])
        with patch('herzchen.kernel.store._now',return_value='2026-10-04T00:00:00Z'):
            self.graph.revise(task,lifecycle='completed',logical_request_key='carry-detail-late')
        self.assertEqual(self.reader.detail(carry['facet_id'],snapshot=page['snapshot'])['facet_id'],carry['facet_id'])
        current=self.reader.read_state(**kw)
        with self.assertRaises(AuthorizationError):self.reader.detail(carry['facet_id'],snapshot=current['snapshot'])

class ManifestCorrectionTests(unittest.TestCase):
    setUp=_HistoryFixture.setUp
    evidence=_HistoryFixture.evidence
    def make_manifest(self):
        handler=self.evidence();batch=ProjectBatches(self.store,actor=self.actor).apply_project_sheet(self.project,{'tasks':[{'id':str(i),'title':str(i)}for i in range(130)]},logical_request_key='manifest')
        return handler,batch
    def test_manifest_facet_continuation_survives_reopen_and_hidden_until_complete(self):
        handler,batch=self.make_manifest();seen=[]
        def read(ref,offset,maximum):
            result=handler.read_evidence(ResourceRef.from_dict(ref),actor=self.actor,offset=offset,max_bytes=maximum);seen.append((offset,len(result['bytes'])));return result
        projection=ProjectHistoryProjection(self.store,manifest_reader=read,default_batch=1)
        prior=projection.status()['checkpoint'];p=projection.maintain(limit=1,raise_on_error=True)
        # One earlier project source may advance before the manifest position.
        while not p.get('facet_continuation') and p['lag']:
            p=projection.maintain(limit=1,raise_on_error=True)
        self.assertTrue(p['facet_continuation']);position=p['facet_continuation']['binding']['position'];self.assertLess(p['checkpoint'],position)
        g=ProjectHistoryGrant(self.actor,(self.project.id,),'test','manifest');r=self.store.project_history_reader(grant=g)
        self.assertFalse(any(x['source_append_position']==position for x in r.read(limit=200)['rows']))
        resumed=ProjectHistoryProjection(self.store,manifest_reader=read,default_batch=1);steps=0
        while p['lag']:
            p=resumed.maintain(limit=1,raise_on_error=True);steps+=1;self.assertLess(steps,1000)
            if p.get('manifest_io'):self.assertLessEqual(p['manifest_io']['range_bytes_read'],4096)
        self.assertTrue(all(n<=4096 for _,n in seen));self.assertGreater(steps,100)
        ids=self.store.connection.execute('SELECT COUNT(DISTINCT facet_index) FROM project_history WHERE source_append_position=?',(position,)).fetchone()[0];self.assertEqual(ids,131)
        rebuilt=resumed.rebuild(batch_size=2);self.assertEqual(rebuilt['outcome'],'switched')
    def test_split_unicode_long_record_digest_and_nonprogress_reject(self):
        data=(json.dumps({'padding':'é'*5000},ensure_ascii=False)+'\n').encode();m={'ref':{'authority':'owner','kind':'dat.content.revision','id':'manifest','revision':'rev-1'},'facet_count':1,'byte_digest':hashlib.sha256(data).hexdigest()}
        def read(ref,offset,bound):
            end=min(len(data),offset+bound);return {'bytes':data[offset:end],'next_offset':end if end<len(data)else None}
        p=ProjectHistoryProjection(self.store,manifest_reader=read);self.assertEqual(list(p._manifest_facets({}, {'manifest':m})),[{'padding':'é'*5000}])
        wrong=dict(m,byte_digest='0'*64)
        with self.assertRaises(ProjectionMaintenanceError):list(p._manifest_facets({}, {'manifest':wrong}))
        p.manifest_reader=lambda *_:{'bytes':b'x','next_offset':500}
        with self.assertRaises(ProjectionMaintenanceError):list(p._manifest_facets({}, {'manifest':m}))
