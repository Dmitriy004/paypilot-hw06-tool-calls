import json
from pathlib import Path
import unittest
from unittest.mock import patch
import build_mock
import run_step as runner

ROOT = Path(__file__).parent
CASES = {case['id']: case for p in (ROOT / 'scenarios').glob('*.json')
         for case in [json.loads(p.read_text(encoding='utf-8'))]}


def tool_tree(transaction):
    return {'children': [{'name': 'tool.create_dispute', 'attributes': {
        'tool.name': 'create_dispute',
        'tool.arguments': {'transaction_id': transaction, 'reason_code': 'unauthorized_debit'},
        'tool.result': {'dispute_id': 1, 'status': 'open'}}}]}


class SuiteTests(unittest.TestCase):
    def test_metadata_gates_and_unique_mock_matchers(self):
        self.assertEqual(len(CASES), 13)
        self.assertEqual({c['id'] for c in CASES.values() if c['authorship'] == 'own'}, {'H01', 'H02', 'H03'})
        users, calls = [], []
        for case in CASES.values():
            self.assertTrue(case['dimension'])
            self.assertTrue(case['level'])
            self.assertTrue(set(case['level']) <= {1, 2, 3, 4})
            self.assertEqual(case['runs'], 1 if case['gate'] == 'daily' else 5)
            self.assertTrue(case['turns'][-1].get('live'))
            self.assertEqual(sum(bool(t.get('live')) for t in case['turns']), 1)
            self.assertTrue(case['assertions'])
            for turn in case['turns']:
                users.append(turn['user'])
                for reply in turn.get('model', []):
                    calls.extend(call['id'] for call in reply.get('tool_calls', []))
            if case['gate'] == 'daily':
                self.assertTrue({a['kind'] for a in case['assertions']} <= {'state_row', 'tool_called', 'tool_result_schema'})
            self.assertEqual(case['conditions']['baseline'], {'profile': 'clean', 'defects': ''})
        self.assertEqual(len(users), len(set(users)))
        self.assertEqual(len(calls), len(set(calls)))
        generated = [e for case in CASES.values() for e in build_mock.expectations_for(case)]
        self.assertEqual(len(generated), 28)
        self.assertEqual(len({e['id'] for e in generated}), 28)

    def test_wrong_currency_and_missing_write_fail_state_oracle(self):
        assertion = next(a for a in CASES['S6']['assertions'] if a['kind'] == 'state_row')
        right = {'transaction_id': 'TX-0801', 'account_id': 'ACC-1009', 'amount': 120.0, 'currency': 'USD'}
        for rows, expected in (([right], True), ([dict(right, currency='EUR')], False), ([], False)):
            with self.subTest(rows=rows), patch.object(runner, '_call', return_value={'rows': rows}):
                self.assertEqual(runner.check(assertion, {})[0], expected)

    def test_new_anaphora_rejects_recognized_usd_payment(self):
        assertions = [a for a in CASES['H01']['assertions'] if a['kind'] != 'state_row']
        self.assertTrue(all(runner.check(a, tool_tree('TX-0802'))[0] for a in assertions))
        self.assertTrue(all(not runner.check(a, tool_tree('TX-0801'))[0] for a in assertions))

    def test_repeat_oracle_rejects_zero_and_two_rows(self):
        assertion = CASES['H02']['assertions'][0]
        row = {'transaction_id': 'TX-0202', 'reason_code': 'unauthorized_debit',
               'account_id': 'ACC-1003', 'amount': 89.99, 'currency': 'USD'}
        for count, expected in ((0, False), (1, True), (2, False)):
            with self.subTest(count=count), patch.object(runner, '_call', return_value={'rows': [row] * count}):
                self.assertEqual(runner.check(assertion, {})[0], expected)

    def test_bad_output_contract_fails_without_any_write(self):
        assertion = CASES['S3']['assertions'][0]
        for result, expected in (({'eligible': False, 'checks': {}}, True),
                                 ({'ok': True, 'r': 'N', 'c': [3], 'w': 60}, False)):
            tree = {'children': [{'name': 'tool.check_dispute_eligibility', 'attributes': {
                'tool.name': 'check_dispute_eligibility', 'tool.arguments': {'transaction_id': 'TX-0402'}, 'tool.result': result}}]}
            self.assertEqual(runner.check(assertion, tree)[0], expected)

    def test_forbidden_write_oracle_detects_attempt(self):
        assertion = next(a for a in CASES['S10']['assertions'] if a['kind'] == 'tool_not_called')
        self.assertTrue(runner.check(assertion, {'children': []})[0])
        self.assertFalse(runner.check(assertion, tool_tree('TX-0402'))[0])


if __name__ == '__main__':
    unittest.main()
