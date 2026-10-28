import random
import re

from app.core.taxonomy import LABEL2ID

_PHONE = re.compile(r"(?<!\w)(?:\+1[ .-]?)?(?:\(\d{3}\)|\d{3})[ .-]\d{3}[ .-]\d{4}(?!\w)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_LONG_DIGITS = re.compile(r"\d{10,}")


def desensitize(text: str) -> str:
    """Mask phone numbers, email addresses, and long references; retain product model IDs."""
    text = _EMAIL.sub("[email]", text)
    text = _PHONE.sub("[phone]", text)
    return _LONG_DIGITS.sub("[reference]", text)


def dedupe(samples: list[dict]) -> list[dict]:

    """Deduplicate input text while preserving the first occurrence and trimming outer whitespace."""
    seen: set[str] = set()
    out: list[dict] = []
    for s in samples:
        t = s["text"].strip()
        if t and t not in seen:
            seen.add(t)
            out.append({**s, "text": t})
    return out


def split_dataset(samples: list[dict], seed: int = 42) -> tuple[list, list, list]:

    """Split 80/10/10 by label combination. Sparse combinations use their lowest-index label; strata under three examples stay in training. Frozen English releases use the family-level exporter instead."""
    rng = random.Random(seed)
    combos: dict[tuple, list[dict]] = {}
    for s in samples:
        key = tuple(sorted(s["labels"], key=LABEL2ID.get))
        combos.setdefault(key, []).append(s)
    strata: dict[tuple, list[dict]] = {}
    for key, items in combos.items():
        target = key if len(items) >= 10 else (min(key, key=LABEL2ID.get),)
        strata.setdefault(target, []).extend(items)
    train: list[dict] = []
    val: list[dict] = []
    test: list[dict] = []
    for key in sorted(strata):
        items = strata[key]
        rng.shuffle(items)
        n = len(items)
        n_test = max(1, round(n * 0.1)) if n >= 3 else 0
        n_val = max(1, round(n * 0.1)) if n >= 3 else 0
        test.extend(items[:n_test])
        val.extend(items[n_test:n_test + n_val])
        train.extend(items[n_test + n_val:])
    return train, val, test
