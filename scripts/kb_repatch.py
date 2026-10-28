"""Apply edits to existing knowledge passages without deleting stored knowledge.

Match project-file chunks to stored chunks by section path and position. Changed
chunks keep their IDs and become pending indexing. New file sections are reported
for manual import; stored passages without a matching file section are preserved.
Run: make kb-repatch. No embedding or chat-model requests are made.
"""
import asyncio
import sys

from app.db import repository
from app.kb import documents
from app.kb.sources import KB_DIR, SOURCE_TYPES


def _norm(s: str) -> str:
    return "\n".join(line.rstrip() for line in (s or "").strip().splitlines())


async def apply_edits() -> dict:
    in_db = await repository.list_chunks_by_content_types(set(SOURCE_TYPES.values()))
    # Long sections may have multiple chunks; match each position, not only the heading.
    by_path: dict[str, list] = {}
    for row in in_db:
        by_path.setdefault(row.section_path, []).append(row)
    updated, new, preserved = [], [], []
    unchanged = 0
    used: dict[str, int] = {}
    for fname, ctype in SOURCE_TYPES.items():
        md = (KB_DIR / fname).read_text(encoding="utf-8")
        for chunk in documents.build_chunks(md, content_type=ctype):
            i = used.get(chunk.section_path, 0)
            used[chunk.section_path] = i + 1
            rows = by_path.get(chunk.section_path) or []
            row = rows[i] if i < len(rows) else None
            if row is None:
                new.append(f"{fname}: {chunk.section_path} (passage {i + 1})")
                continue
            if _norm(row.answer) == _norm(chunk.answer) and _norm(row.questions) == _norm(chunk.questions):
                unchanged += 1
                continue
            await repository.repend_chunk_text(row.id, chunk.questions, chunk.answer)
            updated.append(f"ID {row.id}: {chunk.section_path}")
    for path, rows in by_path.items():
        preserved.extend(f"ID {row.id}: {path}" for row in rows[used.get(path, 0):])
    return {"updated": updated, "unchanged": unchanged, "new": new,
            "preserved": preserved, "pending": await repository.count_chunks_by_status("pending")}


def format_result(result: dict) -> str:
    updated, new, preserved = result['updated'], result['new'], result['preserved']
    lines = ['APPLY DOCUMENT EDITS — RESULT']
    if not updated and not new and not preserved:
        lines.append(f"No changes needed. All {result['unchanged']} project-file passages already match the knowledge base.")
    else:
        lines.append(f"Updated: {len(updated)} | Already up to date: {result['unchanged']} | New file passages not imported: {len(new)} | Stored-only passages kept: {len(preserved)}")
    if updated:
        lines += ['', 'Updated existing passages (original IDs preserved):', *['  ' + s for s in updated]]
    if new:
        lines += ['', f"{len(new)} new file passages have no stored match. This action did not import them.",
                  'To add them, paste their content into section 1 (Paste a new document) and save it.', *['  ' + s for s in new]]
    if preserved:
        lines += ['', f"{len(preserved)} stored passages have no matching section in the current project files. They were kept unchanged.",
                  'This can happen when a file section is renamed or removed, or knowledge is added directly in the admin page.',
                  'This action only updates matching sections; it never deletes knowledge. These entries are not update failures.',
                  *['  ' + s for s in preserved]]
    lines += ['', f"Waiting to be indexed: {result['pending']}."]
    lines.append('Next: click Index pending chunks in section 4 to publish the saved changes to search.'
                 if result['pending'] else 'Next: no indexing is needed. You can test a question in section 5.')
    return '\n'.join(lines)


async def main() -> int:
    print(format_result(await apply_edits()))
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
