"""Read-only guard timings on a disposable, real stand seed database.

Run this script in the shared stand image, with this homework mounted at /revision.
No LLM, tool writes, external mail, reset or reads of the running stand database.
"""
import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
from statistics import median
from tempfile import TemporaryDirectory
from time import get_clock_info, perf_counter_ns

from app import db
from app.engines import disputes, policy
import prewrite_checks
from prewrite_checks import dispute_guard, statement_guard


def measure(output, count=2000, warmup=100):
    valid = dict(transaction_id='TX-0801', account_id='ACC-1009', amount=120, currency='USD')
    expired = dict(transaction_id='TX-0402', account_id='ACC-1005', amount=240, currency='EUR')
    as_of = date(2026, 9, 15)
    def check_dispute(record=valid, owner='CUS-0008', tx='TX-0801', reason='unauthorized_debit'):
        return dispute_guard(owner, tx, reason, record, as_of)
    cases = [
        ('create_dispute_allow', lambda: check_dispute(), 'allow'),
        ('create_dispute_expired', lambda: check_dispute(expired, 'CUS-0004', 'TX-0402', 'duplicate_charge'), 'ineligible'),
        ('create_dispute_wrong_account', lambda: check_dispute(dict(valid, account_id='ACC-1003')), 'record_mismatch'),
        ('create_dispute_wrong_currency', lambda: check_dispute(dict(valid, currency='EUR')), 'record_mismatch'),
        ('create_dispute_partial_legitimate', lambda: check_dispute(dict(valid, amount=50)), 'record_mismatch'),
        ('send_statement_allow', lambda: statement_guard('CUS-0001', 'ACC-1001', 'alice.novak@example.com'), 'allow'),
        ('send_statement_accountant_legitimate', lambda: statement_guard('CUS-0001', 'ACC-1001', 'accountant@example.com'), 'email_mismatch'),
        ('timer_and_call_control', lambda: None, None),
    ]
    samples = {name: [] for name, _, _ in cases}
    with TemporaryDirectory(prefix='paypilot-guard-bench-') as folder:
        target = Path(folder) / 'seed.db'
        db.build(target)
        with db.bound(target):
            before = {table: db.table_dump(table) for table in db.STATE_TABLES}
            for _, operation, expected in cases:
                for _ in range(warmup):
                    assert operation() == expected
            for index in range(count):
                # Rotate order to spread short host scheduling/load changes across cases.
                for offset in range(len(cases)):
                    name, operation, expected = cases[(index + offset) % len(cases)]
                    start = perf_counter_ns()
                    result = operation()
                    elapsed = perf_counter_ns() - start
                    assert result == expected, (name, result, expected)
                    samples[name].append(elapsed)
            after = {table: db.table_dump(table) for table in db.STATE_TABLES}
            assert before == after, 'benchmark must not mutate any seed table'
    report = {
        'captured_at_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'Guard-only local SQLite wall time, including db.one connection open/read/close and real eligibility engine; excludes INSERT/commit, locks across guard+write, HTTP, LLM, SMTP and network latency. Not a production end-to-end benchmark.',
        'environment': {'python': platform.python_version(), 'os': platform.system(),
                        'machine': platform.machine(), 'sqlite': db.sqlite3.sqlite_version,
                        'perf_counter_resolution_seconds': get_clock_info('perf_counter').resolution},
        'fixture': 'db.build disposable seed v1.0.0, as_of=2026-09-15; running stand database untouched',
        'samples_per_case': count, 'warmup_per_case': warmup, 'state_unchanged': before == after,
        'source_sha256': {str(Path(module.__file__).name): hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                          for module in (prewrite_checks, db, disputes, policy)},
        'cases': [],
    }
    for name, _, expected in cases:
        values = samples[name]
        ordered = sorted(values)
        report['cases'].append({'id': name, 'expected': expected, 'matched': len(values), 'n': count,
                                'median_ms': median(values) / 1e6,
                                'p95_ms': ordered[math.ceil(.95 * len(values)) - 1] / 1e6,
                                'min_ms': min(values) / 1e6, 'max_ms': max(values) / 1e6,
                                'samples_ns': values})
    Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'cases'}, indent=2))
    for row in report['cases']:
        print(row['id'], f"{row['matched']}/{row['n']}", 'median_ms', row['median_ms'], 'p95_ms', row['p95_ms'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    measure(args.output)
