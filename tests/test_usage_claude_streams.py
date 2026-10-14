"""Claude Code usage in Codex's Usage model: additive cache, per-model, native cost."""
from copy import deepcopy
from decimal import Decimal
import json
import pathlib
import unittest

from herzchen.usage.accounting import FACT_SCHEMA, account_usage, estimate_span_cost, qualified_observation
from herzchen.usage.capture import UsageStream
from herzchen.usage.contract import RATE_SCHEDULE

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "claude-streams"
FIELDS = {"input_tokens": "input_tokens", "cache_creation_input_tokens": "cache_creation_input_tokens",
          "cached_input_tokens": "cache_read_input_tokens", "output_tokens": "output_tokens"}


def ref(kind, name): return {"authority": "owner", "kind": kind, "id": name, "revision": "rev-1"}


def events(name):
    return [json.loads(line) for line in (FIXTURES / (name + ".jsonl")).read_text().splitlines()]


def observe(name, phase="work", mutate=None):
    stream = UsageStream("claude-code", phase=phase)
    for event in events(name):
        if mutate:
            mutate(event)
        stream.feed(json.dumps(event))
    return stream.observations[0]


def fact(observation, pos, role="manager"):
    return {"schema": FACT_SCHEMA, "ref": ref("wrk.report", "r%d" % pos), "observation": observation,
        "association": {"assignment_ref": ref("wrk.assignment", "a"), "generation": 1, "principal": "p",
            "agent": "agent", "project_ref": ref("work.project", "project"),
            "task_ref": None if observation["phase"] == "initializer" else ref("work.task", "task"), "role": role},
        "append_position": pos, "recorded_at": "2026-10-08T00:00:00Z",
        "first_qualified_recorded_at": "2026-10-05T23:59:00Z", "first_qualified_provenance": {"parser": "v1"},
        "execution_time": "2026-10-04T22:00:00Z", "supersedes_ref": None}


def account(facts):
    return account_usage(facts, as_of=100, authorized_projects=[ref("work.project", "project")], complete=True)


SET = (("haiku-initializer", "initializer"), ("haiku-work", "work"), ("sonnet-work", "work"),
       ("two-models-work", "work"), ("no-cost-work", "work"))


def native_totals(names):
    """Sum the numbers Claude itself reported, straight from the recorded result events."""
    tokens = {k: 0 for k in FIELDS}; cost = Decimal("0")
    for name in names:
        result = [e for e in events(name) if e["type"] == "result"][0]
        for canonical, native in FIELDS.items():
            tokens[canonical] += result["usage"][native]
        if "total_cost_usd" in result:
            cost += Decimal(str(result["total_cost_usd"]))
    return tokens, cost


