"""Shared file-output plumbing for the stellar-review tools (ADR-0271).
The one ensure-parent idiom lives here so units.py stays pure text
processing and every command module agrees on canonical output paths.
"""

import os


def ensure_parent(path: str) -> str:
    """Create the output file's parent directory; returns the absolute
    path so every downstream use agrees on one canonical form."""
    out = os.path.abspath(path)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    return out
