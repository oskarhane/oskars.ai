"""Near-duplicate detection for the stellar-review facts pack (ADR-0271):
normalized token-shingle Jaccard over changed units. The comparison pass
judges the candidate pairs; this module only finds them.
"""

from __future__ import annotations

import itertools
import re

TOKEN_RE = re.compile(r"\w+|[^\w\s]")
LITERAL_RE = re.compile(r'"[^"\n]*"|\b\d+\b')

MIN_UNIT_LINES = 5
MAX_UNIT_LINES = 80
THRESHOLD = 0.45
MAX_PAIRS = 200


def shingles(text: str, width: int = 8) -> frozenset:
    norm = LITERAL_RE.sub("LIT", text)
    toks = TOKEN_RE.findall(norm.lower())
    if len(toks) < width:
        return frozenset([tuple(toks)] if toks else [])
    return frozenset(tuple(toks[i : i + width]) for i in range(len(toks) - width + 1))


def similarity_groups(units: list[dict]) -> list[dict]:
    """Pairs of changed units whose shingle sets meet THRESHOLD, sorted by
    score and truncated to MAX_PAIRS — one fixed criterion, one cap."""
    candidates = [u for u in units if MIN_UNIT_LINES <= (u["end"] - u["start"]) <= MAX_UNIT_LINES]
    sigs = {u["id"]: shingles(u["body"]) for u in candidates}
    pairs: list[dict] = []
    for a_id, b_id in itertools.combinations(sorted(sigs), 2):
        a, b = sigs[a_id], sigs[b_id]
        if not a or not b:
            continue
        inter = len(a & b)
        if not inter:
            continue
        score = inter / (len(a) + len(b) - inter)
        if score >= THRESHOLD:
            pairs.append({"a": a_id, "b": b_id, "score": round(score, 3)})
    pairs.sort(key=lambda p: -p["score"])
    return pairs[:MAX_PAIRS]
