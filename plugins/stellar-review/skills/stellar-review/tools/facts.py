#!/usr/bin/env python3
"""stellar-review facts extractor (ADR-0271).

Computes the deterministic facts pack for a review round — changed files,
unit inventory (functions/types with stable IDs and content hashes), site
index, similarity groups, and module dependency edges — and writes it to
.stellar/facts.json. Pure Python stdlib; byte-identical output for
identical input.

This module owns the git side (diffs, blobs, greps). The language side
(unit extraction, signatures, hashing) lives in units.py; near-duplicate
detection in similar.py.

Every git diff this module and incremental.py run carries
--no-ext-diff --no-textconv plus the core.fsmonitor and core.pager
per-invocation pins: facts recomputation runs inside token-bearing post
steps (the stellar and per-kind lanes recompute the facts after the
shell-capable model step), where a model-written
diff.external, diff.<driver>.command, or core.fsmonitor in .git/config —
planted during the model step or re-added by a persistent model-spawned
child between git calls — would otherwise execute during the diff (the
fsmonitor hook fires on the index refresh `git diff` performs).

Usage:
    facts.py [--base SHA] [--head SHA] [--out PATH] [--repo DIR]
             [--include-units-file PATH]

Defaults: --base is `git merge-base HEAD origin/main` (falling back to
`main`; the `STELLAR_BASE_REF` environment variable overrides both, for
repos whose default branch is not main), --head is HEAD, --out is
.stellar/facts.json under the repo root. CI passes --base/--head
explicitly from the pull-request payload (shallow checkouts have no
merge base).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fileout import ensure_parent  # noqa: E402
from similar import similarity_groups  # noqa: E402
from units import (  # noqa: E402
    LANG_BY_EXT,
    content_hash,
    extract_units,
    file_unit,
    is_test_path,
    unit_id,
)

VERSION = 1

# ---------------------------------------------------------------------------
# git helpers


def git(repo: str, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", repo, *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return out.stdout.decode("utf-8", errors="replace")


def default_base(repo: str) -> str:
    # STELLAR_BASE_REF (e.g. origin/master) comes first when set, so a
    # repo whose default branch is not main resolves its real merge base.
    candidates = [os.environ.get("STELLAR_BASE_REF"), "origin/main", "main"]
    for ref in (r for r in candidates if r):
        try:
            return git(repo, "merge-base", "HEAD", ref).strip()
        except subprocess.CalledProcessError:
            continue
    raise SystemExit(
        "facts.py: cannot resolve a merge base; pass --base explicitly "
        "(or set STELLAR_BASE_REF to your default-branch remote ref)"
    )


# ---------------------------------------------------------------------------
# main extraction


def _units_or_file(path: str, content: str) -> list[dict]:
    """The one fallback policy: extractable units, else a whole-file unit
    for non-docs code files."""
    units = extract_units(path, content)
    if not units and not is_docs(path):
        units = [file_unit(path, content)]
    return units


def _file_facts(repo: str, base: str, head: str, row: tuple[str, str, str],
                status: dict[str, tuple[str, str | None]]) -> tuple[dict, list[dict], list[dict], list[dict]]:
    """One changed file: record, head units, base units, sites."""
    added_s, deleted_s, path = row
    if added_s == "-":  # binary
        added_n = deleted_n = 0
    else:
        added_n, deleted_n = int(added_s), int(deleted_s)
    st, old_path = status.get(path, ("m", None))
    base_path = old_path or path

    file_diff = git(repo, "-c", "core.fsmonitor=", "-c", "core.pager=cat", "diff", "--no-ext-diff", "--no-textconv", "--unified=0", base, head, "--", base_path, path)
    added_lines, ranges = parse_file_diff(file_diff)

    record = {
        "path": path,
        "status": st,
        "old_path": old_path,
        "added": added_n,
        "deleted": deleted_n,
        "lines_now": None,
        "lines_base": None,
        "crossed_1k": False,
        "content_hash": None,
        "kind": LANG_BY_EXT.get(os.path.splitext(path)[1], "other"),
        "is_docs": is_docs(path),
        "is_test": is_test_path(path),
        "hunks": ranges,
    }
    if st == "d":
        return record, [], [], []

    # A head-side read failure must never silently reclassify a live
    # file: units would vanish from the round, the one direction this
    # pipeline promises not to degrade toward.
    head_content = git(repo, "show", f"{head}:{path}")
    record["lines_now"] = len(head_content.splitlines())

    base_content = ""
    if st != "a":
        try:
            base_content = git(repo, "show", f"{base}:{base_path}")
        except subprocess.CalledProcessError:
            # fail-open for sealing (units read as new/changed), but
            # loud — an unreadable base blob must leave a trace
            print(f"facts.py: warning: cannot read base blob {base_path}",
                  file=sys.stderr)

    base_units: list[dict] = []
    if base_content:
        record["lines_base"] = len(base_content.splitlines())
        base_units = _units_or_file(base_path, base_content)
        # Renames register base units under the NEW path id, so the
        # sealing comparison just works and deleted_units stays honest.
        if old_path:
            for u in base_units:
                u["id"] = unit_id(path, u["name"])
    # Test files are never size-gated: long table-driven tests are normal,
    # and std-1 is about splitting production code. Their units are still
    # extracted and reviewed.
    record["crossed_1k"] = (not record["is_test"] and record["lines_now"] > 1000
                            and (record["lines_base"] is None or record["lines_base"] <= 1000))

    record["content_hash"] = content_hash(head_content)
    head_units = _units_or_file(path, head_content)
    sites = extract_sites(path, head_content, added_lines, head_units)
    return record, head_units, base_units, sites


def _expansion_units(repo: str, head: str, include_units: list[str],
                     changed_paths: set[str]) -> tuple[list[dict], list[str]]:
    """Full inventory (with bodies) for dependency-dirty files outside the
    diff — unchanged by construction, serving as review context and hash
    baselines."""
    units: list[dict] = []
    expanded: list[str] = []
    for path in include_units:
        if path in changed_paths:
            continue
        try:
            content = git(repo, "show", f"{head}:{path}")
        except subprocess.CalledProcessError:
            print(f"facts.py: warning: cannot expand {path}", file=sys.stderr)
            continue
        units.extend(_units_or_file(path, content))
        expanded.append(path)
    return units, expanded


def _mark_changed(units: list[dict], base_units: dict[str, dict]) -> list[str]:
    """Seal or dirty each diff-file unit against the base inventory. The
    content hash is authoritative: a unit whose normalized body is
    identical to base is sealed even if a diff hunk touched its span.
    Returns the ids of units deleted between base and head."""
    head_ids = set()
    for u in units:
        head_ids.add(u["id"])
        prev = base_units.get(u["id"])
        if prev is not None:
            u["is_new"] = False
            u["changed"] = prev["hash"] != u["hash"]
            u["signature_changed"] = prev["signature_hash"] != u["signature_hash"]
        else:
            u["is_new"] = True
            u["changed"] = True
            u["signature_changed"] = True
    return sorted(uid for uid in base_units if uid not in head_ids)


def body_references(unit: dict, idents: set[str]) -> bool:
    """ADR-0356's other half — the reference predicate, owned beside
    signature_identifiers so the whole 'which units does this change
    touch' policy lives in one language-side place: a unit references
    the change when its body mentions an identifier, or its body is
    truncated (the facts cap) — a truncated body keeps the whole file
    in scope rather than gambling a miss on the unseen text."""
    return unit.get("body_truncated") or any(i in unit["body"] for i in idents)


def signature_identifiers(unit: dict) -> set[str]:
    """ADR-0356: the symbol set a signature change exposes — the unit's
    own name (a Go method's bare name too, so `Config.Run` still matches
    `c.Run(`) plus the signature's capitalized identifiers (Rust naming
    conventions: types, variants, trait names). Language-side knowledge,
    so it lives here in the facts module, not the ledger. Units always
    carry name and signature, and the name alone makes the set
    non-empty — there is no None contract."""
    return {unit["name"], unit["name"].rpartition(".")[2]} | set(
        re.findall(r"[A-Z][A-Za-z0-9_]{2,}", unit["signature"]))


def hunks_by_path(facts_doc: dict) -> dict[str, list[list[int]]]:
    """The per-file hunk table (changed-file record → hunk ranges) — the
    one place the facts document's hunks are read as a map."""
    return {f["path"]: f["hunks"] for f in facts_doc["files"]}


