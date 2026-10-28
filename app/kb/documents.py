import re
from dataclasses import dataclass

from app.kb import chunking

_KEY_TERMS = ("refund", "return", "shipping", "fee", "warranty", "trial", "deadline", "delivery")

KEY_TERMS = _KEY_TERMS


@dataclass
class Chunk:
    category: str
    questions: str
    answer: str
    section_path: str
    content_type: str
    is_key_clause: int = 0


def has_key_terms(text: str) -> bool:
    text = text.casefold()
    return any(bool(re.search(r"\b" + re.escape(term) + r"\b", text))
               if term.isascii() else term in text for term in KEY_TERMS)


def _is_key(title: str, body: str) -> int:
    head = (title + " " + body[:160]).casefold()
    return int(has_key_terms(head))


is_key = _is_key


def build_chunks(
    md: str, content_type: str,
    chunk_size: int = 1200, overlap: int = 180, table_max_rows: int = 10,
) -> list[Chunk]:
    out: list[Chunk] = []
    for sec in chunking.split_sections(md):
        path = [sec.metadata[k] for k in ("h1", "h2", "h3", "h4") if sec.metadata.get(k)]
        section_path = " / ".join(path)
        title = path[-1] if path else content_type

        category = " / ".join(path[:-1]) if len(path) > 1 else (path[0] if path else content_type)
        body = sec.page_content.strip()
        if not body:
            continue
        if chunking.is_table_block(body):
            pieces = chunking.split_table_rows(body, table_max_rows)
        else:
            base = chunking.recursive_split(body, chunk_size, chunk_overlap=0)
            pieces = chunking.apply_sentence_overlap(base, overlap)
        for piece in pieces:
            out.append(Chunk(
                category=category, questions=title, answer=piece,
                section_path=section_path, content_type=content_type,
                is_key_clause=_is_key(title, piece),
            ))
    return out
