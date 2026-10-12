"""Reusable physical-span, exclusion and historical-attribution contract."""
from copy import deepcopy
import json
import unittest

from otto.agents.usage_accounting import account_usage, FACT_SCHEMA
from otto.agents.usage_capture import UsageStream, digest
from tests.test_usage_capture import native


def ref(kind, name): return {'authority': 'owner', 'kind': kind, 'id': name, 'revision': 'rev-1'}


def fact(adapter='codex-direct', *, pos=1, turn='turn', project='project', generation=1, metrics=None):
    stream = UsageStream(adapter)
    for e in native(adapter, {'input_tokens': 10, 'output_tokens': 5} if metrics is None else metrics, turn=turn):
        stream.feed(json.dumps(e))
    association = {'assignment_ref': ref('wrk.assignment', 'historical'), 'generation': generation,
        'principal': 'old-worker', 'agent': 'old-agent', 'project_ref': ref('work.project', project),
        'task_ref': ref('work.task', 'task'), 'role': 'worker'}
    return {'schema': FACT_SCHEMA, 'ref': ref('wrk.report', str(pos)), 'observation': stream.observations[0],
        'association': association, 'append_position': pos, 'recorded_at': '2026-10-08T00:00:00Z',
        'first_qualified_recorded_at': '2026-10-05T23:59:00Z', 'first_qualified_provenance': {'parser': 'fixed-v1'},
        'execution_time': '2026-10-04T22:00:00Z', 'supersedes_ref': None}