def intersecting_hunk_ends(path: str, start: int, end: int, hbp: dict) -> list[int]:
    """The end lines of the hunks the line range [start, end] intersects,
    in file order — empty when it intersects none. The one spelling of
    the intersection relation."""
    return [e for s, e in hbp.get(path, []) if s <= end and start <= e]


def range_in_hunks(path: str, start: int, end: int, hbp: dict) -> bool:
    """Whether [start, end] intersects a hunk — the boolean face of
    `intersecting_hunk_ends`. Scope computation (ADR-0347) and verdict
    anchoring (ADR-0346) both read it."""
    return bool(intersecting_hunk_ends(path, start, end, hbp))


def build_facts(repo: str, base: str, head: str, include_units: list[str] | None = None) -> dict:
    numstat = git(repo, "-c", "core.fsmonitor=", "-c", "core.pager=cat", "diff", "--no-ext-diff", "--no-textconv", "--numstat", "-z", "--find-renames", base, head)
    name_status = git(repo, "-c", "core.fsmonitor=", "-c", "core.pager=cat", "diff", "--no-ext-diff", "--no-textconv", "--name-status", "-z", "--find-renames", base, head)
    deps = extract_all_deps(repo, head)
    diff_text = git(repo, "-c", "core.fsmonitor=", "-c", "core.pager=cat", "diff", "--no-ext-diff", "--no-textconv", "--find-renames", base, head)
    include_units = include_units or []
    status = parse_name_status_z(name_status)

    files: list[dict] = []
    diff_units: list[dict] = []
    base_units: dict[str, dict] = {}
    sites: list[dict] = []
    for row in parse_numstat_z(numstat):
        record, head_units, base_us, file_sites = _file_facts(repo, base, head, row, status)
        files.append(record)
        diff_units.extend(head_units)
        for u in base_us:
            base_units[u["id"]] = u
        sites.extend(file_sites)

    changed_paths = {f["path"] for f in files}
    expansion, expanded = _expansion_units(repo, head, include_units, changed_paths)
    deleted_units = _mark_changed(diff_units, base_units)

    units = sorted(diff_units + expansion, key=lambda u: u["id"])
    files.sort(key=lambda f: f["path"])
    sites.sort(key=lambda s: (s["path"], s["line"], s["kind"]))

    changed_units = [u for u in diff_units if u["changed"] or u["is_new"]]
    return {
        "version": VERSION,
        "base": base,
        "head": head,
        "diff_text": diff_text,
        "has_code_changes": any(not f["is_docs"] for f in files),
        "files": files,
        "units": units,
        "changed_units": [u["id"] for u in changed_units],
        "deleted_units": deleted_units,
        "sites": sites,
        "similarity": similarity_groups(changed_units),
        "deps": deps,
        "expanded_unit_files": sorted(expanded),
    }