class ClaudeCaptureTests(unittest.TestCase):
    def test_four_counts_stay_separate_and_additive_with_native_cost(self):
        o = observe("haiku-initializer", "initializer")
        self.assertEqual(o["phase"], "initializer")
        self.assertEqual(o["usage"]["metrics"], {"input_tokens": 4, "cached_input_tokens": 13024,
            "cache_creation_input_tokens": 1210, "output_tokens": 6})
        self.assertEqual(o["observed"]["model"], "claude-haiku-5-5")
        money = o["provider_reported_money"]
        self.assertEqual((money["status"], money["amount"], money["currency"]), ("usage_report_estimate", "0.0016895", "USD"))
        self.assertEqual(money["source"]["kind"], "native-reported")
        self.assertEqual((money["metric_scope"], money["population_scope"]), ("invocation", "self"))
        self.assertEqual(o["model_usage"]["models"][0]["metrics"], o["usage"]["metrics"])
        self.assertEqual(o["model_usage"]["reconciliation"], "equal")

    def test_two_models_keep_per_model_facts_and_no_single_span_model(self):
        o = observe("two-models-work")
        self.assertEqual([m["model"] for m in o["model_usage"]["models"]], ["claude-haiku-5-5", "claude-sonnet-5-5"])
        self.assertIsNone(o["observed"]["model"])
        self.assertEqual(o["usage"]["metrics"]["cached_input_tokens"], 30000)
        self.assertEqual(o["provider_reported_money"]["amount"], "0.0224")

    def test_missing_native_cost_is_missing_not_guessed(self):
        o = observe("no-cost-work")
        self.assertEqual(o["provider_reported_money"]["status"], "missing")
        self.assertIsNone(o["provider_reported_money"]["amount"])
        self.assertEqual(o["model_usage"]["models"][0]["cost"], None)

    def test_cost_derived_only_from_complete_per_model_native_costs(self):
        def drop_total(e):
            if e["type"] == "result":
                e.pop("total_cost_usd")
        money = observe("two-models-work", mutate=drop_total)["provider_reported_money"]
        self.assertEqual((money["status"], money["amount"], money["source"]["field"]),
                         ("usage_report_estimate", "0.0224", "modelUsage.costUSD"))

    def test_cost_total_disagreeing_with_models_is_unavailable(self):
        def skew(e):
            if e["type"] == "result":
                e["total_cost_usd"] = 0.5
        money = observe("two-models-work", mutate=skew)["provider_reported_money"]
        self.assertEqual(money["status"], "unavailable")
        self.assertIsNone(money["amount"])

    def test_top_level_difference_is_recorded_and_model_usage_is_the_aggregate(self):
        def skew(e):
            if e["type"] == "result":
                e["usage"]["output_tokens"] = 1
        o = observe("sonnet-work", mutate=skew)
        self.assertEqual(o["usage"]["metrics"]["output_tokens"], 800)
        self.assertEqual(o["model_usage"]["reconciliation"], "differs")
        self.assertEqual(o["model_usage"]["top_level_metrics"]["output_tokens"], 1)

    def test_malformed_model_usage_falls_back_to_top_level_and_conservative_money(self):
        def break_it(e):
            if e["type"] == "result":
                e["modelUsage"]["claude-sonnet-5-5"]["inputTokens"] = True
        o = observe("sonnet-work", mutate=break_it)
        self.assertEqual(o["model_usage"]["state"], "invalid")
        self.assertEqual(o["usage"]["metrics"]["input_tokens"], 12)
        self.assertEqual(o["provider_reported_money"]["metric_scope"], "cumulative")

    def test_bare_total_cost_without_model_usage_keeps_cumulative_reading(self):
        def strip(e):
            if e["type"] == "result":
                e.pop("modelUsage")
        o = observe("sonnet-work", mutate=strip)
        self.assertNotIn("model_usage", o)
        self.assertEqual(o["provider_reported_money"]["metric_scope"], "cumulative")
        self.assertEqual(o["provider_reported_money"]["source"]["kind"], "native-client-estimate")


