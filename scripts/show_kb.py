"""Preview source documents and structural chunking without writes or provider calls."""
import pathlib

from app.kb import chunking, documents
from app.kb.sources import KB_DIR, SOURCE_TYPES as DOCS

ROOT = pathlib.Path(__file__).resolve().parent.parent
SEED_SQL = ROOT / "sql" / "004_conversation_seed.sql"


def _preview(text: str, n: int = 46) -> str:
    one = " ".join(text.split())
    return one if len(one) <= n else one[:n] + "…"


def main() -> None:
    print("=== Project source documents ===")
    print("Documents (split into searchable passages):")
    for fname, ctype in DOCS.items():
        p = KB_DIR / fname
        raw = p.read_text(encoding="utf-8")
        print(f"  data/rag/knowledge/{fname:<24} [{ctype:<6}] {len(raw):>4} characters / {raw.count(chr(10)) + 1} lines")
    print(f"Synthetic conversation fixture: {SEED_SQL.relative_to(ROOT)} (input for the optional conversation-mining job).")
    print("Conversation mining calls a model and requires human review before extracted answers are published.")

    print("\n=== Passage preview (read-only; nothing saved) ===")
    tally: dict[str, int] = {}
    key_total = 0
    table_notes: list[str] = []
    for fname, ctype in DOCS.items():
        md = (KB_DIR / fname).read_text(encoding="utf-8")
        chunks = documents.build_chunks(md, content_type=ctype)
        tally[ctype] = tally.get(ctype, 0) + len(chunks)

        by_path: dict[str, list[documents.Chunk]] = {}
        for c in chunks:
            by_path.setdefault(c.section_path, []).append(c)
        print(f"\n▼ {fname} [{ctype}]  →  {len(chunks)} passages")
        for path, group in by_path.items():
            multi = f"  ({len(group)} passages in this section)" if len(group) > 1 else ""
            print(f"  ┌ Section: {path}{multi}")
            for j, c in enumerate(group, 1):
                key_total += c.is_key_clause
                flag = " * Key clause" if c.is_key_clause else ""
                seq = f"{j}/{len(group)}" if len(group) > 1 else "-"
                is_tbl = chunking.is_table_block(c.answer)
                kind = "Table" if is_tbl else "Text"
                print(f"  │ [{kind} {seq}]{flag}  Q(questions)={c.questions}  category={c.category}")
                print(f"  │   A({len(c.answer)} characters): {_preview(c.answer)}")
                if is_tbl and len(group) > 1:
                    header = c.answer.strip().splitlines()[0]
                    table_notes.append(f"{fname}“{path.split(' / ')[-1]}” passage {seq}, repeated table header: {header.strip()}")
    print("\n=== Summary ===")
    print(f"Total passages: {sum(tally.values())}; by content type: " + " ".join(f"{k}={v}" for k, v in tally.items()))
    print(f"Key clauses: {key_total} passages (identified by policy-related terms).")
    if table_notes:
        print("Tables split by row, with repeated headers:")
        for n in table_notes:
            print(f"  · {n}")
    print("Long sections are split at sentence boundaries with overlap; short sections remain intact.")


if __name__ == "__main__":
    main()