def parse_name_status_z(raw: str) -> dict[str, tuple[str, str | None]]:
    """`git diff --name-status -z`: path -> (status, old_path|None)."""
    toks = raw.split("\0")
    out: dict[str, tuple[str, str | None]] = {}
    i = 0
    while i < len(toks):
        code = toks[i]
        if not code:
            i += 1
            continue
        if code[0] in ("R", "C"):
            out[toks[i + 2]] = ("renamed" if code[0] == "R" else "copied", toks[i + 1])
            i += 3
        else:
            out[toks[i + 1]] = (code[0].lower(), None)
            i += 2
    return out


def parse_numstat_z(raw: str) -> list[tuple[str, str, str]]:
    """`git diff --numstat -z`: [(added, deleted, new_path)].

    Rename rows carry an empty path field followed by old/new path tokens.
    """
    toks = raw.split("\0")
    out: list[tuple[str, str, str]] = []
    i = 0
    while i < len(toks):
        tok = toks[i]
        if not tok.strip():
            i += 1
            continue
        parts = tok.split("\t")
        if len(parts) >= 3 and parts[2]:
            out.append((parts[0], parts[1], parts[2]))
            i += 1
        else:
            out.append((parts[0], parts[1], toks[i + 2]))
            i += 3
    return out


HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def parse_file_diff(diff_text: str) -> tuple[set[int], list[list[int]]]:
    """Parse one file's unified diff.

    Returns (added_lines, changed_ranges): added_lines are 1-based line
    numbers in the NEW file introduced by `+` lines; changed_ranges are
    [start, end] new-file ranges of each hunk (a deletion-only hunk
    contributes the line it anchored at).
    """
    added: set[int] = set()
    ranges: list[list[int]] = []
    new_line = 0
    hunk_start = None
    hunk_end = None
    in_hunk = False
    for line in diff_text.splitlines():
        m = HUNK_RE.match(line)
        if m:
            if hunk_start is not None:
                ranges.append([hunk_start, max(hunk_end, hunk_start)])
            new_line = int(m.group(1))
            hunk_start = new_line
            hunk_end = new_line - 1
            in_hunk = True
            continue
        if not in_hunk:
            continue  # diff --git / --- / +++ file headers
        if line.startswith("\\"):
            continue  # "\ No newline at end of file" metadata
        if line.startswith("+"):
            added.add(new_line)
            hunk_end = new_line
            new_line += 1
        elif line.startswith("-"):
            pass  # deletion: no new-file line consumed
        else:
            hunk_end = new_line
            new_line += 1
    if hunk_start is not None:
        ranges.append([hunk_start, max(hunk_end, hunk_start)])
    return added, ranges