class ClaudeAccountingTests(unittest.TestCase):
    def facts(self, names=SET):
        return [fact(observe(n, p), i + 1, role="manager" if "haiku" in n else "worker") for i, (n, p) in enumerate(names)]

    def public(self, facts):
        from otto.portfolio.observability_views import _fold_retained_usage
        rows = [{"subject_ref": f["ref"], "source_append_position": f["append_position"], "recorded_at": f["recorded_at"],
                 "summary": {"after": {"fields": {"usage_fact": f}}}} for f in facts]
        return _fold_retained_usage(rows, {"snapshot": {"boundary": 100}, "projects": [ref("work.project", "project")]},
                                    complete=True)[0]

    def test_view_totals_equal_sum_of_claude_reported_numbers(self):
        tokens, _ = native_totals([n for n, _ in SET])
        _, cost = native_totals([n for n, _ in SET if n != "no-cost-work"])
        for result in (account(self.facts()), self.public(self.facts())):
            self.assertEqual(result["metrics"], tokens)
            self.assertEqual(result["provider_reported"]["currency"], "USD")
            self.assertEqual(Decimal(result["provider_reported"]["amount"]), cost)
            self.assertEqual(result["provider_reported"]["span_count"], 4)
            self.assertEqual(result["provider_reported"]["missing_spans"], 1)  # unreported stays unreported, not zero
            self.assertEqual(result["exclusions"], [{"span_id": result["exclusions"][0]["span_id"],
                "group": "task", "reason": "initializer-or-attribution-unknown"}])

    def test_total_input_is_the_sum_never_a_partition(self):
        m = account(self.facts([("haiku-initializer", "initializer")]))["metrics"]
        self.assertEqual(m["input_tokens"] + m["cached_input_tokens"] + m["cache_creation_input_tokens"], 4 + 13024 + 1210)

    def test_per_model_view_matches_modelusage_and_costs(self):
        result = account(self.facts())
        by = {g["identity"]: g for g in result["by_model"]}
        self.assertEqual(set(by), {"claude-haiku-5-5", "claude-sonnet-5-5"})
        sonnet = by["claude-sonnet-5-5"]
        self.assertEqual(sonnet["span_count"], 2)  # sonnet turn + share of the two-model turn
        self.assertEqual(sonnet["metrics"]["cache_creation_input_tokens"], 2400 + 1500)
        self.assertEqual(Decimal(sonnet["provider_reported"]["amount"]), Decimal("0.0252") + Decimal("0.0205"))
        haiku = by["claude-haiku-5-5"]
        self.assertEqual(haiku["metrics"]["cached_input_tokens"], 13024 + 14234 + 5000 + 1000)
        self.assertEqual(haiku["roles"], ["manager", "worker"])
        self.assertEqual(Decimal(haiku["provider_reported"]["amount"]), Decimal("0.0016895") + Decimal("0.0021") + Decimal("0.0019"))
        # Per role and model include initializer overhead; per task explicitly
        # excludes that project-only phase instead of silently attributing it.
        by_role = {g["identity"]: g for g in result["groups"]["role"]}
        self.assertEqual(set(by_role), {"manager", "worker"})
        self.assertEqual(sum(g["metrics"]["output_tokens"] for g in by_role.values()), result["metrics"]["output_tokens"])
        self.assertEqual(Decimal(by_role["manager"]["provider_reported"]["amount"]), Decimal("0.0037895"))
        self.assertEqual(Decimal(by_role["worker"]["provider_reported"]["amount"]), Decimal("0.0476"))
        self.assertEqual(by_role["worker"]["provider_reported"]["missing_spans"], 1)
        by_task = result["groups"]["task"][0]
        self.assertEqual(Decimal(by_task["provider_reported"]["amount"]), Decimal("0.0497"))
        self.assertEqual(by_task["provider_reported"]["missing_spans"], 1)
        self.assertEqual(by_task["metrics"]["output_tokens"], result["metrics"]["output_tokens"] - 6)
        # Per project remains an alternate view of the same physical spans.
        self.assertEqual(sum(g["metrics"]["output_tokens"] for g in result["groups"]["project"]), result["metrics"]["output_tokens"])

    def test_partial_then_complete_duplicate_counts_the_claude_span_once(self):
        stream = UsageStream("claude-code", phase="work")
        native = events("haiku-work")
        for event in native[:-1]:
            stream.feed(json.dumps(event))
        partial = deepcopy(native[-1]); partial["usage_complete"] = False
        stream.feed(json.dumps(partial))
        stream.feed(json.dumps(native[-1]))
        stream.feed(json.dumps(native[-1]))
        self.assertEqual([o["usage"]["state"] for o in stream.observations], ["partial", "observed"])
        partial_fact = fact(stream.observations[0], 1)
        partial_fact["first_qualified_recorded_at"] = None
        complete_fact = fact(stream.observations[1], 2)
        result = account([partial_fact, complete_fact])
        self.assertEqual(result["metrics"], stream.observations[1]["usage"]["metrics"])
        self.assertEqual(result["provider_reported"]["span_count"], 1)

    def test_estimates_stay_unavailable_without_adopted_price_for_claude_models(self):
        spans = account(self.facts())["spans"]
        self.assertTrue(all(s["price_estimate"]["status"] == "unavailable" for s in spans))
        self.assertEqual({s["price_estimate"]["reason"] for s in spans}, {"missing-model-or-rate"})

    def schedule(self):
        schedule = deepcopy(RATE_SCHEDULE)  # test-only illustrative rates, not an adopted policy
        for model, rate in (("claude-haiku-5-5", "0.000001"), ("claude-sonnet-5-5", "0.000003")):
            r = Decimal(rate)
            schedule["entries"][model + "/default"] = {"input_tokens": str(r), "cached_input_tokens": str(r / 10),
                "cache_creation_input_tokens": str(r * Decimal("1.25")), "output_tokens": str(r * 5)}
        return schedule

    def test_estimate_uses_additive_semantics_per_model_when_a_schedule_is_supplied(self):
        row = account(self.facts([("two-models-work", "work")]))["spans"][0]
        row = {**row, "_source": {"consumption_time": "2026-10-04T22:00:00Z"}}
        price = estimate_span_cost(row, rate_schedule=self.schedule())
        self.assertEqual(price["status"], "estimated")
        expected = (Decimal(10) * Decimal("0.000003") + Decimal(25000) * Decimal("0.0000003")
            + Decimal(1500) * Decimal("0.00000375") + Decimal(700) * Decimal("0.000015")
            + Decimal(5) * Decimal("0.000001") + Decimal(5000) * Decimal("0.0000001")
            + Decimal(500) * Decimal("0.00000125") + Decimal(200) * Decimal("0.000005"))
        self.assertEqual(Decimal(price["amount"]), expected)
        self.assertEqual(price["models"], ["claude-haiku-5-5", "claude-sonnet-5-5"])
        self.assertEqual(price["input_partition_basis"], "provider-exclusive-input-partitions")

    def test_one_missing_model_rate_makes_the_whole_estimate_unavailable(self):
        schedule = self.schedule(); del schedule["entries"]["claude-haiku-5-5/default"]
        row = {**account(self.facts([("two-models-work", "work")]))["spans"][0], "_source": {"consumption_time": "2026-10-04T22:00:00Z"}}
        price = estimate_span_cost(row, rate_schedule=schedule)
        self.assertEqual((price["status"], price["reason"]), ("unavailable", "missing-model-or-rate"))

    def test_tampered_model_usage_is_rejected(self):
        o = observe("sonnet-work")
        bad = deepcopy(o); bad["model_usage"]["models"][0]["metrics"]["output_tokens"] += 1
        with self.assertRaises(ValueError):
            qualified_observation(bad)
        bad = deepcopy(o); bad["model_usage"]["models"][0]["metrics"]["input_tokens"] = True
        with self.assertRaises(ValueError):
            qualified_observation(bad)
        qualified_observation(o)

    def test_codex_partition_semantics_are_untouched_beside_claude(self):
        from tests.test_usage_accounting import fact as codex_fact
        value = codex_fact("codex-host", metrics={"input_tokens": 100, "cached_input_tokens": 20, "output_tokens": 30})
        value["observation"]["observed"]["model"] = "gpt-5.6-luna"
        claude = self.facts([("haiku-work", "work")])[0]; claude["ref"] = ref("wrk.report", "c"); claude["append_position"] = 2
        result = account([value, claude])
        by_ns = {s["identity"]["namespace"]: s for s in result["spans"]}
        codex = by_ns["openai/managed-codex-cli"]["price_estimate"]
        self.assertEqual((codex["amount"], codex["components"]["input_tokens"]), ("0.00069600", "0.00024000"))
        self.assertIn("codex-total-input-minus-cached", codex["input_partition_basis"])
        self.assertEqual(result["metrics"]["input_tokens"], 107)  # raw Codex total input + Claude uncached input
        self.assertNotIn("model_usage", by_ns["openai/managed-codex-cli"])
        codex_span = by_ns["openai/managed-codex-cli"]
        self.assertEqual(codex_span["provider_reported_money"]["status"], "missing")


if __name__ == "__main__":
    unittest.main()
