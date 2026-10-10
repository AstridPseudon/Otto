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
        'task_ref': ref('work.task', 'task')}
    return {'schema': FACT_SCHEMA, 'ref': ref('wrk.report', str(pos)), 'observation': stream.observations[0],
        'association': association, 'append_position': pos, 'recorded_at': '2026-10-08T00:00:00Z',
        'first_qualified_recorded_at': '2026-10-05T23:59:00Z', 'first_qualified_provenance': {'parser': 'fixed-v1'},
        'execution_time': '2026-10-04T22:00:00Z', 'supersedes_ref': None}


class AccountingTests(unittest.TestCase):
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
        self.assertEqual(shared['groups'], {'project': [], 'task': [], 'agent': []})
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