# ---------------------------------------------------------------------------
# site extraction

GO_CODE = r"^(?!\s*//).*?"  # a Go code line: not comment-only

SITE_PATTERNS = [
    ("silent_fallback", re.compile(r"\.ok\(\)\s*;|let\s+_\s*=|\.catch\s*\(\s*\(\s*\)\s*=>\s*\{\s*\}\s*\)"), {"rust", "typescript", "javascript"}),
    ("unwrap", re.compile(r"\.unwrap\(\)"), {"rust"}),
    ("expect", re.compile(r"\.expect\("), {"rust"}),
    ("as_cast", re.compile(r"\bas\s+(?:u8|u16|u32|u64|u128|usize|i8|i16|i32|i64|i128|isize|f32|f64)\b"), {"rust"}),
    ("ts_any", re.compile(r"\bas\s+(?:any|unknown)\b|:\s*any\b"), {"typescript", "javascript"}),
    ("bool_param", re.compile(r"\w+\s*:\s*bool\b|\w+[?]?:\s*boolean\b"), {"rust", "typescript", "javascript"}),
    ("option_param", re.compile(r"\w+\s*:\s*Option<|\w+\?\s*:"), {"rust", "typescript"}),
    ("new_pub", re.compile(r"^\s*pub(?:\([^)]*\))?\s+(?:fn|struct|enum|trait|mod|type|const|static)\b|^\s*export\s+(?:function|class|const|interface|type)\b"), {"rust", "typescript", "javascript"}),
    ("new_branch", re.compile(r"^\s*(?:if\b|else\s+if\b|match\b|switch\b|case\b|for\b|while\b)"), {"rust", "python", "typescript", "javascript", "go", "java", "c"}),
    ("new_await", re.compile(r"\.await\b|^\s*await\s"), {"rust", "typescript", "javascript"}),
    ("new_lock", re.compile(r"\bMutex\b|\bRwLock\b|\.lock\(\)|\.read\(\)|\.write\(\)"), {"rust"}),
    # Go. Textual, so types are not resolved: `_ = f()` and a trailing `, _ := f()`
    # count as dropped errors; `defer f.Close()`, a bare `f()` statement and a
    # leading `_, x := f()` are not seen. Comment-only lines never match.
    ("ignored_error", re.compile(r"^\s*_\s*=\s*[A-Za-z_][\w.]*\(|^\s*(?:(?:if|switch)\s+)?\w+(?:\s*,\s*\w+)*\s*,\s*_\s*:?=\s*[A-Za-z_][\w.]*\("), {"go"}),
    ("go_any", re.compile(GO_CODE + r"(?:[\s(\[\],*]any\b(?=\s*(?:[,)\]{}=]|$))|\binterface\s*\{\s*\})"), {"go"}),
    ("unchecked_assert", re.compile(r"^(?!.*,\s*\w+\s*:?=.*\.\()" + GO_CODE + r"\.\((?!type\))\*?[\w.\[\]]+\)"), {"go"}),
    ("panic", re.compile(GO_CODE + r"\bpanic\("), {"go"}),
    ("go_lock", re.compile(GO_CODE + r"(?:\bsync\.(?:RW)?Mutex\b|\.R?Lock\(\))"), {"go"}),
    ("goroutine", re.compile(r"^\s*go\s+(?:func\b|[A-Za-z_][\w.]*\()"), {"go"}),
]


