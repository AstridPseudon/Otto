from ops.bootstrap.throughput_report import parse_land_log, summarize_runner_records


def test_land_parser_keeps_two_runs_repeats_and_runner_gaps():
    rows = parse_land_log("""2026-10-17T00:00:00Z land X: BASE abc
2026-10-17T00:00:10Z sweep tests/test_slow.py run 1/2: 0 failing
2026-10-17T00:00:30Z sweep tests/test_slow.py run 2/2: 0 failing
2026-10-17T00:01:00Z sweep tests/test_slow.py run 1/2: 0 failing
2026-10-17T00:01:50Z sweep tests/test_slow.py run 2/2: 0 failing
""", source="/runs/X/land.out")
    assert [row["run"] for row in rows["sweeps"]] == [1, 2, 1, 2]
    assert rows["repeated_inputs"]["tests/test_slow.py"] == 2
    assert [row["elapsed_seconds"] for row in rows["sweeps"]] == [None, 20, None, 50]
    assert rows["runner"] == "unavailable: no sealed runner records supplied"


def test_runner_summary_separates_execution_from_queue_wait():
    summary = summarize_runner_records([{
        "run_id": "r1", "state": "settled", "submitted_at": 100,
        "started_at": 110, "settled_at": 130, "seconds": 19.5,
    }])
    assert summary["execution_seconds"] == 19.5
    assert summary["queue_wait_seconds"] == 10
    assert summary["gate_elapsed_seconds"] == 30
