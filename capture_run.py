"""Run the unchanged course runner and retain each run before its next DB reset.

Only trace/response/state plus proxy COUNTS are retained. MockServer request
headers are deliberately not written: they may contain provider credentials.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys

import run_step as runner


def capture_snapshot(path, scenario, settings, execution):
    step, response, tree, scripted_calls = execution
    disputes = runner._call(runner.STAND, "GET", "/api/_test/state/disputes")["rows"]
    state = {"disputes": disputes}
    for assertion in scenario.get("assertions", []):
        table = assertion.get("table") if assertion.get("kind") == "state_row" else None
        if table and table not in state:
            state[table] = runner._call(runner.STAND, "GET", f"/api/_test/state/{table}")["rows"]
    received = runner._call(runner.MOCK, "PUT", "/mockserver/retrieve?type=REQUESTS",
                            {"path": ".*/chat/completions"})
    proxied = runner._call(runner.MOCK, "PUT", "/mockserver/retrieve?type=RECORDED_EXPECTATIONS",
                           {"path": ".*/chat/completions"})
    record = {"captured_at_utc": datetime.now(timezone.utc).isoformat(),
              "series": os.environ.get("L07_RUN_LABEL", "manual"),
              "scenario": scenario["id"], "settings": settings, "live_step": step,
              "scripted_calls": scripted_calls, "response": response, "trace": tree,
              "disputes": disputes, "state": state,
              "proxy": {"received": len(received), "proxied": len(proxied)}}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def result_args(args, label):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", label):
        raise ValueError("L07_RUN_LABEL must contain only letters, digits, underscores or hyphens")
    if any(arg == "--json" or arg.startswith("--json=") for arg in args):
        return list(args)
    return [*args, "--json", f"reports/{label}.json"]


def main():
    label = os.environ.get("L07_RUN_LABEL", "manual")
    output = Path(os.environ.get("L07_EVIDENCE", f"reports/{label}.evidence.jsonl"))
    Path("reports").mkdir(exist_ok=True)
    original_args = sys.argv[:]
    sys.argv = [sys.argv[0], *result_args(sys.argv[1:], label)]
    original = runner.run_once

    def observed_run(scenario, settings):
        execution = original(scenario, settings)
        capture_snapshot(output, scenario, settings, execution)
        return execution

    runner.run_once = observed_run
    try:
        runner.main()
    finally:
        runner.run_once = original
        sys.argv = original_args


if __name__ == "__main__":
    main()