def extract_sites(path: str, content: str, added_lines: set[int], units: list[dict]) -> list[dict]:
    lang = LANG_BY_EXT.get(os.path.splitext(path)[1])
    if not lang or lang == "markdown":
        return []
    lines = content.splitlines()
    sites: list[dict] = []
    for lineno in sorted(added_lines):
        if lineno > len(lines):
            continue
        text = lines[lineno - 1]
        for kind, pat, langs in SITE_PATTERNS:
            if lang not in langs or not pat.search(text):
                continue
            sites.append(
                {
                    "kind": kind,
                    "path": path,
                    "line": lineno,
                    "unit": unit_at(units, lineno),
                    "snippet": text.strip()[:200],
                }
            )
    return sites


def unit_at(units: list[dict], lineno: int) -> str | None:
    best = None
    for u in units:
        if u["start"] <= lineno <= u["end"]:
            if best is None or (u["end"] - u["start"]) < (best["end"] - best["start"]):
                best = u
    return best["id"] if best else None


# ---------------------------------------------------------------------------
# dependency edges (module-level; repo-wide via one git grep per language)

USE_RE = {
    "rust": re.compile(r"^\s*(?:pub\s+)?use\s+(crate(?:::[\w:]+)?|relate[\w-]*(?:::[\w:]+)?)"),
    "python": re.compile(r"^\s*(?:from\s+([\w.]+)\s+)?import\s+([\w.]+)"),
    "typescript": re.compile(r"""^\s*import\s+.*from\s+['"]([^'"]+)['"]"""),
    "javascript": re.compile(r"""^\s*import\s+.*from\s+['"]([^'"]+)['"]"""),
    "go": re.compile(r"""^\s*(?:import\s+)?(?:[\w.]+\s+)?"([^"]+)"\s*$"""),
}

# git grep uses POSIX ERE: no \s or \w — use bracket classes.
GREP_PATTERNS = [
    (["*.rs"], r"^[[:space:]]*(pub[[:space:]]+)?use[[:space:]]+(crate::|relate)"),
    (["*.ts", "*.tsx", "*.js", "*.jsx", "*.mjs"], r"^[[:space:]]*import[[:space:]].*from[[:space:]]+['\"]"),
    (["*.py"], r"^[[:space:]]*(from[[:space:]]+[A-Za-z0-9_.]+[[:space:]]+)?import[[:space:]]+"),
    # Go imports: `import "x"`, `import alias "x"`, and the lines of an
    # `import ( ... )` block. A lone quoted line elsewhere is dropped later
    # because it does not resolve to an in-repo package.
    (["*.go"], r"^[[:space:]]*(import[[:space:]]+)?([A-Za-z0-9_.]+[[:space:]]+)?\"[^\"]+\"[[:space:]]*$"),
]

GO_MODULE_RE = re.compile(r"^\s*module\s+(\S+)", re.M)


def go_module_path(repo: str, head: str) -> str | None:
    """The module path from the root go.mod (nested modules are not seen)."""
    try:
        m = GO_MODULE_RE.search(git(repo, "show", f"{head}:go.mod"))
    except subprocess.CalledProcessError:
        return None
    return m.group(1).strip('"') if m else None


def resolve_go_import(imp: str, module: str | None) -> str | None:
    """An import of an in-repo package becomes its repo-relative directory
    (`mod/internal/foo` -> `internal/foo`); standard-library, third-party
    and root-package imports resolve to None and are not edges."""
    if module and imp.startswith(module + "/"):
        return imp[len(module) + 1:]
    return None


# Per-language import resolution: (import text, language context) -> edge
# target, or None to drop it. Languages not listed keep the raw import.
IMPORT_RESOLVERS = {"go": resolve_go_import}


