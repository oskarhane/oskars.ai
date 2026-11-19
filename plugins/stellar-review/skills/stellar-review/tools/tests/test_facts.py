"""Tests for facts.py — deterministic facts extraction (ADR-0271)."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import facts  # noqa: E402
from helpers import RepoFixture  # noqa: E402
from units import extract_signature  # noqa: E402


RUST_BASE = """\
use crate::engine::Session;

pub fn parse_port(s: &str) -> Option<u16> {
    s.parse().ok()
}

fn helper(x: u32) -> u32 {
    x + 1
}
"""

PY_BASE = """\
def greet(name):
    return "hi " + name
"""


class TestParsers(unittest.TestCase):
    def test_hunk_plus_plus_content_does_not_drift(self):
        diff = ("diff --git a/x.c b/x.c\n--- a/x.c\n+++ b/x.c\n"
                "@@ -1,3 +1,4 @@\n int i;\n++i;\n ++j;\n return i;\n")
        added, ranges = facts.parse_file_diff(diff)
        # `++i;` is an added line (marker `+` + content `++i;`) at line 2;
        # without hunk-state tracking it would be swallowed as a header
        self.assertEqual(added, {2})
        self.assertEqual(ranges, [[1, 4]])

    def test_no_newline_marker_is_not_context(self):
        diff = ("@@ -1,2 +1,2 @@\n-old\n\\ No newline at end of file\n+new\n"
                "\\ No newline at end of file\n")
        added, ranges = facts.parse_file_diff(diff)
        self.assertEqual(added, {1})
        self.assertEqual(ranges, [[1, 1]])

    def test_python_signature_keeps_annotations(self):
        sig = extract_signature("def build_facts(repo: str, base: str, head: str) -> dict:\n    pass", "python")
        self.assertEqual(sig, "def build_facts(repo: str, base: str, head: str) -> dict")

    def test_numstat_z_rename_rows(self):
        raw = "1\t0\tkeep.rs\0" + "0\t0\t\0old.rs\0new.rs\0"
        rows = facts.parse_numstat_z(raw)
        self.assertEqual(rows, [("1", "0", "keep.rs"), ("0", "0", "new.rs")])
        ns = facts.parse_name_status_z("M\0keep.rs\0R100\0old.rs\0new.rs\0")
        self.assertEqual(ns["new.rs"], ("renamed", "old.rs"))
        self.assertEqual(ns["keep.rs"], ("m", None))


class TestRenameHandling(RepoFixture):
    def test_renamed_file_keeps_old_path_and_base_units(self):
        self.write("src/old.rs", "pub fn parse() {}\n")
        base = self.commit("base")
        facts.git(self.dir, "mv", "src/old.rs", "src/new.rs")
        head = self.commit("rename")
        f = facts.build_facts(self.dir, base, head)
        rec = [x for x in f["files"] if x["path"] == "src/new.rs"]
        self.assertEqual(len(rec), 1)
        self.assertEqual(rec[0]["status"], "renamed")
        self.assertEqual(rec[0]["old_path"], "src/old.rs")
        # same content → the unit survives the rename as unchanged
        u = [x for x in f["units"] if x["id"] == "src/new.rs::parse"]
        self.assertEqual(len(u), 1)
        self.assertFalse(u[0]["changed"])


class TestExtraction(RepoFixture):
    def build(self):
        self.write("src/lib.rs", RUST_BASE)
        self.write("src/engine.rs", "pub struct Session;\n")
        self.write("tool.py", PY_BASE)
        self.write("README.md", "# hello\n")
        base = self.commit("base")
        self.write("src/lib.rs", RUST_BASE.replace(
            "pub fn parse_port(s: &str) -> Option<u16> {\n    s.parse().ok()\n}",
            "pub fn parse_port(s: &str) -> Option<u16> {\n    if s.is_empty() {\n"
            "        return None;\n    }\n    let n: u16 = s.parse().unwrap();\n"
            "    Some(n as u16)\n}",
        ))
        self.write("tool.py", PY_BASE + "\nclass Greeter:\n    def loud(self, name):\n"
                   "        if not name:\n            return ''\n        return greet(name).upper()\n")
        head = self.commit("change")
        return facts.build_facts(self.dir, base, head)

    def test_units_and_flags(self):
        f = self.build()
        units = {u["id"]: u for u in f["units"]}
        self.assertIn("src/lib.rs::parse_port", units)
        self.assertIn("src/lib.rs::helper", units)
        self.assertIn("tool.py::Greeter::loud", units)
        self.assertTrue(units["src/lib.rs::parse_port"]["changed"])
        # body changed, signature did not
        self.assertFalse(units["src/lib.rs::parse_port"]["signature_changed"])
        self.assertFalse(units["src/lib.rs::helper"]["changed"])
        self.assertTrue(units["tool.py::Greeter::loud"]["is_new"])

    def test_sites(self):
        f = self.build()
        kinds = {(s["kind"], s["path"]) for s in f["sites"]}
        self.assertIn(("unwrap", "src/lib.rs"), kinds)
        self.assertIn(("as_cast", "src/lib.rs"), kinds)
        self.assertIn(("new_branch", "src/lib.rs"), kinds)
        self.assertIn(("new_branch", "tool.py"), kinds)
        # the base `.ok()` line was removed, not added: no silent_fallback
        self.assertNotIn(("silent_fallback", "src/lib.rs"), kinds)

    def test_deps_repo_wide(self):
        f = self.build()
        self.assertIn("src/lib.rs", f["deps"])
        self.assertIn("crate::engine::Session", f["deps"]["src/lib.rs"])

    def test_determinism(self):
        first = self.build()
        base = facts.git(self.dir, "rev-parse", "HEAD~1").strip()
        head = facts.git(self.dir, "rev-parse", "HEAD").strip()
        a = json.dumps(first, sort_keys=True)
        b = json.dumps(facts.build_facts(self.dir, base, head), sort_keys=True)
        self.assertEqual(a, b)


class TestDocsOnly(RepoFixture):
    def test_docs_commit_is_not_code(self):
        self.write("src/lib.rs", RUST_BASE)
        base = self.commit("base")
        self.write("docs/guide.md", "# guide\n")
        self.write("README.md", "# x\n")
        head = self.commit("docs")
        f = facts.build_facts(self.dir, base, head)
        self.assertFalse(f["has_code_changes"])
        self.assertEqual(f["units"], [])


class TestFileUnits(RepoFixture):
    def test_unitless_code_files_get_file_units(self):
        self.write("run.sh", "#!/bin/sh\necho hi\n")
        base = self.commit("base")
        self.write("run.sh", "#!/bin/sh\necho hi\necho bye\n")
        head = self.commit("change")
        f = facts.build_facts(self.dir, base, head)
        ids = [u["id"] for u in f["units"]]
        self.assertEqual(ids, ["run.sh::__file__"])
        self.assertTrue(f["units"][0]["changed"])

    def test_unchanged_file_unit_seals(self):
        self.write("run.sh", "#!/bin/sh\necho hi\n")
        self.write("x.rs", "fn a() {}\n")
        base = self.commit("base")
        self.write("x.rs", "fn a() {}\nfn b() {}\n")
        head = self.commit("change")
        f = facts.build_facts(self.dir, base, head)
        fu = [u for u in f["units"] if u["id"] == "run.sh::__file__"]
        # run.sh not in this diff at all: no unit emitted
        self.assertEqual(fu, [])


class TestSimilarity(RepoFixture):
    def test_near_duplicates_pair_up(self):
        # similarity is computed over CHANGED units, so the pair must be
        # introduced by the diff itself
        self.write("src/lib.rs", "pub fn existing() {}\n")
        base = self.commit("base")
        body_a = "pub fn parse_%s(s: &str) -> Option<u16> {\n    let t = s.trim();\n    if t.is_empty() {\n        return None;\n    }\n    t.parse().ok()\n}\n"
        self.write("src/lib.rs", "pub fn existing() {}\n" + body_a % "one" + "\n" + body_a % "two")
        head = self.commit("add pair")
        f = facts.build_facts(self.dir, base, head)
        self.assertTrue(any(
            {p["a"], p["b"]} == {"src/lib.rs::parse_one", "src/lib.rs::parse_two"}
            for p in f["similarity"]
        ))


class TestIncludeUnits(RepoFixture):
    def test_expansion_adds_unchanged_units(self):
        self.write("src/lib.rs", "pub fn a() {}\n")
        self.write("src/user.rs", "use crate::a;\npub fn calls() { a() }\n")
        base = self.commit("base")
        self.write("src/lib.rs", "pub fn a() {}\npub fn b() {}\n")
        head = self.commit("change")
        f = facts.build_facts(self.dir, base, head, include_units=["src/user.rs"])
        u = [x for x in f["units"] if x["id"] == "src/user.rs::calls"]
        self.assertEqual(len(u), 1)
        self.assertFalse(u[0]["changed"])
        self.assertEqual(f["expanded_unit_files"], ["src/user.rs"])


class StdoutJsonContract(unittest.TestCase):
    """--stdout-json: the pipe channel the per-kind gate consumes. The
    gate's decision must never re-read the model-writable
    .stellar/facts.json, so facts.py hands the same bytes it wrote to
    the file to stdout — as the stream's FINAL content, with the
    progress summary on stderr."""

    def test_stdout_json_is_the_file_and_ends_the_stream(self):
        import subprocess
        import tempfile
        facts_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "facts.py")
        with tempfile.TemporaryDirectory() as d:
            def sh(*a):
                subprocess.run(a, cwd=d, check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            sh("git", "init", "-q", ".")
            sh("git", "config", "user.email", "t@example.com")
            sh("git", "config", "user.name", "t")
            with open(os.path.join(d, "main.rs"), "w") as fh:
                fh.write("fn main() {}\n")
            sh("git", "add", "main.rs")
            sh("git", "commit", "-qm", "one")
            with open(os.path.join(d, "lib.rs"), "w") as fh:
                fh.write("pub fn f() {}\n")
            sh("git", "add", "lib.rs")
            sh("git", "commit", "-qm", "two")
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=d,
                                  check=True, capture_output=True, text=True).stdout.strip()
            base = subprocess.run(["git", "rev-parse", "HEAD~1"], cwd=d,
                                  check=True, capture_output=True, text=True).stdout.strip()
            out = os.path.join(d, "facts.json")
            r = subprocess.run([sys.executable, facts_py, "--repo", d,
                                "--base", base, "--head", head,
                                "--out", out, "--stdout-json"],
                               check=True, capture_output=True, text=True)
            # stdout parses as JSON and equals the file; the summary is
            # on stderr, never after the JSON on stdout
            stdout_facts = json.loads(r.stdout)
            with open(out) as fh:
                file_facts = json.load(fh)
            self.assertEqual(stdout_facts, file_facts)
            self.assertNotIn("facts:", r.stdout)
            self.assertIn("facts:", r.stderr)
            # and the plain mode is unchanged: summary on stdout, no JSON
            r2 = subprocess.run([sys.executable, facts_py, "--repo", d,
                                 "--base", base, "--head", head, "--out", out],
                                check=True, capture_output=True, text=True)
            self.assertIn("facts:", r2.stdout)
            self.assertEqual(r2.stdout.count("{"), 0)


class IsDocsClassification(unittest.TestCase):
    """The one classification, pinned directly: source files under
    docs-classified directories (the API surfaces' runnable examples —
    compiled and executed by CI) are code, not docs; everything the
    DOCS_PATH table and documentation extensions name stays docs."""

    def test_docs_code_extensions_are_not_docs(self):
        self.assertFalse(facts.is_docs("docs/api/rust/examples/hello.rs"))
        self.assertFalse(facts.is_docs("docs/api/c/examples/vector.c"))
        self.assertFalse(facts.is_docs("docs/api/cli/examples/agent.sh"))
        self.assertTrue(facts.is_docs("docs/api/rust/spec.md"))
        self.assertTrue(facts.is_docs("docs/adr/0001-x.md"))
        self.assertTrue(facts.is_docs("docs/api/javascript/README.md"))
        self.assertTrue(facts.is_docs("website/index.md"))


if __name__ == "__main__":
    unittest.main()
