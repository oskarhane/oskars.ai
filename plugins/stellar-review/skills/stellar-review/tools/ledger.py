#!/usr/bin/env python3
"""stellar-review cross-round ledger (ADR-0271).

Keeps per-unit state (content hash, open findings) and finding lifecycles
(open / resolved / waived) across review rounds, so round N+1 re-reviews
exactly what changed — never the whole diff again.

Commands:
    scope   Compute the next round's review scope from facts + ledger.
    update  Roll the ledger forward from the round's findings.
    brief   Emit per-pass briefs (delegates to briefs.py).

Usage:
    ledger.py scope --facts F --ledger L --out scope.json
    ledger.py update --facts F --ledger L --findings R [--waive ID:reason ...]
    ledger.py brief --facts F --scope S [--diff diff.patch] [--no-shard] --out DIR

With no --ledger (or a missing file), round 1 is a full review. The ledger
is the only stateful component of the pipeline; CI round-trips it through
the PR summary comment, locally it lives at .stellar/ledger.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import briefs  # noqa: E402
import facts as facts_mod  # noqa: E402
from fileout import ensure_parent  # noqa: E402

VERSION = 1

# ---------------------------------------------------------------------------
# module-path mapping for dependency invalidation (best effort)

CRATE_DIR_RE = re.compile(r"^(?:relate|surfaces|testing)/(relate[\w-]*)/src/(.+)\.rs$")


def rust_module_of(path: str) -> str | None:
    """Map a Rust file path to its module path (crate::foo::bar)."""
    m = CRATE_DIR_RE.match(path)
    if not m:
        return None
    crate = m.group(1).replace("-", "_")
    rest = m.group(2)
    if rest == "lib" or rest == "main":
        return crate
    parts = rest.split("/")
    if parts[-1] == "mod":
        parts.pop()
    return "::".join([crate, *parts])


def module_of(path: str) -> str | None:
    if path.endswith(".rs"):
        return rust_module_of(path)
    # Other languages: the file path itself is the importable identity for
    # relative-import matching (TS `./foo`, Python `.foo`).
    stem, _ = os.path.splitext(path)
    return stem


def crate_of(path: str) -> str | None:
    m = CRATE_DIR_RE.match(path)
    return m.group(1).replace("-", "_") if m else None


def module_candidates(imp: str, importer_path: str) -> set[str]:
    """The module identities one import could refer to, with all `::`
    prefixes — so matching against a signature-changed module set is a
    plain set intersection, and new import forms are added here exactly
    once."""
    norm = imp.replace("-", "_").rstrip(":")
    bases = {norm}
    if norm.startswith("crate::"):
        crate = crate_of(importer_path)
        if crate:
            bases.add(crate + "::" + norm[len("crate::"):])
    elif norm.startswith("."):
        # relative TS/Python import: resolve against the importer's dir
        bases.add(os.path.normpath(os.path.join(os.path.dirname(importer_path), norm)))
    elif "/" in norm:
        bases.add(norm.split("/")[-1])
    out: set[str] = set()
    for b in bases:
        parts = b.split("::")
        for i in range(1, len(parts) + 1):
            out.add("::".join(parts[:i]))
    return out


def dependency_dirty_files(facts: dict, led: dict) -> set[str]:
    """Files whose imports reference a module with a signature-changed unit.

    Signature change is judged against the LEDGER (previous round), not
    the merge base — a body-only change never invalidates dependents; a
    public-signature change does (ADR-0271 decision 2).
    """
    sig_changed_modules = set()
    for u in signature_changed_units(facts, led):
        mod = module_of(u["path"])
        if mod:
            sig_changed_modules.add(mod)
    if not sig_changed_modules:
        return set()
    dirty: set[str] = set()
    for path, imports in facts.get("deps", {}).items():
        for imp in imports:
            if module_candidates(imp, path) & sig_changed_modules:
                dirty.add(path)
                break
    return dirty


def signature_changed_units(facts: dict, led: dict) -> list[dict]:
    """The one walk of the signature-changed units (ADR-0356): every
    consumer of that set — the file-level and unit-level expansions —
    reads this list, never a second filtered walk of facts["units"]."""
    return [u for u in facts["units"] if signature_fires(u, led)]


def signature_fires(unit: dict, led: dict) -> bool:
    """The one signature-change predicate (dependency_dirty_files' inner
    test, named): a unit whose signature changed vs the ledger — or vs
    the merge base when new to the ledger, never a brand-new unit."""
    prev_sig = unit_sig_hash(led, unit["id"])
    if prev_sig is not None:
        # units always carry signature_hash (facts sets it on both paths)
        return prev_sig != unit["signature_hash"]
    return bool(unit.get("signature_changed")) and not unit.get("is_new")


def dependency_dirty_units(facts: dict, led: dict, dirty_files: set[str]) -> set[str]:
    """ADR-0356: unit-granular expansion — the unit ids of the dirty files
    that join scope: a dirty file's units whose body references a changed
    unit's identifier (facts.signature_identifiers, the language-side
    home). The whole-file fallback stays internal: every unit of a dirty
    file joins when its body is truncated (the facts cap)."""
    if not dirty_files:
        return set()
    idents: set[str] = set()
    for u in signature_changed_units(facts, led):
        idents |= facts_mod.signature_identifiers(u)
    return {u["id"] for u in facts["units"]
            if u["path"] in dirty_files
            and facts_mod.body_references(u, idents)}


# ---------------------------------------------------------------------------
# ledger IO


def empty_ledger() -> dict:
    # units map uid -> "hash:signature_hash" (compact — the comment blob
    # must stay far under GitHub's 65536-char limit on monster PRs)
    return {"version": VERSION, "rounds": 0, "last_head": None, "units": {},
            "findings": {}, "resolved_tail": []}


def unit_hash(led: dict, uid: str) -> str | None:
    v = led["units"].get(uid)
    return v.split(":", 1)[0] if v else None


def unit_sig_hash(led: dict, uid: str) -> str | None:
    v = led["units"].get(uid)
    return v.split(":", 1)[1] if v else None


def load_ledger(path: str | None) -> dict:
    if not path or not os.path.exists(path):
        return empty_ledger()
    with open(path) as fh:
        led = json.load(fh)
    if led.get("version") != VERSION:
        raise SystemExit(f"ledger.py: unsupported ledger version {led.get('version')}")
    return led


def save_ledger(led: dict, path: str) -> None:
    path = ensure_parent(path)
    with open(path, "w") as fh:
        json.dump(led, fh, indent=1, sort_keys=True)
        fh.write("\n")


def trim_for_comment(led: dict) -> dict:
    """The comment-embedded form: live state plus the resolved tail, no
    full resolved history.

    On extreme PRs the unit map alone can exceed the comment budget; the
    caller (post.encode_ledger) compresses, and as a last resort the map
    is dropped — sealing then degrades to merge-base-relative scoping
    (bigger rounds, never wrong) because units absent from the ledger
    count as changed only when they actually differ from the base.
    Findings keep their own unit_hash_at_filing, so resolution checks
    still work. The resolved tail (ADR-0275) survives trimming: it is
    what stops later rounds from re-litigating or contradicting accepted
    remedies.
    """
    return {
        "version": led["version"],
        "rounds": led["rounds"],
        "last_head": led["last_head"],
        "units": led["units"],
        "findings": {k: f for k, f in led["findings"].items() if f["status"] != "resolved"},
        "resolved_tail": led.get("resolved_tail", []),
    }


# ---------------------------------------------------------------------------
# scope

SEALED_NOTE = "sealed units cannot produce new findings this round"


def file_proxy_hash(facts: dict, path: str) -> str | None:
    """The file's content hash from the facts pack — unit-less findings
    ride it, so their resolution checks fire on ANY change to the file,
    including unit-invariant ones (reorders, module-level edits)."""
    for f in facts["files"]:
        if f["path"] == path:
            return f.get("content_hash")
    return None


def _staleness_reason(f: dict, facts_units: dict, facts: dict) -> str | None:
    """Why a previously filed finding needs a resolution check this round
    (None = untouched, carry it as context). The file-level rule exists
    because a finding's fix can land in a sibling unit (helper extracted,
    call site fixed)."""
    uid = f.get("unit")
    if uid:
        if uid not in facts_units:
            return "unit no longer exists"
        if facts_units[uid]["hash"] != f.get("unit_hash_at_filing"):
            return "unit changed since filing"
        filed_file_hash = f.get("file_hash_at_filing")
        if filed_file_hash and file_proxy_hash(facts, f["path"]) != filed_file_hash:
            return "file changed since filing (its fix may have landed in a sibling unit)"
        return None
    if file_proxy_hash(facts, f["path"]) != f.get("unit_hash_at_filing"):
        return "file changed since filing"
    return None


def compute_scope(facts: dict, led: dict) -> dict:
    round_no = led["rounds"] + 1
    full = led["rounds"] == 0

    open_findings = {k: f for k, f in led["findings"].items() if f["status"] == "open"}
    waived = {k: f for k, f in led["findings"].items() if f["status"] == "waived"}

    facts_units = {u["id"]: u for u in facts["units"]}

    # "Changed" is judged against the LEDGER (the previous round's head),
    # not the merge base: a push that touches nothing since the last
    # round scopes to zero units and costs zero model tokens. Units absent
    # from the ledger count only when facts says they actually changed vs
    # the merge base — expansion inventory (dependency-dirty files) is
    # unchanged by construction and must not dirty itself.
    # A unit the PR no longer differs on (equal to the merge base) is never
    # "changed": a rebase onto a newer main moves hashes without the PR
    # touching the code, and other-PR code is never re-judged (LABS-311).
    changed = {
        uid
        for uid, u in facts_units.items()
        if (u.get("changed") or u.get("is_new"))
        and (uid not in led["units"] or unit_hash(led, uid) != u["hash"])
    }

    dirty_files = dependency_dirty_files(facts, led)
    # ADR-0356: unit-granular — the dirty file's *using* units join
    # scope; a whole file only when the heuristic cannot hold
    dep_dirty = (facts_units.keys()
                 & dependency_dirty_units(facts, led, dirty_files)) - changed

    # Open findings force a resolution check when their unit (or file,
    # via the proxy hash) changed or vanished; otherwise they are carried
    # as already-posted context.
    resolve_checks = []
    for fid, f in sorted(open_findings.items()):
        reason = _staleness_reason(f, facts_units, facts)
        if reason:
            resolve_checks.append({"finding_id": fid, "unit": f.get("unit"),
                                   "path": f["path"], "reason": reason,
                                   "summary": f.get("summary", ""),
                                   "remedy": f.get("remedy", ""),
                                   "quote": f.get("quote", "")})

    if full:
        # ADR-0347: round 1 judges the units the diff hunks actually touch
        # (plus new units and dependency-dirty expansion files) — the rest
        # of a changed file is context (ADR-0346): carried or night-shift
        # backlog, never first-round judgment.
        hbp = facts_mod.hunks_by_path(facts)
        judged = {uid for uid, u in facts_units.items()
                  if u.get("is_new")
                  or facts_mod.range_in_hunks(u["path"], u["start"], u["end"], hbp)}
    else:
        judged = changed
    review = sorted(judged | dep_dirty)

    sealed = sorted(set(facts_units) - set(review))
    review_files = sorted({facts_units[uid]["path"] for uid in review})

    return {
        "version": VERSION,
        "round": round_no,
        "full": full,
        "head": facts["head"],
        "review_units": review,
        "review_files": review_files,
        "sealed_units": sealed,
        "sealed_note": SEALED_NOTE,
        "resolve_checks": resolve_checks,
        "open_findings": [
            {"id": fid, "path": f["path"], "lines": f["lines"], "severity": f["severity"],
             "summary": f["summary"], "unit": f.get("unit")}
            for fid, f in sorted(open_findings.items())
        ],
        "waived": [
            {"id": fid, "path": f["path"], "summary": f["summary"], "reason": f.get("waive_reason", "")}
            for fid, f in sorted(waived.items())
        ],
        # Already litigated and closed: the briefs show these so a later
        # round neither re-reports them nor contradicts their remedies.
        "resolved_recent": led.get("resolved_tail", []),
        "dependency_dirty_files": sorted(dirty_files),
        "stats": {
            "units_total": len(facts_units),
            "units_changed": len(changed),
            "units_dependency_dirty": len(dep_dirty),
            "units_sealed": len(sealed),
            "units_in_scope": len(review),
        },
    }


# ---------------------------------------------------------------------------
# update

QUOTE_WS = re.compile(r"\s+")


def _close_from_spec(led: dict, specs: list[str], round_no: int,
                     status: str, note_key: str) -> None:
    """Close open findings from "finding-id:note" specs — the one
    lifecycle idiom shared by waivers and the resolve hatch."""
    for spec in specs:
        fid, _, note = spec.partition(":")
        f = led["findings"].get(fid.strip())
        if f and f["status"] == "open":
            f["status"] = status
            f["round_closed"] = round_no
            f[note_key] = note.strip()


RESOLVED_TAIL_CAP = 12


def round_dispositions(led: dict, round_no: int) -> dict:
    """The round's finding dispositions — new / carried / resolved /
    waived — all derived from entry internals here in the module that
    owns the ledger schema, so callers stay pure orchestration. Resolved
    and waived both key on `round_closed`: every close path in
    apply_update (model resolution, --resolve hatch, --waive) sets it."""
    after = led["findings"]
    return {
        "new": sorted((f for f in after.values()
                       if f.get("round_filed") == round_no and f["status"] == "open"),
                      key=lambda f: f["id"]),
        "carried": sorted((f for f in after.values()
                           if f["status"] == "open" and f.get("round_filed") != round_no),
                          key=lambda f: f["id"]),
        "resolved": sorted(f["id"] for f in after.values()
                           if f["status"] == "resolved"
                           and f["round_closed"] == round_no),
        "waived": sorted((f for f in after.values()
                          if f["status"] == "waived" and f["round_closed"] == round_no),
                         key=lambda f: f["id"]),
    }


def _resolved_tail(led: dict) -> list[dict]:
    """The most recent resolved findings, compact — the next rounds'
    "already litigated" memory (ADR-0275). Capped: this rides the PR
    summary comment."""
    resolved = [f for f in led["findings"].values() if f["status"] == "resolved"]
    resolved.sort(key=lambda f: f.get("round_closed", 0), reverse=True)
    return [
        {"id": f["id"], "path": f["path"], "summary": f.get("summary", ""),
         "remedy": f.get("remedy", ""), "round_closed": f.get("round_closed", 0)}
        for f in resolved[:RESOLVED_TAIL_CAP]
    ]


def apply_update(facts: dict, led: dict, review: dict, waivers: list[str],
                 allowed_resolve_ids: set[str] | None = None,
                 resolves: list[str] | None = None) -> dict:
    round_no = led["rounds"] + 1
    facts_units = {u["id"]: u for u in facts["units"]}

    # resolutions: closed-form verdicts on previously open findings —
    # accepted only for ids this round's scope actually checked, so a
    # compromised or confused model cannot silently resolve a finding on
    # untouched code (allowed_resolve_ids=None keeps the permissive
    # behavior for callers without a scope document). --resolve entries
    # are the human escape hatch for fixes the staleness rules cannot see
    # (e.g. landed in a sibling unit before file hashes were tracked).
    for res in review.get("resolutions", []):
        fid = res.get("finding_id")
        if allowed_resolve_ids is not None and fid not in allowed_resolve_ids:
            print(f"ledger.py: ignoring out-of-scope resolution for {fid}", file=sys.stderr)
            continue
        f = led["findings"].get(fid)
        if not f or f["status"] != "open":
            continue
        if res.get("addressed"):
            f["status"] = "resolved"
            f["round_closed"] = round_no
    _close_from_spec(led, resolves or [], round_no, "resolved", "resolve_note")

    # new findings
    seq = sum(1 for f in led["findings"].values() if f.get("round_filed") == round_no)
    for find in review.get("findings", []):
        seq += 1
        fid = f"F-{round_no}-{seq}"
        uid = find.get("unit")
        filed_hash = (
            facts_units.get(uid, {}).get("hash")
            if uid
            else file_proxy_hash(facts, find["path"])
        )
        led["findings"][fid] = {
            "id": fid,
            "unit": uid,
            "path": find["path"],
            "lines": [find.get("start_line"), find.get("end_line")],
            "severity": find["severity"],
            "area": find["area"],
            "checklist_id": find.get("checklist_id", ""),
            "quote_hash": hash_quote(find.get("quote", "")),
            "summary": find.get("why", "")[:200],
            "remedy": find.get("remedy", "")[:300],
            "status": "open",
            "unit_hash_at_filing": filed_hash,
            "file_hash_at_filing": file_proxy_hash(facts, find["path"]),
            "quote": find.get("quote", "")[:400],
            "round_filed": round_no,
            "confidence": find.get("confidence", "high"),
        }

    # waivers (manual, e.g. post.py --waive F-3:reason); applied after
    # filing so a finding can be filed and waived in the same update
    _close_from_spec(led, waivers, round_no, "waived", "waive_reason")

    # roll unit state forward (compact "hash:sighash" per unit)
    for uid, u in facts_units.items():
        led["units"][uid] = f"{u['hash']}:{u.get('signature_hash', '')}"
    # units that vanished from the diff's file set stay in the ledger but
    # stop participating in scope (they are neither in facts nor sealed).

    # migration: findings filed before file_hash_at_filing existed get it
    # backfilled from the current facts, so the sibling-unit rule applies
    # to them from the next round on
    for f in led["findings"].values():
        if f["status"] == "open" and f.get("unit") and not f.get("file_hash_at_filing"):
            f["file_hash_at_filing"] = file_proxy_hash(facts, f["path"])

    led["resolved_tail"] = _resolved_tail(led)
    led["rounds"] = round_no
    led["last_head"] = facts["head"]
    return led


def hash_quote(quote: str) -> str:
    return hashlib.sha256(QUOTE_WS.sub(" ", quote.strip()).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# CLI — one table; adding a command is one entry, no branches


def _cmd_scope(args: argparse.Namespace, facts: dict, led: dict) -> None:
    scope = compute_scope(facts, led)
    out = json.dumps(scope, indent=2, sort_keys=True) + "\n"
    if args.out:
        with open(ensure_parent(args.out), "w") as fh:
            fh.write(out)
    else:
        sys.stdout.write(out)
    s = scope["stats"]
    print(
        f"scope: round {scope['round']} ({'full' if scope['full'] else 'incremental'}) — "
        f"{s['units_in_scope']}/{s['units_total']} units in scope, "
        f"{s['units_sealed']} sealed, {len(scope['resolve_checks'])} resolution checks",
        file=sys.stderr,
    )


def _cmd_update(args: argparse.Namespace, facts: dict, led: dict) -> None:
    with open(args.findings) as fh:
        review = json.load(fh)
    allowed = None
    if args.scope:
        # flag present but file missing fails closed and loudly — the
        # same policy cmd_post applies; flag absent is the documented
        # permissive bootstrap
        with open(args.scope) as fh:
            scope = json.load(fh)
        allowed = {rc["finding_id"] for rc in scope.get("resolve_checks", [])}
    led = apply_update(facts, led, review, args.waive,
                       allowed_resolve_ids=allowed, resolves=args.resolve)
    out_path = args.out or args.ledger
    if not out_path:
        raise SystemExit("ledger.py update: pass --ledger or --out")
    save_ledger(led, out_path)
    open_n = sum(1 for f in led["findings"].values() if f["status"] == "open")
    print(f"ledger: round {led['rounds']} recorded, {open_n} open findings -> {out_path}",
          file=sys.stderr)


def _cmd_brief(args: argparse.Namespace, facts: dict, led: dict) -> None:
    with open(args.scope) as fh:
        scope = json.load(fh)
    diff_text = ""
    if args.diff:
        with open(args.diff) as fh:
            diff_text = fh.read()
    out_dir = args.out or os.path.join(os.path.dirname(os.path.abspath(args.facts)), "briefs")
    # override-only: write_briefs' signature owns the default cap; the
    # call site states just the --no-shard decision
    if args.no_shard:
        written = briefs.write_briefs(facts, scope, diff_text, out_dir, cap=None)
    else:
        written = briefs.write_briefs(facts, scope, diff_text, out_dir)
    for name, path in sorted(written.items()):
        size = os.path.getsize(path)
        print(f"brief {name}: {size} bytes -> {path}", file=sys.stderr)


COMMANDS = {
    "scope": {"handler": _cmd_scope, "extra_args": []},
    "update": {"handler": _cmd_update, "extra_args": [
        (("--findings",), {"required": True}),
        (("--scope",), {"help": "scope.json; when given, resolutions are accepted "
                                "only for ids in its resolve_checks"}),
        (("--resolve",), {"action": "append", "default": [],
                          "help": "finding-id:note; human escape hatch — marks an open "
                                  "finding resolved when the staleness rules cannot "
                                  "see the fix"}),
        (("--waive",), {"action": "append", "default": [],
                        "help": "finding-id:reason; marks an open finding waived"}),
    ]},
    "brief": {"handler": _cmd_brief, "extra_args": [
        (("--scope",), {"required": True, "help": "scope.json from the scope command"}),
        (("--diff",), {"help": "patch file to embed (incremental rounds: "
                               "git diff <last_head> <head>; round 1: omit — "
                               "unit bodies carry the content)"}),
        (("--no-shard",), {"action": "store_true",
                           "help": "one brief per pass, no sharding however "
                                   "big the round (the quick local round's "
                                   "shape; the full round always shards)"}),
    ]},
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, spec in COMMANDS.items():
        p = sub.add_parser(name)
        p.add_argument("--facts", required=True)
        p.add_argument("--ledger")
        p.add_argument("--out")
        for flags, kwargs in spec["extra_args"]:
            p.add_argument(*flags, **kwargs)
    args = ap.parse_args()

    with open(args.facts) as fh:
        facts = json.load(fh)
    led = load_ledger(args.ledger)
    COMMANDS[args.cmd]["handler"](args, facts, led)


if __name__ == "__main__":
    main()
