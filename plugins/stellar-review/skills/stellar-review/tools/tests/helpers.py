"""Shared helpers for the stellar-review tool tests: the repo root, the
pass registry in order, file reading and regex region slicing, agent-file
frontmatter splitting, and a temp git repo with write/commit helpers.
Importing this module puts tools/ on sys.path, so test modules import it
before any tool module."""

import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import briefs  # noqa: E402
import facts  # noqa: E402

ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)
# Derived from the canonical production pass registry (briefs.PASS_LAYOUT);
# this tuple exists only so the tests iterate it in registry order.
PASSES = tuple(briefs.PASS_LAYOUT)


def read(path):
    with open(path) as fh:
        return fh.read()


def region_between(text, start_pat, end_pat, label):
    """From the first `start_pat` match through the next `end_pat` match
    (or the end of the text when `end_pat` never matches)."""
    m = re.search(start_pat, text, re.M)
    if m is None:
        raise AssertionError(f"{label}: no match for {start_pat!r}")
    rest = text[m.end():]
    nxt = re.search(end_pat, rest, re.M)
    return text[m.start(): m.end() + (nxt.start() if nxt else len(rest))]


def split_frontmatter(text: str) -> tuple[str, str]:
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    assert m, "agent file has no frontmatter"
    return m.group(1), m.group(2)


class RepoFixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        facts.git(self.dir, "init", "-q", "-b", "main")
        facts.git(self.dir, "config", "user.email", "t@t.t")
        facts.git(self.dir, "config", "user.name", "t")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, path, content):
        full = os.path.join(self.dir, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as fh:
            fh.write(content)

    def commit(self, msg):
        facts.git(self.dir, "add", "-A")
        facts.git(self.dir, "commit", "-qm", msg)
        return facts.git(self.dir, "rev-parse", "HEAD").strip()


def f(fid, path, sev="medium", status="open", q=None):
    """One open ledger finding, the shape ledger.py's findings take."""
    return {"id": fid, "path": path, "severity": sev, "status": status,
            "checklist_id": "std-1", "quote_hash": q or fid, "summary": "s", "remedy": "r"}


def led(*fs):
    """One ledger document from its findings."""
    return {"findings": {x["id"]: x for x in fs}}
