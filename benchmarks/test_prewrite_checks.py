"""Run in the shared stand image; uses real seed SQLite and eligibility engine."""
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app import db

try:
    from prewrite_checks import dispute_guard, statement_guard
except ImportError:
    dispute_guard = statement_guard = None


class PrewriteCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = TemporaryDirectory()
        cls.path = Path(cls.folder.name) / 'seed.db'
        db.build(cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_final_record_guard_rejects_wrong_account_currency_amount_and_expired_window(self):
        self.assertTrue(callable(dispute_guard), 'pre-write dispute guard is missing')
        valid = dict(transaction_id='TX-0801', account_id='ACC-1009', amount=120, currency='USD')
        cases = [
            ('CUS-0008', 'TX-0801', valid, 'unauthorized_debit', 'allow'),
            ('CUS-0008', 'TX-0801', dict(valid, account_id='ACC-1003'), 'unauthorized_debit', 'record_mismatch'),
            ('CUS-0008', 'TX-0801', dict(valid, currency='EUR'), 'unauthorized_debit', 'record_mismatch'),
            ('CUS-0008', 'TX-0801', dict(valid, amount=50), 'unauthorized_debit', 'record_mismatch'),
            ('CUS-0002', 'TX-0801', valid, 'unauthorized_debit', 'not_owner'),
            ('CUS-0008', 'TX-0801', valid, 'unknown_reason', 'ineligible'),
            ('CUS-0004', 'TX-0402', dict(transaction_id='TX-0402', account_id='ACC-1005', amount=240, currency='EUR'), 'duplicate_charge', 'ineligible'),
        ]
        with db.bound(self.path):
            for owner, tx, record, reason, expected in cases:
                with self.subTest(owner=owner, tx=tx, record=record, reason=reason):
                    self.assertEqual(dispute_guard(owner, tx, reason, record, date(2026, 9, 15)), expected)
            self.assertEqual(db.table_dump('disputes'), [])

    def test_statement_guard_accepts_registered_address_and_blocks_another_recipient(self):
        self.assertTrue(callable(statement_guard), 'pre-write statement guard is missing')
        with db.bound(self.path):
            self.assertEqual(statement_guard('CUS-0001', 'ACC-1001', 'ALICE.NOVAK@EXAMPLE.COM'), 'allow')
            self.assertEqual(statement_guard('CUS-0001', 'ACC-1001', 'accountant@example.com'), 'email_mismatch')
            self.assertEqual(statement_guard('CUS-0002', 'ACC-1001', 'alice.novak@example.com'), 'not_owner')
            self.assertEqual(statement_guard('CUS-0001', 'missing', 'alice.novak@example.com'), 'not_owner')
            self.assertEqual(db.table_dump('statements_sent'), [])


if __name__ == '__main__':
    unittest.main()
