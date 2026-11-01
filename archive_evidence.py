"""Verify archived observations with the course oracle and render a readable appendix.

Usage: python archive_evidence.py evidence/homework-runs
No network requests; state assertions use the snapshot retained before reset.
"""
from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import run_step as runner


def main(folder):
    root = Path(__file__).parent
    folder = Path(folder)
    cases = {s['id']: s for p in sorted((root / 'scenarios').glob('*.json'))
             for s in [json.loads(p.read_text(encoding='utf-8'))]}
    set_hash = hashlib.sha256(b''.join(p.read_bytes().replace(b'\r\n', b'\n')
                             for p in sorted((root / 'scenarios').glob('*.json')))).hexdigest()
    assert set_hash == '8c07838fce08f290b7f35e2a3929bf644ecc997ba5d234aa882408c4cbe6530a'
    prediction_time = int(subprocess.check_output(
        ['git', 'show', '-s', '--format=%ct', '2ae14ca'], cwd=root, text=True).strip())
    all_records, groups = [], []
    total_assertions = 0
    for phase in ('daily', 'baseline', 'release'):
        records = [json.loads(line) for line in (folder / f'{phase}.evidence.jsonl').read_text(encoding='utf-8').splitlines()]
        report = json.loads((folder / f'{phase}.json').read_text(encoding='utf-8'))
        assert len(records) == sum(len(g['runs']) for g in report)
        for group in report:
            matching = [r for r in records if r['scenario'] == group['scenario'] and r['settings'] == group['settings']]
            assert len(matching) == len(group['runs'])
            for rec, run in zip(matching, group['runs']):
                assert rec['series'] == phase
                assert rec['trace']['started_at'] > prediction_time
                assert run['answer'] == rec['response']['answer']
                assert len(runner._llm_spans(rec['trace'])) == run['model_calls']
                assert rec['proxy']['received'] == run['mock_seen']
                def offline_call(base, method, route, body=None, **kwargs):
                    assert method == 'GET' and route.startswith('/api/_test/state/')
                    return {'rows': rec['state'][route.rsplit('/', 1)[1]]}
                with patch.object(runner, '_call', side_effect=offline_call):
                    replay = [runner.check(a, rec['trace']) for a in cases[rec['scenario']]['assertions']]
                assert [v[0] for v in replay] == [v['ok'] for v in run['verdicts']]
                assert all(v[0] for v in replay) == run['passed']
                total_assertions += len(replay)
            costs = [sum((Decimal(str(s['attributes'].get('provider.cost_usd', 0)))
                          for s in runner._llm_spans(r['trace'])), Decimal(0)) for r in matching]
            group_cost = sum(costs, Decimal(0))
            groups.append({'phase': phase, 'scenario': group['scenario'], 'condition': group['condition'],
                           'pass': sum(r['passed'] for r in group['runs']), 'n': len(matching),
                           'model_calls': sum(r['model_calls'] for r in group['runs']),
                           'provider_cost_usd': str(group_cost), 'mean_provider_cost_usd': str(group_cost / len(matching)),
                           'request_ids': [r['response']['request_id'] for r in matching]})
        all_records.extend(records)
    assert len(all_records) == 76
    assert len({r['response']['request_id'] for r in all_records}) == len(all_records)
    calls = [s for r in all_records for s in runner._llm_spans(r['trace'])]
    cost = sum((Decimal(str(s['attributes'].get('provider.cost_usd', 0))) for s in calls), Decimal(0))
    models = sorted({s['attributes'].get('gen_ai.request.model') for s in calls})
    s5 = {g['condition']: g for g in groups if g['phase'] == 'release' and g['scenario'] == 'S5'}
    ratio = Decimal(s5['defect']['mean_provider_cost_usd']) / Decimal(s5['baseline']['mean_provider_cost_usd'])
    s10 = [r for r in all_records if r['series'] == 'release' and r['scenario'] == 'S10' and r['settings']['defects'] == 'D29']
    attempts = [any(s['attributes']['tool.name'] == 'create_dispute' for s in runner._tool_spans(r['trace'])) for r in s10]
    writes = [any(row.get('transaction_id') == 'TX-0402' for row in r['state']['disputes']) for r in s10]
    successes = [any(s['attributes']['tool.name'] == 'create_dispute' and s['attributes'].get('tool.result', {}).get('status') == 'open'
                     for s in runner._tool_spans(r['trace'])) for r in s10]
    assert successes == writes
    summary = {'set_hash': set_hash, 'prediction_commit': '2ae14ca', 'live_runs': len(all_records),
               'replayed_assertions': total_assertions, 'chat_requests': sum(r['live_step'] for r in all_records),
               'paid_llm_calls': len(calls), 'models': models,
               'scripted_model_requests': sum(r['scripted_calls'] for r in all_records),
               'provider_cost_usd': str(cost),
               'response_cost_usd': str(sum((Decimal(str(r['response']['usage']['cost_usd'])) for r in all_records), Decimal(0))),
               'input_tokens': sum(s['attributes'].get('gen_ai.usage.input_tokens', 0) for s in calls),
               'output_tokens': sum(s['attributes'].get('gen_ai.usage.output_tokens', 0) for s in calls),
               'cache_read_tokens': sum(s['attributes'].get('gen_ai.usage.cache_read_input_tokens', 0) for s in calls),
               'cache_write_tokens': sum(s['attributes'].get('gen_ai.usage.cache_creation_input_tokens', 0) for s in calls),
               's5_provider_cost_ratio': str(ratio), 's10_attempts': attempts, 's10_successful_writes': writes, 'groups': groups}
    (folder.parent / 'homework-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    lines = ['# ДЗ_6: повні первинні докази', '',
             'Дослівні відповіді, request_id, tool.args/result і стан до reset. Авторизаційні заголовки не зберігаються.', '',
             f'Набір `{set_hash}`; окремий прогноз `2ae14ca`; усі started_at перевірені пізніше коміту.', '',
             '| Етап / ID / умова | PASS / N | Виклики | Provider USD |', '| --- | --- | --- | --- |']
    for g in groups:
        lines.append(f"| {g['phase']} / {g['scenario']} / {g['condition']} | {g['pass']}/{g['n']} | {g['model_calls']} | {g['provider_cost_usd']} |")
    lines += ['', f"{len(all_records)} живих кроків; {len(calls)} платних LLM-викликів; provider.cost_usd = {cost} USD. "
              f"Усі {total_assertions} assertion verdict-и відтворено штатним check() офлайн зі збереженими таблицями.", '']
    occurrences = Counter()
    for rec in all_records:
        condition = rec['settings'].get('defects') or 'baseline'
        key = rec['series'], rec['scenario'], condition
        occurrences[key] += 1
        lines += [f"## {rec['series']} / {rec['scenario']} / {condition} / run {occurrences[key]}", '',
                  f"request_id `{rec['response']['request_id']}`; root `{rec['trace']['span_id']}`; live step {rec['live_step']}; {rec['captured_at_utc']}.", '',
                  'Поточний вхід:', '```text', rec['trace']['attributes'].get('request.message', ''), '```', '',
                  'Відповідь агента (дослівно):', '```text', rec['response']['answer'], '```', '',
                  'Usage, proxy counts і state після поточного кроку:', '```json',
                  json.dumps({k: rec[k] for k in ('state', 'proxy')} | {'usage': rec['response']['usage']}, ensure_ascii=False, indent=2), '```', '']
        for span in rec['trace'].get('children', []):
            if span['name'] != 'llm.call' and not span['name'].startswith('tool.'):
                continue
            attrs = {k: v for k, v in span['attributes'].items() if k.startswith(('tool.', 'gen_ai.usage.'))
                     or k in ('provider.cost_usd', 'gen_ai.request.model')}
            lines += [f"{span['name']} · span `{span['span_id']}`:", '```json', json.dumps(attrs, ensure_ascii=False, indent=2), '```', '']
    (folder.parent / 'homework-evidence.md').write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k != 'groups'}, ensure_ascii=False, indent=2))
    print([(g['phase'], g['scenario'], g['condition'], g['pass'], g['n']) for g in groups])


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'evidence/homework-runs')
