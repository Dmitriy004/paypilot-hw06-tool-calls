import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    import capture_run
except ImportError:
    capture_run = None


class EvidenceCaptureTests(unittest.TestCase):
    def test_all_asserted_state_tables_survive_the_next_reset(self):
        def api(base, method, route, body=None, **kwargs):
            if route.startswith("/api/_test/state/"):
                return {"rows": [{"table": route.rsplit("/", 1)[1]}]}
            return []

        scenario = {"id": "H03", "assertions": [
            {"kind": "state_row", "table": "statements_sent"}]}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "evidence.jsonl"
            with patch.object(capture_run.runner, "_call", side_effect=api):
                capture_run.capture_snapshot(path, scenario, {}, (1, {}, {}, 0))
            record = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(record["state"]["statements_sent"], [{"table": "statements_sent"}])
        self.assertEqual(record["state"]["disputes"], record["disputes"])

    def test_missing_json_option_gets_a_phase_report(self):
        self.assertTrue(hasattr(capture_run, "result_args"), "phase report routing is missing")
        self.assertEqual(capture_run.result_args(["--gate", "daily"], "daily"),
                         ["--gate", "daily", "--json", "reports/daily.json"])

    def test_explicit_report_path_is_not_overwritten(self):
        self.assertTrue(hasattr(capture_run, "result_args"), "phase report routing is missing")
        args = ["--condition", "baseline", "--json=reports/custom.json"]
        self.assertEqual(capture_run.result_args(args, "baseline"), args)

    def test_report_phase_cannot_escape_reports_directory(self):
        self.assertTrue(hasattr(capture_run, "result_args"), "phase report routing is missing")
        with self.assertRaises(ValueError):
            capture_run.result_args([], "../outside")

    def test_full_answer_request_id_and_state_survive_capture_without_proxy_credentials(self):
        self.assertIsNotNone(capture_run, "evidence capture implementation is missing")
        response = {"request_id": "live-123", "answer": "original answer " * 100,
                    "usage": {"cost_usd": 0.001}}
        tree = {"name": "agent.request", "children": [{"name": "tool.create_dispute",
                "attributes": {"tool.result": {"account_id": "ACC-1002", "currency": "EUR"}}}]}

        def api(base, method, route, body=None, **kwargs):
            if route == "/api/_test/state/disputes":
                return {"rows": [{"transaction_id": "TX-0202", "currency": "EUR"}]}
            if "RECORDED_EXPECTATIONS" in route:
                return [{"httpRequest": {"headers": {"Authorization": ["do-not-save"]}}}]
            if "REQUESTS" in route:
                return [{"headers": {"Authorization": ["do-not-save"]}}] * 4
            raise AssertionError(route)

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "evidence.jsonl"
            with patch.object(capture_run.runner, "_call", side_effect=api):
                capture_run.capture_snapshot(path, {"id": "S1"}, {"defects": "D12"},
                                             (3, response, tree, 4))
            record = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(record["response"], response)
        self.assertEqual(record["trace"], tree)
        self.assertEqual(record["disputes"][0]["currency"], "EUR")
        self.assertEqual(record["proxy"], {"received": 4, "proxied": 1})
        self.assertNotIn("do-not-save", json.dumps(record))

    def test_multiple_runs_append_in_order_instead_of_overwriting(self):
        self.assertIsNotNone(capture_run, "evidence capture implementation is missing")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "nested" / "evidence.jsonl"
            with patch.object(capture_run.runner, "_call", return_value={"rows": []}):
                for request_id in ("r1", "r2"):
                    capture_run.capture_snapshot(path, {"id": "S3"}, {},
                                                 (2, {"request_id": request_id}, {}, 2))
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["response"]["request_id"] for r in records], ["r1", "r2"])


if __name__ == "__main__":
    unittest.main()
