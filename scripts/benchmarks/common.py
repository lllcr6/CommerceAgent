"""Pure statistics shared by reproducible project benchmarks."""
import math
import random
import statistics
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'data' / 'benchmarks'


def summarize(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return {'n': 0, 'mean': None, 'p50': None, 'p95': None}
    def percentile(q):
        x = (len(values) - 1) * q; lower = int(x); upper = math.ceil(x)
        return values[lower] + (values[upper] - values[lower]) * (x - lower)
    return {'n': len(values), 'mean': statistics.mean(values),
            'p50': percentile(.5), 'p95': percentile(.95)}


def paired_delta(before, after, seed=20261021, resamples=2000):
    if not before or len(before) != len(after):
        raise ValueError('Paired samples must be nonempty and have identical length')
    differences = [b-a for a,b in zip(before,after)]
    rng = random.Random(seed)
    estimates = sorted(statistics.mean(rng.choices(differences, k=len(differences)))
                       for _ in range(resamples))
    baseline = statistics.mean(before); delta = statistics.mean(differences)
    return {'baseline': baseline, 'variant': statistics.mean(after), 'delta': delta,
            'relative_pct': 100*delta/baseline if baseline else None,
            'paired_bootstrap_95_ci': [estimates[int(.025*resamples)], estimates[int(.975*resamples)]],
            'n_pairs': len(before), 'seed': seed, 'resamples': resamples}


def write_report(name, report):
    OUT.mkdir(parents=True,exist_ok=True)
    path=OUT/(name+'.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    tmp.replace(path)
    return path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def load_agent_report():
    """Use the explicit completed cohort when present; raw runs stay immutable."""
    path=OUT/'agent_completed_cohort.json'
    if path.exists():
        report=json.loads(path.read_text())
        sources=report.get('cohort_provenance',{}).get('source_sha256',{})
        if sources and all((OUT/name).exists() and sha(OUT/name)==digest for name,digest in sources.items()):
            return report,path.name
    path=OUT/'agent_performance.json'
    return json.loads(path.read_text()),path.name
