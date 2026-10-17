"""Summarize historical landing log intervals and sealed runner timing records."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

STAMP = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ) ")
SWEEP = re.compile(r"sweep (tests/\S+) run ([12])/2:")


def _time(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")


def parse_land_log(text: str, source: str = "<memory>") -> dict:
    events, per_file = [], defaultdict(list)
    for line in text.splitlines():
        match = STAMP.match(line)
        if not match:
            continue
        stamp = _time(match.group(1))
        events.append(stamp)
        sweep = SWEEP.search(line)
        if sweep:
            per_file[sweep.group(1)].append({"run": int(sweep.group(2)), "at": stamp})
    sweeps, repeats = [], Counter()
    for filename, occurrences in per_file.items():
        repeats[filename] = len(occurrences) // 2
        for offset in range(0, len(occurrences), 2):
            pair = occurrences[offset:offset + 2]
            for index, item in enumerate(pair):
                elapsed = None
                if index == 1 and pair[0]["run"] == 1 and item["run"] == 2:
                    elapsed = (item["at"] - pair[0]["at"]).total_seconds()
                sweeps.append({"source": source, "file": filename, "run": item["run"],
                               "completed_at": item["at"].isoformat() + "Z",
                               "elapsed_seconds": elapsed})
    return {"source": source, "gate_elapsed_seconds": (events[-1] - events[0]).total_seconds() if len(events) > 1 else None,
            "sweeps": sweeps, "repeated_inputs": dict(repeats),
            "runner": "unavailable: no sealed runner records supplied"}


def summarize_runner_records(records: list[dict]) -> dict:
    execution, queue, gate = [], [], []
    for record in records:
        start, submitted, settled = record.get("started_at"), record.get("submitted_at"), record.get("settled_at")
        if isinstance(record.get("seconds"), (int, float)):
            execution.append(record["seconds"])
        if isinstance(start, (int, float)) and isinstance(submitted, (int, float)):
            queue.append(start - submitted)
        if isinstance(settled, (int, float)) and isinstance(submitted, (int, float)):
            gate.append(settled - submitted)
    return {"records": len(records), "execution_seconds": sum(execution) if execution else None,
            "queue_wait_seconds": sum(queue) if queue else None,
            "gate_elapsed_seconds": sum(gate) if gate else None}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", nargs="+", type=Path)
    parser.add_argument("--runner-records", type=Path)
    args = parser.parse_args()
    reports = [parse_land_log(path.read_text(errors="replace"), str(path)) for path in args.logs]
    runner = summarize_runner_records([json.loads(line) for line in args.runner_records.read_text().splitlines() if line.strip()]) if args.runner_records else None
    pairs = [(row["elapsed_seconds"], row["file"], row["source"]) for report in reports for row in report["sweeps"] if row["elapsed_seconds"] is not None]
    print("# Historical throughput baseline\n")
    print(f"Logs: {len(reports)}; gate elapsed (first to last logged timestamp): {sum(r['gate_elapsed_seconds'] or 0 for r in reports):.0f}s. This is elapsed time, not CPU.")
    if runner:
        print(f"Runner records: {runner}")
    else:
        print("Runner execution, queue wait, and runner gate elapsed: unavailable (no sealed runner record export found).")
    print("\nLargest paired sweep completion intervals (elapsed, not CPU):")
    totals = defaultdict(float)
    for seconds, filename, _source in pairs:
        totals[filename] += seconds
    for filename, seconds in sorted(totals.items(), key=lambda item: item[1], reverse=True)[:10]:
        refs = sorted({source for value, file, source in pairs if file == filename})
        print(f"- {filename}: {seconds:.0f}s across {sum(1 for value, file, _ in pairs if file == filename)} pairs; {', '.join(refs)}")
    print("\nSource log paths:")
    for path in args.logs:
        print(f"- {path}")


if __name__ == "__main__":
    main()