class AccountingTests(unittest.TestCase):
    def test_money_alias_conflict_population_and_qualified_separate_span(self):
        for adapter in ('codex-direct', 'codex-host', 'claude-code'):
            with self.subTest(adapter=adapter):
                a=fact(adapter);a['provider_reported_money']={'amount':'1','currency':'USD','status':'usage_report_estimate'}
                alias=deepcopy(a);alias['ref']=ref('wrk.report','alias');alias['append_position']=2
                alias['provider_reported_money']['source']={'kind':'native-client-estimate','carrier':'different'}
                q=self.query([a,alias]);self.assertEqual(q['provider_reported']['amount'],'1');self.assertEqual(q['provider_reported']['span_count'],1)
                alias['provider_reported_money']['amount']='2'
                q=self.query([a,alias]);self.assertIsNone(q['provider_reported']['amount']);self.assertEqual(q['provider_reported']['span_count'],0)
                self.assertEqual(q['spans'][0]['provider_reported_money']['reason'],'provider-money-conflict')
                self.assertEqual(len(q['spans'][0]['provider_reported_money']['observations']),2)
                child=fact(adapter,pos=3,turn='separate');child['provider_reported_money']={'amount':'3','currency':'USD','status':'usage_report_estimate'}
                self.assertEqual(self.query([a,alias,child])['provider_reported']['amount'],'3')
                for population in ('cumulative','includes-descendants'):
                    excluded=deepcopy(a)
                    if population=='cumulative':
                        excluded['observation']['identity']['metric_scope']='cumulative'
                        excluded['observation']['identity']['span_id']='usage-span-'+digest({k:v for k,v in excluded['observation']['identity'].items()if k!='span_id'})
                        excluded['observation']['usage']['scope']='cumulative'
                    else:excluded['observation']['population_scope']=population
                    q=self.query([excluded,child]);self.assertEqual(q['provider_reported']['amount'],'3');self.assertEqual(q['provider_reported']['span_count'],1)
                    self.assertTrue(q['coverage']['monetary']['provider_money_exclusion_reasons'])

    def test_money_semantic_decimal_aliases_and_actual_native_population(self):
        for adapter in ('codex-direct','codex-host','claude-code'):
            for left,right in (('1','1.0'),('0','0.0'),('1.25','1.2500'),('100','1E+2'),
                ('0.123456789012345678901234567891','0.1234567890123456789012345678910')):
                a=fact(adapter);a['provider_reported_money']={'amount':left,'currency':'USD','status':'usage_report_estimate'}
                b=deepcopy(a);b['ref']=ref('wrk.report','alias');b['append_position']=2;b['provider_reported_money']['amount']=right
                q=self.query([a,b]);self.assertEqual(q['spans'][0]['state'],'measured');self.assertEqual(q['provider_reported']['span_count'],1)
                self.assertIsNotNone(q['metrics'])
                self.assertEqual(self.public_fold([a,b])['provider_reported']['span_count'],1)
        for left,right in (('0.123456789012345678901234567891','0.123456789012345678901234567892'),('1','2')):
            a=fact();a['provider_reported_money']={'amount':left,'currency':'USD','status':'usage_report_estimate'}
            b=deepcopy(a);b['ref']=ref('wrk.report','alias');b['append_position']=2;b['provider_reported_money']['amount']=right
            q=self.query([a,b]);self.assertEqual(q['spans'][0]['state'],'provider-money-conflict');self.assertIsNone(q['provider_reported']['amount'])
        a=fact();a['provider_reported_money']={'amount':'1','currency':'USD','status':'billed','receipt_ref':ref('billing.receipt','a')}
        b=deepcopy(a);b['ref']=ref('wrk.report','alias');b['append_position']=2;b['provider_reported_money']['receipt_ref']=ref('billing.receipt','b')
        self.assertEqual(self.query([a,b])['spans'][0]['state'],'provider-money-conflict')
        for left,right in ((0,0.0),(1,1.0),(1.25,1.2500)):
            stream=UsageStream('claude-code')
            for cost in(left,right):
                for event in native('claude-code',{'input_tokens':10,'output_tokens':2}):
                    if event['type']=='result':event['total_cost_usd']=cost
                    stream.feed(json.dumps(event))
            facts=[]
            for index,o in enumerate(stream.observations):
                f=fact('claude-code',pos=index+1);f['observation']=o;facts.append(f)
            q=self.query(facts);self.assertEqual(q['metrics']['input_tokens'],10)
            self.assertEqual(q['provider_reported']['span_count'],0);self.assertIsNone(q['provider_reported']['amount'])
            self.assertEqual(q['spans'][0]['provider_reported_money']['reason'],'provider-money-cumulative-not-additive')
            public=self.public_fold(facts);self.assertEqual(public['metrics']['input_tokens'],10)
            self.assertIsNone(public['provider_reported']['amount']);self.assertEqual(public['spans'][0]['state'],'measured')

    def public_fold(self,facts):
        from otto.portfolio.observability_views import _fold_retained_usage
        rows=[{'subject_ref':f['ref'],'source_append_position':f['append_position'],'recorded_at':f['recorded_at'],'summary':{'after':{'fields':{'usage_fact':f}}}}for f in facts]
        result={'snapshot':{'boundary':100},'projects':[ref('work.project','project')]}
        return _fold_retained_usage(rows,result,complete=True)[0]

    def test_receipt_billed_zero_missing_and_malformed_money_remain_distinct(self):
        for raw,status,amount in (({'amount':'0','currency':'USD','status':'zero'},'zero','0'),
            (None,'missing',None),({'amount':'bad','currency':'USD'},'unavailable',None),
            ({'amount':'1','currency':None},'unavailable',None),
            ({'amount':'1','currency':'not-currency'},'unavailable',None),({},'unavailable',None),
            ({'amount':'1','currency':'USD','status':'billed'},'unavailable',None),
            ({'amount':'1','currency':'USD','status':'billed','receipt_ref':ref('billing.receipt','receipt')},'billed','1')):
            with self.subTest(raw=raw):
                f=fact();f['provider_reported_money']=raw;q=self.query([f]);m=q['spans'][0]['provider_reported_money']
                self.assertEqual(m['status'],status);self.assertEqual(m.get('amount'),amount)
                self.assertEqual(q['provider_reported']['amount'],amount)

    def test_native_cache_partition_pricing_codex_and_claude_are_distinct(self):
        for adapter in ('codex-direct','codex-host','claude-code'):
            with self.subTest(adapter=adapter):
                metrics={'input_tokens':100,'output_tokens':30,'reasoning_output_tokens':10}
                if adapter.startswith('codex'):metrics['cached_input_tokens']=20
                else:metrics.update(cache_read_input_tokens=20,cache_creation_input_tokens=5)
                value=fact(adapter,metrics=metrics);value['execution_time']='2026-10-04T22:00:00Z';value['observation']['observed']['model']='gpt-5.6-luna' if adapter.startswith('codex') else 'claude-sonnet-4-5'
                result=self.query([value]);price=result['spans'][0]['price_estimate']
                self.assertEqual(price['status'],'estimated');self.assertEqual(price['components']['input_tokens'],'0.00024000' if adapter.startswith('codex') else '0.00030000')
                self.assertEqual(price['components']['cached_input_tokens'],'0.00000600');self.assertEqual(price['components']['output_tokens'],'0.00045000');self.assertNotIn('reasoning_output_tokens',price['components'])
                self.assertEqual(price['amount'],'0.00069600' if adapter.startswith('codex') else '0.00077475')
                self.assertEqual(result['metrics']['input_tokens'],100) # preserve raw provider metrics

    def test_missing_invalid_and_zero_codex_cache_partition_are_not_inferred(self):
        for cached,expected in ((None,'unavailable'),(101,'unavailable'),(False,'unavailable'),(0,'estimated'),(100,'estimated')):
            with self.subTest(cached=cached):
                value=fact('codex-host',metrics={'input_tokens':100,'output_tokens':0});value['observation']['observed']['model']='gpt-5.6-luna'
                if cached is not None:value['observation']['usage']['metrics']['cached_input_tokens']=cached
                if cached is False:
                    with self.assertRaises(ValueError):self.query([value])
                    continue
                price=self.query([value])['spans'][0]['price_estimate'];self.assertEqual(price['status'],expected)
                if expected=='unavailable':self.assertIsNone(price['amount'])
                else:self.assertEqual(price['components']['input_tokens'],'0.00030000' if cached==0 else '0.00000000')

    def query(self, facts, projects=('project',), as_of=100, **kwargs):
        return account_usage(facts, as_of=as_of, authorized_projects=[ref('work.project', p) for p in projects], **kwargs)

    def test_parameterized_alias_richer_conflict_and_historical_generation(self):
        for adapter in ('codex-direct','codex-host','claude-code'):
            with self.subTest(adapter=adapter):
                a = fact(adapter); b = deepcopy(a); b['ref'] = ref('wrk.report','alias'); b['append_position'] = 2
                b['observation']['usage']['metrics']['cached_input_tokens'] = 3
                q = self.query([a,b]); self.assertEqual(len(q['spans']),1)
                self.assertEqual(q['metrics'], {'input_tokens': 10, 'output_tokens': 5, 'cached_input_tokens': 3})
                self.assertEqual(q['groups']['agent'][0]['identity'][1], 1)
                b['observation']['usage']['metrics']['input_tokens'] = 11
                self.assertIsNone(self.query([a,b])['metrics'])
                self.assertEqual(self.query([a,b])['spans'][0]['state'],'conflict')
        self.assertEqual(len(self.query([fact('codex-direct'),fact('codex-host',pos=2)])['spans']),1)
        self.assertEqual(len(self.query([fact('codex-direct'),fact('claude-code',pos=2)])['spans']),2)

    def test_shared_once_and_partial_grant_does_not_leak(self):
        a = fact(); b = fact(pos=2, project='secret-project')
        b['association']['task_ref'] = ref('work.task','secret-task')
        b['association']['assignment_ref'] = ref('wrk.assignment','secret-agent')
        shared = self.query([a,b], projects=('project','secret-project'))
        self.assertEqual(shared['metrics']['input_tokens'],10)
        self.assertEqual(shared['groups'], {'project': [], 'task': [], 'role': [], 'agent': []})
        denied = self.query([a,b])
        self.assertEqual(denied['spans'],[]); self.assertIsNone(denied['metrics'])
        self.assertNotIn('secret',json.dumps(denied)); self.assertEqual(denied['coverage']['limited'],1)

    def test_cumulative_parent_child_and_unknown_population_exclusions(self):
        for adapter in ('codex-direct','codex-host','claude-code'):
            a = fact(adapter); a['observation']['identity']['metric_scope'] = 'cumulative'
            a['observation']['identity']['span_id'] = 'usage-span-' + digest({k:v for k,v in a['observation']['identity'].items() if k != 'span_id'})
            a['observation']['usage']['scope'] = 'cumulative'
            q = self.query([a]); self.assertIsNone(q['metrics']); self.assertEqual(q['spans'][0]['state'],'cumulative-not-additive')
            parent = fact(adapter); parent['observation']['population_scope'] = 'includes-descendants'
            child = fact(adapter,pos=2,turn='child',metrics={'input_tokens': 2})
            child['association']['parent'] = parent['association']
            q = self.query([parent, child]); self.assertEqual(q['metrics']['input_tokens'],2)
            self.assertEqual(q['spans'][0]['state'] if q['spans'][0]['state'] != 'measured' else q['spans'][1]['state'], 'parent-child-scope-unproven')
            parent['observation']['population_scope'] = 'self'
            self.assertEqual(self.query([parent,child])['metrics']['input_tokens'],12)

    def test_unknown_missing_zero_and_initializer_alternate_views(self):
        missing = fact(); missing['first_qualified_recorded_at'] = None
        missing['observation']['usage'].update(state='missing',metrics=None)
        q = self.query([missing]); self.assertIsNone(q['metrics']); self.assertEqual(q['coverage']['missing_or_invalid_observations'],1)
        zero = fact(metrics={'input_tokens':0}); self.assertEqual(self.query([zero])['metrics'],{'input_tokens':0})
        zero['association']['generation'] = None
        q = self.query([zero]); self.assertIsNone(q['metrics']); self.assertEqual(q['spans'][0]['state'],'attribution-unknown')
        init = fact(); init['association']['task_ref'] = None; init['observation']['phase'] = 'initializer'
        q = self.query([init]); self.assertEqual(q['groups']['task'],[]); self.assertEqual(q['groups']['project'][0]['metrics']['input_tokens'],10)
        init['association']['task_ref'] = ref('work.task','explicit-initializer-task')
        self.assertEqual(len(self.query([init])['groups']['task']),1)

    def test_branching_correction_and_boundary_old_snapshot(self):
        a = fact(); b = fact(pos=2, metrics={'input_tokens':20}); b['supersedes_ref'] = a['ref']
        c = fact(pos=3, metrics={'input_tokens':30}); c['supersedes_ref'] = a['ref']
        self.assertEqual(self.query([a,b,c],as_of=1)['metrics']['input_tokens'],10)
        self.assertEqual(self.query([a,b,c],as_of=2)['metrics']['input_tokens'],20)
        self.assertIsNone(self.query([a,b,c],as_of=3)['metrics'])
        with self.assertRaises(ValueError): self.query([b])
        q = self.query([a,b,c],as_of=1,from_at='2026-10-05T00:00:00Z',to_at='2026-10-06T00:00:00Z')
        self.assertEqual(q['metrics']['input_tokens'],10)
        self.assertEqual(q['coverage']['totals'],'page-only')
        q = self.query([a,b],from_at='2026-10-08T00:00:00Z',to_at='2026-10-09T00:00:00Z')
        self.assertIsNone(q['metrics'])

    def test_spoofed_namespace_boolean_and_metric_state_rejected(self):
        for mutate in (lambda f: f['observation']['identity'].update(namespace='foreign'),
                lambda f: f['observation']['usage']['metrics'].update(input_tokens=True)):
            f = fact(); mutate(f)
            with self.assertRaises(ValueError): self.query([f])

if __name__ == '__main__': unittest.main()
