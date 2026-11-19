#!/usr/bin/env python3
"""Stale-ledger-proof incremental diff (LABS-311, ADR-0292).

The incremental anchoring diff is `last_head…head`. A force-push or a
rebase onto a newer main makes `last_head` unreachable or no longer an
ancestor of head; a naive diff then drags main's unrelated commits (or
nothing at all) into the round. This tool picks the smallest covering
base and restricts the patch to the files the PR itself changed, so
pre-merged and other-PR code can never anchor a finding and a stale
ledger can never trigger a full re-scope.

    incremental.py --facts F --ledger L --out PATCH [--repo DIR]

Base choice, in order:
  1. last_head, when it exists locally and is an ancestor of head.
  2. merge-base(last_head, head), when last_head exists but diverged
     (force-push / rebase) — never the main merge-base.
  3. none: the patch is left empty and the round falls back to its
     file-level scope (the ledger's per-unit hashes), not a full review.
Prints `base=<sha|none> reason=<why>` for the CI log.
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

SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _git_ok(repo: str, *args: str) -> str | None:
    r = subprocess.run(["git", "-C", repo, *args], stdout=subprocess.PIPE,
                       stderr=subprocess.DEVNULL)
    return r.stdout.decode("utf-8", errors="replace") if r.returncode == 0 else None


def resolve_base(repo: str, last_head: str | None, head: str) -> tuple[str | None, str]:
    if not last_head or not SHA_RE.match(last_head):
        return None, "no-valid-last-head"
    if _git_ok(repo, "cat-file", "-e", f"{last_head}^{{commit}}") is None:
        return None, "last-head-unreachable"
    if _git_ok(repo, "merge-base", "--is-ancestor", last_head, head) is not None:
        return last_head, "ancestor"
    mb = _git_ok(repo, "merge-base", last_head, head)
    if mb and mb.strip():
        return mb.strip(), "diverged-merge-base"
    return None, "no-common-ancestor"


def incremental_patch(repo: str, base: str, head: str, pr_files: list[str]) -> str:
    if not pr_files:
        return ""
    # --literal-pathspecs: a PR-controlled file name like `:(exclude)*.rs`
    # must be a path, never pathspec magic that shrinks the anchoring diff.
    # --no-ext-diff --no-textconv: the anchoring diff recomputes inside
    # the token-bearing post steps, so external diff drivers and textconv
    # filters (facts.py's pins, the same spelling) never run during it.
    return _git_ok(
        repo, "--literal-pathspecs",
        "-c", "core.fsmonitor=", "-c", "core.pager=cat",
        "diff",
        "--no-ext-diff", "--no-textconv", base, head, "--", *pr_files,
    ) or ""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--facts", required=True)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--repo", default=".")
    args = ap.parse_args()

    with open(args.facts) as fh:
        facts = json.load(fh)
    with open(args.ledger) as fh:
        last = json.load(fh).get("last_head")
    head = facts["head"]
    base, reason = resolve_base(args.repo, last, head)
    patch = ""
    if base and base != head:
        patch = incremental_patch(args.repo, base, head, [f["path"] for f in facts["files"]])
    with open(ensure_parent(args.out), "w") as fh:
        fh.write(patch)
    print(f"incremental: base={base or 'none'} reason={reason} bytes={len(patch)}")


if __name__ == "__main__":
    main()