def extract_all_deps(repo: str, head: str) -> dict[str, list[str]]:
    """Import edges for EVERY source file at head, via one git grep per
    language — dependent invalidation (ADR-0271) needs edges for files
    that are not themselves in the diff."""
    deps: dict[str, set[str]] = {}
    contexts = {"go": go_module_path(repo, head)}
    for globs, pattern in GREP_PATTERNS:
        try:
            out = git(repo, "grep", "-n", "-E", pattern, head, "--", *globs)
        except subprocess.CalledProcessError:
            continue  # no matches for this language
        for line in out.splitlines():
            # format: <sha>:<path>:<lineno>:<content>
            parts = line.split(":", 3)
            if len(parts) < 4:
                continue
            path, text = parts[1], parts[3]
            lang = LANG_BY_EXT.get(os.path.splitext(path)[1])
            pat = USE_RE.get(lang or "")
            if not pat:
                continue
            m = pat.match(text)
            if m:
                imp = next(g for g in m.groups() if g)
                resolve = IMPORT_RESOLVERS.get(lang)
                target = resolve(imp, contexts.get(lang)) if resolve else imp
                if target:
                    deps.setdefault(path, set()).add(target)
    return {p: sorted(d) for p, d in sorted(deps.items())}


# ---------------------------------------------------------------------------
# docs-only classification

DOCS_PATH = re.compile(r"^(?:docs/|website/|\.github/|README|AGENTS\.md|CHANGELOG|LICENSE)")

# Source files living under docs-classified directories: the API
# surfaces' runnable examples (compiled and executed by CI — doctests,
# client integration builds) are code in every sense that matters for
# classification; a .rs under docs/ is a code change, not a docs edit.
DOCS_CODE_EXT = (".rs", ".c", ".h", ".py", ".sh", ".js", ".ts", ".java", ".go", ".rb", ".swift")


def is_docs(path: str) -> bool:
    if path.endswith(DOCS_CODE_EXT):
        return False
    if DOCS_PATH.match(path):
        return True
    return path.endswith((".md", ".mdx", ".txt", ".svg", ".png", ".mermaid"))




def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", help="base SHA (default: merge-base HEAD origin/main; STELLAR_BASE_REF overrides)")
    ap.add_argument("--head", default="HEAD", help="head SHA (default: HEAD)")
    ap.add_argument("--out", help="output path (default: <repo>/.stellar/facts.json)")
    ap.add_argument("--stdout-json", action="store_true",
                    help="also print the facts JSON to stdout (a pipe channel: "
                         "gates consume the bytes straight from this process, "
                         "never from the model-writable file on disk; the file "
                         "write is unchanged)")
    ap.add_argument("--repo", default=".", help="repository directory")
    ap.add_argument("--include-units-file",
                    help="file with newline-separated extra paths to inventory "
                         "(dependency-dirty files from ledger scope)")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    head = git(repo, "rev-parse", args.head).strip()
    base = args.base or default_base(repo)
    base = git(repo, "rev-parse", base).strip()

    include: list[str] = []
    if args.include_units_file:
        with open(args.include_units_file) as fh:
            include = [ln.strip() for ln in fh if ln.strip()]
    facts = build_facts(repo, base, head, include_units=include)
    out = ensure_parent(args.out or os.path.join(repo, ".stellar", "facts.json"))
    diff_path = os.path.join(os.path.dirname(out), "diff.patch")
    with open(diff_path, "w") as fh:
        fh.write(facts.pop("diff_text"))
    facts["diff_path"] = diff_path
    with open(out, "w") as fh:
        json.dump(facts, fh, indent=2, sort_keys=True)
        fh.write("\n")
    n_files = len(facts["files"])
    n_units = len(facts["units"])
    n_changed = len(facts["changed_units"])
    summary = (f"facts: {n_files} files, {n_units} units ({n_changed} changed), "
               f"{len(facts['sites'])} sites, {len(facts['similarity'])} similar pairs -> {out}")
    if args.stdout_json:
        # Pipe mode: stdout carries ONLY the JSON, as its final content —
        # the consumer parses the first JSON value from the stream, so
        # nothing may follow it. The summary rides stderr (both land in
        # the job log).
        print(summary, file=sys.stderr)
        sys.stdout.write(json.dumps(facts, indent=2, sort_keys=True) + "\n")
    else:
        print(summary)


if __name__ == "__main__":
    main()
