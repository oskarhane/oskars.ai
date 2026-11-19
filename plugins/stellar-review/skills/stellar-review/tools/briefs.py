"""stellar-review brief generation (ADR-0271).

One deterministic markdown brief per review pass (chunked on big rounds):
a pass agent reads its brief plus the doctrine references and nothing
else — no diff searching, no file exploration. Pass layouts are
descriptors in PASS_LAYOUT; add a pass or a section by extending tables,
not by branching.
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from units import LANG_BY_EXT  # noqa: E402

# which site kinds each pass owns (comparison gets clusters, not ownership)
SITE_OWNERS = {
    "branching": {"new_branch", "bool_param", "option_param"},
    "boundaries": {"silent_fallback", "unwrap", "expect", "as_cast", "ts_any",
                   "new_pub", "new_await", "new_lock"},
}

BRIEF_CHUNK_UNITS = 200
# The one spelling of a brief file's name vocabulary: emit writes the
# files and the stale-file sweep in write_briefs recognizes ours by the
# same prefix/suffix — never a second derivation of the naming.
BRIEF_FILE_PREFIX = "brief-"
BRIEF_FILE_SUFFIX = ".md"


def brief_filename(pass_name: str, suffix: str) -> str:
    return f"{BRIEF_FILE_PREFIX}{pass_name}{suffix}{BRIEF_FILE_SUFFIX}"

NO_FENCE = {"markdown"}


def fence_for(path: str) -> str:
    """Markdown fence label from the canonical extension→language table."""
    lang = LANG_BY_EXT.get(os.path.splitext(path)[1])
    return "" if lang is None or lang in NO_FENCE else lang


def unquote_diff_path(token: str) -> str:
    """Git quotes diff-header paths containing spaces or non-ASCII bytes
    (`"b/x y.rs"`, octal-escaped UTF-8 like `"b/caf\303\251.rs"`); the
    slice match must see the raw path. unicode_escape yields latin-1 code
    points for octal escapes, so round-trip back through bytes."""
    if not (token.startswith('"') and token.endswith('"')):
        return token
    unescaped = bytes(token[1:-1], "utf-8").decode("unicode_escape")
    try:
        return unescaped.encode("latin-1").decode("utf-8")
    except UnicodeError:
        return unescaped


DIFF_TOKEN_RE = re.compile(r'"(?:[^"\\]|\\.)*"|\S+')


def diff_sections(diff_text: str) -> list[tuple[str, list[str]]]:
    """Split a multi-file patch into `(b_path, section_lines)` pairs, in
    order. Headers are `diff --git <a-token> <b-token>` where a token is
    bare or "-quoted; the b/ path is unquoted and stripped. A malformed
    header (fewer than 2 tokens) warns loudly and starts no section —
    a silent section miss shrinks review scope."""
    sections: list[tuple[str, list[str]]] = []
    cur: list[str] | None = None
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            toks = DIFF_TOKEN_RE.findall(line[len("diff --git "):])
            if len(toks) < 2:
                print(f"briefs: warning: malformed diff header: {line!r}", file=sys.stderr)
                cur = None
                continue
            cur = []
            sections.append((unquote_diff_path(toks[1]).removeprefix("b/"), cur))
        if cur is not None:
            cur.append(line)
    return sections


def slice_diff(diff_text: str, paths: set[str]) -> tuple[str, list[str]]:
    """The `diff --git` sections for exactly the given paths, plus the
    sorted scoped paths that matched no section. Callers must handle the
    miss list — a silent slice miss shrinks review scope."""
    out, seen = [], set()
    for b_path, lines in diff_sections(diff_text):
        if b_path in paths:
            seen.add(b_path)
            out += lines
    return "\n".join(out), sorted(paths - seen)


def unit_block(u: dict) -> list[str]:
    flags = ", ".join(x for x, v in (("new", u["is_new"]), ("changed", u["changed"]),
                                     ("signature changed", u.get("signature_changed"))) if v) or "context"
    lines = [f"### `{u['id']}` — {u['kind']}, lines {u['start']}–{u['end']} ({flags})"]
    if u.get("signature"):
        lines.append(f"signature: `{u['signature']}`")
    lines += [f"```{fence_for(u['path'])}", u["body"], "```", ""]
    return lines


def chunk_units(review_units: list[dict], cap: int | None) -> list[list[dict]]:
    """Split a large round-1 scope into fixed-size chunks over the units
    ordered by top-level directory (stable sort — a directory's units stay
    adjacent; one chunk may straddle two directories at a boundary).
    cap=None disables chunking: the whole set is one chunk however big —
    the quick local round's one-brief-per-pass shape. cap is required
    here: the default policy lives on write_briefs' signature, the one
    home for it (pass_plan's docstring points there)."""
    if cap is None or len(review_units) <= cap:
        return [review_units]
    ordered = sorted(review_units, key=lambda u: u["path"].split("/", 1)[0])
    return [ordered[i:i + cap] for i in range(0, len(ordered), cap)]


# ---------------------------------------------------------------------------
# section builders — each takes the brief context dict and returns
# markdown lines. Keys: facts, scope, units, chunk, paths, sites, scope_diff


def sec_file_facts(ctx):
    facts, paths = ctx["facts"], ctx["paths"]
    sec = ["## File facts", ""]
    for f in facts["files"]:
        if f["is_docs"] or f["path"] not in paths:
            continue
        cross = " — **crossed 1000 lines this PR**" if f["crossed_1k"] else ""
        sec.append(f"- `{f['path']}`: {f['status']}, +{f['added']}/-{f['deleted']}, "
                   f"{f['lines_base']} → {f['lines_now']} lines{cross}")
    return sec + [""]


def sec_dep_edges(ctx):
    facts, paths = ctx["facts"], ctx["paths"]
    sec = ["## Module dependency edges (scope files)", ""]
    for p in sorted(paths):
        for d in facts.get("deps", {}).get(p, []):
            sec.append(f"- `{p}` imports `{d}`")
    return sec + [""]


def sec_units(ctx):
    sec = ["## Units in scope", ""]
    for u in ctx["chunk"]:
        sec += unit_block(u)
    return sec


def make_sec_sites(title: str, kinds: set[str]):
    def build(ctx):
        sec = [f"## {title}", ""]
        for s in ctx["sites"]:
            if s["kind"] in kinds:
                sec.append(f"- {s['kind']} `{s['path']}:{s['line']}` (unit `{s['unit']}`) — `{s['snippet']}`")
        return sec + [""]
    return build


def sec_diff(ctx):
    if not ctx["scope_diff"]:
        return []
    return ["", "## Diff hunks for scope files", "", "```diff", ctx["scope_diff"], "```"]


def sec_similar_pairs(ctx):
    facts, scope, units = ctx["facts"], ctx["scope"], ctx["units"]
    sec = ["## Similar units (judge: duplicate or justified?)", ""]
    review_ids = set(scope["review_units"])
    for pair in facts.get("similarity", []):
        a, b = units.get(pair["a"]), units.get(pair["b"])
        if not a or not b:
            continue
        if a["id"] not in review_ids and b["id"] not in review_ids:
            continue
        sec.append(f"### `{pair['a']}` ↔ `{pair['b']}` (similarity {pair['score']})")
        sec += unit_block(a) + unit_block(b)
    return sec


def sec_site_clusters(ctx):
    sec = ["## Site clusters (judge: consistent policy across similar sites?)", ""]
    by_kind: dict[str, list[dict]] = {}
    for s in ctx["sites"]:
        by_kind.setdefault(s["kind"], []).append(s)
    for kind, group in sorted(by_kind.items()):
        if len(group) < 2:
            continue
        sec.append(f"### {kind} × {len(group)}")
        for s in group:
            sec.append(f"- `{s['path']}:{s['line']}` — `{s['snippet']}`")
        sec.append("")
    return sec


def sec_resolution_checks(ctx):
    scope, units = ctx["scope"], ctx["units"]
    if not scope["resolve_checks"]:
        return []
    sec = ["## Resolution checks (closed form: addressed yes/no)", ""]
    for rc in scope["resolve_checks"]:
        u = units.get(rc["unit"])
        sec.append(f"### {rc['finding_id']} — {rc['reason']}")
        if rc.get("summary"):
            sec.append(f"Finding: {rc['summary']}")
        if rc.get("remedy"):
            sec.append(f"Remedy asked: {rc['remedy']}")
        if rc.get("quote"):
            sec += ["Quoted at filing:", "```", rc["quote"], "```"]
        if u:
            sec += unit_block(u)
        else:
            sec.append("(anchor unit gone or file-level — check the file's current state)")
        sec.append("")
    return sec


# A pass descriptor: chunked passes split big rounds per top-level
# directory; global passes (comparison) get one brief over the whole
# scope. Add a pass by adding an entry — write_briefs has no branches.
PASS_LAYOUT = {
    "structure": {"chunked": True,
                  "sections": [sec_file_facts, sec_dep_edges, sec_units, sec_diff]},
    "branching": {"chunked": True,
                  "sections": [sec_units, make_sec_sites("Branch / parameter sites on added lines",
                                                         SITE_OWNERS["branching"]), sec_diff]},
    "boundaries": {"chunked": True,
                   "sections": [make_sec_sites("Sites on added lines", SITE_OWNERS["boundaries"]),
                                sec_units, sec_diff]},
    "comparison": {"chunked": False,
                   "sections": [sec_similar_pairs, sec_site_clusters, sec_resolution_checks]},
}


# ---------------------------------------------------------------------------


def brief_common(scope: dict) -> list[str]:
    s = scope["stats"]
    lines = [
        f"Scope: round {scope['round']} — {s['units_in_scope']}/{s['units_total']} units in scope, "
        f"{s['units_sealed']} sealed.",
        "",
        "Sealed units are decided: you may read them for context but MUST NOT report findings on "
        "them. Review ONLY the units assigned below.",
        "",
    ]
    # (scope key, header, item formatter) — adding a brief section is a
    # table entry, not a new branch.
    blocks = [
        ("open_findings",
         "Already posted, do NOT re-report (still open):",
         lambda f: f"- {f['id']} ({f['severity']}) `{f['path']}` — {f['summary']}"),
        ("waived",
         "Waived by a human, do NOT re-flag:",
         lambda f: f"- {f['id']} `{f['path']}` — {f['summary']} (waiver: {f['reason']})"),
        ("resolved_recent",
         "Resolved in earlier rounds — already litigated: do NOT re-report, "
         "and do NOT contradict the accepted remedy:",
         lambda f: f"- {f['id']} `{f['path']}` — {f['summary']}"
                   + (f" → remedy: {f['remedy']}" if f.get("remedy") else "")),
    ]
    for key, header, fmt in blocks:
        items = scope[key]
        if items:
            lines.append(header)
            lines += [fmt(f) for f in items]
            lines.append("")
    if scope["round"] > 1:
        lines.append(
            "Incremental round: every finding MUST anchor to lines changed since the last "
            "round (the diff hunks below) — a finding on unchanged lines is dropped by the "
            "poster, even when the unit around them is in scope. If a changed hunk makes "
            "unchanged lines wrong, quote the changed lines and explain the causal link in "
            "`why`.")
        lines.append("")
    return lines


def pass_plan(desc: dict, review_units: list[dict], review_paths: set[str],
              diff_text: str, diff_file_paths: set[str],
              cap: int | None) -> list[tuple[list[dict], set[str], str]]:
    """One pass → [(chunk, paths, scope_diff)]. The chunked/global branch
    lives here exactly once, so write_briefs' emit loop is branch-free.
    Slice misses warn only for files that are actually in the diff —
    dependency-expansion units come from unchanged files and legitimately
    have no hunks. cap is required here: the default policy lives on
    write_briefs' signature, this forwarder states no policy of its own."""
    if not desc["chunked"]:
        return [(review_units, review_paths, "")]
    plan = []
    for chunk in chunk_units(review_units, cap):
        paths = {u["path"] for u in chunk}
        scope_diff, missed = slice_diff(diff_text, paths)
        for p in missed:
            if p in diff_file_paths:
                print(f"briefs: warning: no diff section for changed file {p}",
                      file=sys.stderr)
        plan.append((chunk, paths, scope_diff))
    return plan


def write_briefs(facts: dict, scope: dict, diff_text: str, out_dir: str,
                 cap: int | None = BRIEF_CHUNK_UNITS) -> dict[str, str]:
    os.makedirs(out_dir, exist_ok=True)
    units = {u["id"]: u for u in facts["units"]}
    # a scope id missing from facts is a pipeline bug — index directly so
    # it raises loudly, matching the fail-closed stance on slice misses
    review_units = [units[uid] for uid in scope["review_units"]]
    review_paths = set(scope["review_files"]) | set(scope["dependency_dirty_files"])
    sites_all = facts["sites"]

    paths_written: dict[str, str] = {}

    def emit(pass_name: str, chunk_no: int, total_chunks: int,
             sections: list[str]) -> None:
        suffix = ""
        chunk_note = ""
        if total_chunks > 1:
            suffix = f"-{chunk_no}"
            chunk_note = (f"This is chunk {chunk_no} of {total_chunks} in a large round: "
                          f"your assigned units are the subset below. Other chunks are "
                          f"reviewed by sibling passes.\n\n")
        content = "\n".join(
            [f"# stellar-review brief — {pass_name}{suffix} (round {scope['round']})", ""]
            + [chunk_note] + brief_common(scope) + sections)
        path = os.path.join(out_dir, brief_filename(pass_name, suffix))
        with open(path, "w") as fh:
            fh.write(content)
        paths_written[f"{pass_name}{suffix}"] = path

    for pass_name, desc in PASS_LAYOUT.items():
        plan = pass_plan(desc, review_units, review_paths, diff_text,
                         {f["path"] for f in facts["files"]}, cap=cap)
        for i, (chunk, paths, scope_diff) in enumerate(plan):
            ctx = {
                "facts": facts,
                "scope": scope,
                "units": units,
                "chunk": chunk,
                "paths": paths,
                "sites": [s for s in sites_all if s["path"] in paths],
                "scope_diff": scope_diff,
            }
            sections: list[str] = []
            for builder in desc["sections"]:
                sections += builder(ctx)
            emit(pass_name, i + 1, len(plan), sections)

    # The directory reflects exactly the current plan: a previous,
    # differently-shaped round's brief-*.md files are removed, never
    # left behind for a later pass dispatch to pick up — the function
    # that owns the output naming owns the output set.
    written = set(paths_written.values())
    for name in os.listdir(out_dir):
        full = os.path.join(out_dir, name)
        if (name.startswith(BRIEF_FILE_PREFIX) and name.endswith(BRIEF_FILE_SUFFIX)
                and full not in written):
            os.remove(full)

    return paths_written
