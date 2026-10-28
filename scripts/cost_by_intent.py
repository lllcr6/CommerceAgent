"""Export customer token usage from the same local records as the dashboard.

Run make cost-report DAYS=7. This reads local usage only; it does not query
Langfuse, run evaluations, or request AI chart descriptions.
"""
import argparse
import json
import pathlib
import sys

from app.kb.eval_checkpoint import atomic_json
from app.paths import OBSERVABILITY_REPORTS_DIR
from app.usage_store import intent_report

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_OUT_DIR = OBSERVABILITY_REPORTS_DIR
_OUT = _OUT_DIR / 'cost_by_intent.txt'
_OUT_JSON = _OUT_DIR / 'cost_by_intent.json'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--days', type=int, default=7)
    args = parser.parse_args()
    if args.days < 1:
        parser.error('--days must be positive')
    report = intent_report(args.days) or {
        'meta': {'days': args.days, 'source': 'Local backend usage'},
        'rows': [], 'total_tokens': 0, 'total_requests': 0}
    rows = report['rows']
    lines = [f'=== Customer token usage by intent (last {args.days} days; local records) ===',
             f"{'Intent':24s} {'Requests':>8s} {'Input tokens':>12s} {'Output tokens':>13s} {'Avg. tokens':>12s}"]
    for row in rows:
        label = row['intent'].replace('_', ' ').title()
        lines.append(f"{label:24s} {row['count']:>8d} {row['input_tokens']:>12,d} "
                     f"{row['output_tokens']:>13,d} {row['avg_tokens']:>12,.0f}")
    if not rows:
        lines.append('No customer usage recorded in this window. Synthetic Agent tests are excluded.')
    text = '\n'.join(lines) + '\n'
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(text, encoding='utf-8')
    atomic_json(_OUT_JSON, report)
    print(text, end='')
    print(f'Reports saved: {_OUT} and {_OUT_JSON}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
