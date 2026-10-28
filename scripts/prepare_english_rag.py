"""Build reviewed English RAG annotations offline, optionally binding to live IDs.

python -m scripts.prepare_english_rag             # no services or paid calls
python -m scripts.prepare_english_rag --bind-live # read-only live index binding
"""
import argparse
import asyncio
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from app.kb.documents import build_chunks
from app.kb.evaluation import fingerprint, validate_annotations
from app.kb.sources import KB_DIR, SOURCE_TYPES
from app.paths import RAG_EVAL_FILE

ROOT = RAG_EVAL_FILE.parent


def source_chunks() -> list[dict]:
    rows = []
    for source, ctype in SOURCE_TYPES.items():
        for chunk in build_chunks((KB_DIR / source).read_text(encoding='utf-8'), ctype):
            row = asdict(chunk)
            row['question'] = row.pop('questions')
            row.update(id=len(rows) + 1, source=source)
            row['sha256'] = fingerprint(row)
            rows.append(row)
    return rows


def identity(row: dict) -> tuple:
    return tuple(row.get(k, '') for k in ('section_path', 'question', 'answer', 'content_type', 'category'))


def bind_live(chunks: list[dict], live: list[dict]) -> list[dict]:
    by_content = {}
    for row in live:
        key = identity(row)
        if key in by_content:
            raise ValueError('Ambiguous duplicate live chunk; review index before binding')
        by_content[key] = row['id']
    rebound = []
    for chunk in chunks:
        if identity(chunk) not in by_content:
            raise ValueError(f"English chunk is missing or stale in live index: {chunk['section_path']}")
        row = dict(chunk, id=by_content[identity(chunk)])
        row['sha256'] = fingerprint(row)
        rebound.append(row)
    return rebound


def annotate(cases: list[dict], chunks: list[dict]) -> list[dict]:
    rows = []
    for case in cases:
        selected = []
        for ref in case['evidence_sections']:
            match = [c for c in chunks if c['source'] == ref['source'] and c['question'] == ref['title']]
            if not match:
                raise ValueError(f"{case['id']}: unknown source section {ref}")
            selected.extend(c['id'] for c in match)
        row = dict(case, relevant_chunk_ids=list(dict.fromkeys(selected)), relevance_version='chunk-id-v1',
                   expect_section=[r['title'] for r in case['evidence_sections']])
        evidence = '\n'.join(c['answer'] for c in chunks if c['id'] in selected).casefold()
        for point in row['expect_points']:
            if point.casefold() not in evidence:
                raise ValueError(f"{row['id']}: reference point absent from annotated evidence: {point!r}")
        # Group by primary source section to avoid splitting direct paraphrases
        # across dev and held-out. Shared policy facts across scenarios remain.
        primary = case['evidence_sections'][:1] or [case['query']]
        group = hashlib.sha256(json.dumps(primary, sort_keys=True).encode()).hexdigest()
        row['family'] = group[:12]
        row['split'] = 'heldout' if int(group[:8], 16) % 4 == 0 else 'dev'
        rows.append(row)
    validate_annotations(rows, chunks)
    if len({r['query'] for r in rows}) != len(rows):
        raise ValueError('Duplicate evaluation question')
    return rows


def write(chunks: list[dict], rows: list[dict], bound: bool) -> None:
    RAG_EVAL_FILE.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')
    manifest = {'schema_version':'chunk-id-v1','corpus_version':'paw-hearth-en-v1','language':'en-US',
                'collection':'knowledge_en_v1','id_binding':'live' if bound else 'offline-canonical',
                'sources_sha256':{name:hashlib.sha256((KB_DIR/name).read_bytes()).hexdigest() for name in SOURCE_TYPES},
                'chunks':chunks}
    (ROOT/'chunks.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# English RAG annotation review', '',
           '121 authored questions. Source sections are explicitly selected; relevance is not inferred from keyword matches.',
           'Offline canonical chunk IDs must be rebound to the deployed English index before live evaluation.',
           'Development and held-out scenarios are grouped by primary evidence section. They share a synthetic authored corpus; this is not an independent production benchmark.', '',
           '| ID | Split | Bucket | Question | Relevant chunk IDs |', '| --- | --- | --- | --- | --- |']
    lines.extend(f"| {r['id']} | {r['split']} | {r['bucket']} | {r['query'].replace('|','/')} | {', '.join(map(str,r['relevant_chunk_ids'])) or 'None'} |" for r in rows)
    (ROOT/'annotations.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


async def main(bind: bool) -> None:
    chunks = source_chunks()
    if bind:
        from app.kb import milvus_client as m
        live = await m.acall(lambda: m.get_client().query(collection_name=m.COLLECTION, filter='id >= 0',
                             output_fields=['section_path','question','answer','content_type','category'],limit=16384))
        chunks = bind_live(chunks, live)
    rows = annotate(json.loads((ROOT/'cases_en.json').read_text()), chunks)
    write(chunks, rows, bind)
    print(f'{len(rows)} questions, {len(chunks)} chunks; buckets: {dict(Counter(r["bucket"] for r in rows))}; binding={"live" if bind else "offline-canonical"}')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind-live',action='store_true')
    asyncio.run(main(parser.parse_args().bind_live))
