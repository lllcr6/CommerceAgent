"""Replace quota-interrupted contexts using an explicitly recorded supplemental run.

Raw reports remain unchanged. This is a completed workload cohort, not a new
uniform-concurrency run or an estimate of the initial run's reliability.
"""
import copy
import json

from scripts.benchmarks.agent_performance import finalize_report
from scripts.benchmarks.common import OUT, now, sha, write_report


def complete_cohort(original, supplement):
    for key in ('model', 'pricing_sha256'):
        if original['meta'][key] != supplement['meta'][key]:
            raise ValueError(f'Incompatible {key}')
    expected = {'chitchat', 'orders_status', 'orders_product'}
    replacements = {s['scenario']: s for s in supplement['sessions']}
    if set(replacements) != expected or len(supplement['sessions']) != 3:
        raise ValueError('Expected exactly the three quota-affected scenarios')
    cohort = copy.deepcopy(original)
    cohort.pop('provider_diagnostics', None)
    cohort['usage'] = {}
    changed = []
    for index, session in enumerate(original['sessions']):
        replacing = session['repeat'] == 2 and session['scenario'] in expected
        selected = replacements[session['scenario']] if replacing else session
        if replacing:
            if not any(t['error'] == 'sse_error' for t in session['turns']):
                raise ValueError('Original session does not match recorded quota interruption')
            if len(selected['turns']) != 3 or any(t['error'] or t['terminal'] != 'done' for t in selected['turns']):
                raise ValueError('Supplemental context did not complete normally')
            changed.append({'scenario': session['scenario'], 'repeat': 2,
                            'original_conversation_id': session['conversation_id'],
                            'supplement_conversation_id': selected['conversation_id']})
        row = copy.deepcopy(selected)
        row['repeat'] = session['repeat']
        row['source_report'] = 'agent_quota_supplement.json' if replacing else 'agent_performance.json'
        row['source_repeat'] = selected['repeat']
        cohort['sessions'][index] = row
        source = supplement if replacing else original
        cid = str(row['conversation_id'])
        if cid in source.get('usage', {}):
            cohort['usage'][cid] = copy.deepcopy(source['usage'][cid])
    if len(changed) != 3:
        raise ValueError('Expected three original interrupted contexts')
    cohort['cohort_provenance'] = {
        'created_at': now(), 'replacements': changed,
        'rule': 'Replace only the three documented provider-quota failures, replaying entire contexts. No selection by answer quality. Original errors and successful prefixes remain in the original raw report.',
        'initial_concurrency': original['meta']['concurrency'],
        'supplement_concurrency': supplement['meta']['concurrency'],
        'latency_limitation': 'Mixed execution periods and concurrency; descriptive completed-workload statistics, not a fresh uniform-concurrency run.',
        'initial_summary': original['summary'],
        'supplement_summary': supplement['summary'],
        'all_executions': {'attempted_turns': original['summary']['attempted_turns'] + supplement['summary']['attempted_turns'],
                           'initial_provider_quota_errors': 3},
    }
    cohort['meta']['account'] = [original['meta']['account'], supplement['meta']['account']]
    cohort['meta']['concurrency'] = f"initial {original['meta']['concurrency']}, supplement {supplement['meta']['concurrency']}"
    return finalize_report(cohort)


def main():
    paths = [OUT / name for name in ('agent_performance.json', 'agent_quota_supplement.json')]
    cohort = complete_cohort(*(json.loads(p.read_text()) for p in paths))
    cohort['cohort_provenance']['source_sha256'] = {p.name: sha(p) for p in paths}
    print(write_report('agent_completed_cohort', cohort))


if __name__ == '__main__':
    main()
