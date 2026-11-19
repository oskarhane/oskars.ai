"""Language-aware unit extraction for the stellar-review facts pack
(ADR-0271): per-language unit tables, unit-end scanners, scope-stack
context tracking, signature/content hashing, and body truncation.

Everything here is pure text processing — no git, no I/O. facts.py owns
the git side; this module owns the language side. Add a language by
extending the tables, not by branching inside functions.
"""

from __future__ import annotations

import hashlib
import os
import re

LANG_BY_EXT = {
    ".rs": "rust",
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".md": "markdown",
}

# Unit starts, per language. Each pattern matches the line where a unit
# begins; group "name" is the unit name, "kind" the unit kind.
UNIT_PATTERNS = {
    "rust": [
        ("fn", re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+(?P<name>[A-Za-z_]\w*)")),
        ("struct", re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?struct\s+(?P<name>[A-Za-z_]\w*)")),
        ("enum", re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?enum\s+(?P<name>[A-Za-z_]\w*)")),
        ("trait", re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:unsafe\s+)?trait\s+(?P<name>[A-Za-z_]\w*)")),
        ("type", re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?type\s+(?P<name>[A-Za-z_]\w*)")),
    ],
    "python": [
        ("fn", re.compile(r"^(?P<indent>\s*)(?:async\s+)?def\s+(?P<name>[A-Za-z_]\w*)")),
        ("class", re.compile(r"^(?P<indent>\s*)class\s+(?P<name>[A-Za-z_]\w*)")),
    ],
    "javascript": [
        ("fn", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(?P<name>[A-Za-z_$][\w$]*)")),
        ("fn", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>")),
        ("class", re.compile(r"^\s*(?:export\s+)?class\s+(?P<name>[A-Za-z_$][\w$]*)")),
    ],
    "typescript": [],
    "go": [
        ("fn", re.compile(r"^func\s+(?:\([^)]*\)\s*)?(?P<name>[A-Za-z_]\w*)")),
        ("type", re.compile(r"^type\s+(?P<name>[A-Za-z_]\w*)\s+(?:struct|interface)\b")),
    ],
    "java": [
        ("class", re.compile(r"^\s*(?:public|private|protected|abstract|final|static|\s)*\b(?:class|interface|enum|record)\s+(?P<name>[A-Za-z_]\w*)")),
        ("fn", re.compile(r"^\s*(?:public|private|protected|static|final|synchronized|abstract|\s)+[\w<>\[\],.?]+\s+(?P<name>[a-zA-Z_]\w*)\s*\([^;]*$")),
    ],
    "c": [
        ("fn", re.compile(r"^(?:static\s+|inline\s+|[A-Za-z_][\w\s\*]*\s)+(?P<name>[A-Za-z_]\w*)\s*\([^;]*$")),
    ],
}
UNIT_PATTERNS["typescript"] = UNIT_PATTERNS["javascript"] + [
    ("interface", re.compile(r"^\s*(?:export\s+)?interface\s+(?P<name>[A-Za-z_$][\w$]*)")),
    ("type", re.compile(r"^\s*(?:export\s+)?type\s+(?P<name>[A-Za-z_$][\w$]*)\s*=")),
]

BRACE_LANGS = {"rust", "javascript", "typescript", "go", "java", "c"}

COMMENT_LINE = {
    "rust": "//", "javascript": "//", "typescript": "//", "go": "//",
    "java": "//", "c": "//", "python": "#",
}

# Enclosing-type push patterns for stable, unique unit IDs: methods inside
# `impl Foo { }` / `class Foo:` become `path::Foo::method`.
IMPL_RE = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:unsafe\s+)?impl(?:<[^>]*>)?\s+(?:(?:[A-Za-z_]\w*(?:::\w+)?)\s+for\s+)?([A-Za-z_]\w*)")
CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_]\w*)")


def strip_strings_comments(line: str, lang: str, in_block: bool) -> tuple[str, bool]:
    """Remove string literals and comments for brace counting.

    Returns (cleaned_line, in_block_comment) — the caller threads the
    block-comment state across lines. Good enough for unit-boundary
    detection, not a lexer.
    """
    out = []
    i = 0
    marker = COMMENT_LINE.get(lang, "//")
    while i < len(line):
        ch = line[i]
        nxt = line[i + 1] if i + 1 < len(line) else ""
        if in_block:
            if ch == "*" and nxt == "/":
                in_block = False
                i += 2
            else:
                i += 1
            continue
        if ch == "/" and nxt == "*":
            in_block = True
            i += 2
            continue
        if line.startswith(marker, i):
            break
        if ch in "\"'`":
            quote = ch
            i += 1
            while i < len(line) and line[i] != quote:
                i += 2 if line[i] == "\\" else 1
            i += 1
            out.append(" ")
            continue
        out.append(ch)
        i += 1
    return "".join(out), in_block


# ---------------------------------------------------------------------------
# unit-end scanners, one per language family (registered, not branched)


def _scan_python_end(lines: list[str], start: int, lang: str) -> int:
    m = re.match(r"^(\s*)", lines[start])
    base_indent = len(m.group(1))
    end = start
    for i in range(start + 1, len(lines)):
        text = lines[i]
        if text.strip() == "":
            end = i
            continue
        indent = len(text) - len(text.lstrip())
        if indent <= base_indent:
            break
        end = i
    return end + 1


def _scan_brace_end(lines: list[str], start: int, lang: str) -> int:
    depth = 0
    seen_open = False
    in_block = False
    for i in range(start, len(lines)):
        cleaned, in_block = strip_strings_comments(lines[i], lang, in_block)
        depth += cleaned.count("{")
        if "{" in cleaned:
            seen_open = True
        depth -= cleaned.count("}")
        if seen_open and depth <= 0:
            return i + 1
        # declaration without body (e.g. trait method sig, `type X = ...;`)
        if not seen_open and cleaned.rstrip().endswith(";"):
            return i + 1
    return len(lines)


SCANNERS = {"python": _scan_python_end, **{lang: _scan_brace_end for lang in BRACE_LANGS}}


def find_unit_end(lines: list[str], start: int, lang: str) -> int:
    """Return the 1-based end line of the unit starting at `start` (0-based idx)."""
    scanner = SCANNERS.get(lang)
    return scanner(lines, start, lang) if scanner else start + 1


# ---------------------------------------------------------------------------
# enclosing-type contexts: one scope-stack scan, parameterized per language


def _brace_scope(lines: list[str], lang: str, push_re: re.Pattern) -> dict[int, str]:
    result: dict[int, str] = {}
    stack: list[tuple[str, int]] = []  # (name, brace depth at entry)
    depth = 0
    in_block = False
    for i, line in enumerate(lines):
        cleaned, in_block = strip_strings_comments(line, lang, in_block)
        m = push_re.match(line)
        if stack:
            result[i + 1] = stack[-1][0]
        if m:
            stack.append((m.group(1), depth))
        depth += cleaned.count("{") - cleaned.count("}")
        while stack and depth <= stack[-1][1] and ("}" in cleaned):
            stack.pop()
    return result


def _indent_scope(lines: list[str], lang: str, push_re: re.Pattern) -> dict[int, str]:
    result: dict[int, str] = {}
    stack: list[tuple[str, int]] = []  # (name, indent at entry)
    for i, line in enumerate(lines):
        if not line.strip():
            if stack:
                result[i + 1] = stack[-1][0]
            continue
        indent = len(line) - len(line.lstrip())
        while stack and indent <= stack[-1][1]:
            stack.pop()
        if stack:
            result[i + 1] = stack[-1][0]
        m = push_re.match(line)
        if m:
            stack.append((m.group(1), indent))
    return result


SCOPE_SCANS = {
    "rust": (IMPL_RE, _brace_scope),
    "python": (CLASS_RE, _indent_scope),
}


def enclosing_contexts(lines: list[str], lang: str) -> dict[int, str]:
    """Map 1-based line number -> innermost enclosing type name."""
    spec = SCOPE_SCANS.get(lang)
    if not spec:
        return {}
    push_re, scan = spec
    return scan(lines, lang, push_re)


# Per-language signature body-openers: the char that ends a signature at
# paren depth 0. Brace languages end at `{`; python at `:`. Add a language
# here, not as a branch inside extract_signature.
SIG_OPENERS = {"python": ":"}
DEFAULT_SIG_OPENER = "{"

# ---------------------------------------------------------------------------
# signatures, hashes, bodies


def unit_id(path: str, name: str) -> str:
    """The one owner of the unit-ID format (`path::name`) — ledger keys,
    rename matching, and briefs all derive from this."""
    return f"{path}::{name}"

BODY_CAP_LINES = 120
TRUNCATION_MARKER = "# ... (truncated)"


def truncate_body(body: str) -> tuple[str, bool]:
    """The one body-cap policy: BODY_CAP_LINES plus a marker comment."""
    lines = body.splitlines()
    if len(lines) <= BODY_CAP_LINES:
        return body, False
    return "\n".join(lines[:BODY_CAP_LINES]) + "\n" + TRUNCATION_MARKER, True


def extract_signature(body: str, lang: str) -> str:
    """The unit's signature: up to the body opener (`{` for brace
    languages, `:` for python — SIG_OPENERS) or the closing `;` of a
    declaration. Paren-depth-aware so annotations and defaults survive.
    """
    opener = SIG_OPENERS.get(lang, DEFAULT_SIG_OPENER)
    depth = 0
    out = []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and ch == opener:
            break
        out.append(ch)
        if ch == ";" and depth == 0:
            break
    return " ".join("".join(out).split())[:400]


def content_hash(text: str) -> str:
    """Whitespace-insensitive content hash (ledger key component)."""
    norm = "\n".join(line.rstrip() for line in text.strip().splitlines() if line.strip())
    return hashlib.sha256(norm.encode()).hexdigest()[:16]


def signature_hash(signature: str) -> str:
    return hashlib.sha256(" ".join(signature.split()).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# unit inventory


def extract_units(path: str, content: str) -> list[dict]:
    """Extract unit inventory from a file's content. Every unit carries
    the full record shape (flags False — _mark_changed in facts.py is the
    only flag-flipper) so downstream code never patches missing keys."""
    lang = LANG_BY_EXT.get(os.path.splitext(path)[1])
    if not lang or lang == "markdown":
        return []
    lines = content.splitlines()
    patterns = UNIT_PATTERNS.get(lang, [])
    enclosing = enclosing_contexts(lines, lang)
    seen: dict[str, int] = {}
    units: list[dict] = []
    for idx, line in enumerate(lines):
        for kind, pat in patterns:
            m = pat.match(line)
            if not m:
                continue
            name = m.group("name")
            ctx = enclosing.get(idx + 1)
            qual = f"{ctx}::{name}" if ctx and kind == "fn" else name
            count = seen.get(qual, 0)
            seen[qual] = count + 1
            if count:
                qual = f"{qual}#{count + 1}"
            start = idx + 1
            end = find_unit_end(lines, idx, lang)
            body = "\n".join(lines[idx:end])
            signature = extract_signature(body, lang)
            capped, truncated = truncate_body(body)
            units.append(
                {
                    "id": unit_id(path, qual),
                    "path": path,
                    "kind": kind,
                    "name": qual,
                    "start": start,
                    "end": end,
                    "signature": signature,
                    "signature_hash": signature_hash(signature),
                    "hash": content_hash(body),
                    "body": capped,
                    "body_truncated": truncated,
                    "changed": False,
                    "is_new": False,
                    "signature_changed": False,
                }
            )
            break
    units.sort(key=lambda u: (u["start"], -(u["end"])))
    return units


def file_unit(path: str, content: str) -> dict:
    """Whole-file fallback unit for code files with no extractable units."""
    lines = content.splitlines()
    body, truncated = truncate_body(content)
    return {
        "id": unit_id(path, "__file__"),
        "path": path,
        "kind": "file",
        "name": "__file__",
        "start": 1,
        "end": len(lines),
        "signature": "",
        "signature_hash": "",
        "hash": content_hash(content),
        "body": body,
        "body_truncated": truncated,
        "changed": False,
        "is_new": False,
        "signature_changed": False,
    }
