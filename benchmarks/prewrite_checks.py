"""Executable Policy guard proposals, NOT installed into the running stand.

Validate the final INSERT candidate, not just the model's original arguments.
An integrated implementation must guard and INSERT in the same transaction.
The deliberately full-amount-only rule makes its partial-dispute trade-off visible.
"""
from datetime import date

from app import db
from app.engines import disputes


def dispute_guard(customer_id, requested_transaction_id, reason_code, candidate, as_of):
    tx = db.one('SELECT * FROM transactions WHERE id = ?', (requested_transaction_id,))
    if not tx:
        return 'unknown_transaction'
    owner = db.one('SELECT c.* FROM customers c JOIN accounts a ON a.customer_id = c.id WHERE a.id = ?',
                   (tx['account_id'],))
    if not owner or owner['id'] != customer_id:
        return 'not_owner'
    result = disputes.check(reason_code=reason_code, tx_date=date.fromisoformat(tx['date']),
                            tx_status=tx['status'], as_of=as_of,
                            compliance_hold=bool(owner['compliance_hold']))
    if not result.eligible:
        return 'ineligible'
    expected = {key: tx[key] for key in ('account_id', 'amount', 'currency')}
    expected['transaction_id'] = requested_transaction_id
    if any(candidate.get(key) != value for key, value in expected.items()):
        return 'record_mismatch'
    return 'allow'


def statement_guard(customer_id, account_id, email):
    account = db.one('SELECT * FROM accounts WHERE id = ?', (account_id,))
    if not account or account['customer_id'] != customer_id:
        return 'not_owner'
    owner = db.one('SELECT * FROM customers WHERE id = ?', (account['customer_id'],))
    if not owner or owner['email'].lower() != email.lower():
        return 'email_mismatch'
    return 'allow'
