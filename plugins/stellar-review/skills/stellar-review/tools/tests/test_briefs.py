"""Tests for briefs.py — per-pass brief assembly."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import briefs  # noqa: E402


class TestSliceDiff(unittest.TestCase):
    DIFF = ("diff --git a/sub/b/foo.rs b/sub/b/foo.rs\n@@ -1 +1 @@\n-a\n+b\n"
            "diff --git a/foo.rs b/foo.rs\n@@ -1 +1 @@\n-c\n+d\n")

    def test_matches_b_path_exactly(self):
        out, missed = briefs.slice_diff(self.DIFF, {"foo.rs"})
        self.assertIn("a/foo.rs", out)
        self.assertNotIn("sub/b/foo.rs", out)
        self.assertEqual(missed, [])

    def test_quoted_paths_unquote_before_matching(self):
        diff = 'diff --git "a/dir with space/x.rs" "b/dir with space/x.rs"\n@@ -1 +1 @@\n-a\n+b\n'
        out, missed = briefs.slice_diff(diff, {"dir with space/x.rs"})
        self.assertIn("+b", out)
        self.assertEqual(missed, [])

    def test_octal_escaped_non_ascii_round_trips(self):
        diff = 'diff --git "a/caf\\303\\251.rs" "b/caf\\303\\251.rs"\n@@ -1 +1 @@\n-a\n+b\n'
        out, missed = briefs.slice_diff(diff, {"café.rs"})
        self.assertIn("+b", out)
        self.assertEqual(missed, [])

    def test_scoped_miss_is_returned_as_data(self):
        _, missed = briefs.slice_diff(self.DIFF, {"foo.rs", "missing.rs"})
        self.assertEqual(missed, ["missing.rs"])


class TestDiffSections(unittest.TestCase):
    def test_splits_sections_in_order(self):
        diff = ("diff --git a/x.rs b/x.rs\n@@ -1 +1 @@\n-a\n+b\n"
                "diff --git a/y.rs b/y.rs\n@@ -1 +1 @@\n-c\n+d\n")
        sections = briefs.diff_sections(diff)
        self.assertEqual([p for p, _ in sections], ["x.rs", "y.rs"])
        self.assertIn("+b", sections[0][1])
        self.assertIn("+d", sections[1][1])

    def test_malformed_header_warns_and_starts_no_section(self):
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            sections = briefs.diff_sections("diff --git onlyonetoken\n+stray\n")
        self.assertEqual(sections, [])
        self.assertIn("malformed diff header", err.getvalue())


class TestBriefCommon(unittest.TestCase):
    SCOPE = {
        "version": 1, "round": 1, "full": True, "head": "b",
        "review_units": [], "review_files": [], "sealed_units": [],
        "resolve_checks": [], "open_findings": [], "waived": [],
        "resolved_recent": [], "dependency_dirty_files": [],
        "stats": {"units_total": 2, "units_changed": 0,
                  "units_dependency_dirty": 0, "units_sealed": 2,
                  "units_in_scope": 0},
    }

    def test_incremental_round_states_the_anchor_rule(self):
        text = "\n".join(briefs.brief_common(dict(self.SCOPE, round=2, full=False)))
        self.assertIn("MUST anchor to lines changed since the last round", text)
        # round 1 is unfiltered — no rule line
        text = "\n".join(briefs.brief_common(self.SCOPE))
        self.assertNotIn("MUST anchor", text)

    def test_resolved_recent_is_rendered_as_litigated(self):
        scope = dict(self.SCOPE, resolved_recent=[
            {"id": "F-1-2", "path": "a.rs", "summary": "dup table",
             "remedy": "derive the inverse", "round_closed": 1}])
        text = "\n".join(briefs.brief_common(scope))
        self.assertIn("already litigated", text)
        self.assertIn("F-1-2", text)
        self.assertIn("derive the inverse", text)


class TestChunkUnits(unittest.TestCase):
    def units(self):
        # over the chunk capacity, spread over two top-level dirs
        return [{"path": f"{top}/f{i}.rs"} for top in ("relate", "surfaces")
                for i in range(briefs.BRIEF_CHUNK_UNITS)]

    def test_over_capacity_splits_by_top_level_dir(self):
        units = self.units()
        chunks = briefs.chunk_units(units, cap=briefs.BRIEF_CHUNK_UNITS)
        self.assertGreater(len(chunks), 1)
        # units are built in directory order, so the stable sort returns
        # them unchanged — asserted against the input, not a re-derived key
        flat = [u["path"] for chunk in chunks for u in chunk]
        self.assertEqual(flat, [u["path"] for u in units])

    def test_interleaved_input_comes_out_directory_adjacent(self):
        # interleaved directories: the stable sort is load-bearing, not a
        # no-op — each directory's units come out adjacent
        units = [{"path": p} for p in
                 ("relate/a.rs", "surfaces/b.rs", "relate/c.rs",
                  "surfaces/d.rs", "relate/e.rs", "surfaces/f.rs")]
        chunks = briefs.chunk_units(units, cap=3)
        flat = [u["path"] for chunk in chunks for u in chunk]
        self.assertEqual(flat, ["relate/a.rs", "relate/c.rs",
                                "relate/e.rs", "surfaces/b.rs",
                                "surfaces/d.rs", "surfaces/f.rs"])

    def test_explicit_cap_slices_fixed_size_chunks(self):
        # the expected sizes derive from the corpus size, never from a
        # snapshot of BRIEF_CHUNK_UNITS' value
        total = len(self.units())
        cap = 150
        chunks = briefs.chunk_units(self.units(), cap=cap)
        expected = [cap] * (total // cap) + ([total % cap] if total % cap else [])
        self.assertEqual([len(chunk) for chunk in chunks], expected)

    def test_cap_none_keeps_one_brief_per_pass(self):
        # the quick round's shape: however big the round, one chunk
        units = self.units()
        self.assertEqual(briefs.chunk_units(units, cap=None), [units])


class TestWriteBriefsDirectory(unittest.TestCase):
    """The briefs directory reflects exactly the current plan: a previous,
    differently-shaped round's files are removed, never left for a later
    pass dispatch to pick up."""

    def docs(self, paths):
        units = [{"id": f"u{i}", "kind": "function", "path": p, "start": 1,
                  "end": 2, "is_new": True, "changed": True, "body": "x",
                  "signature": "f()"} for i, p in enumerate(paths)]
        facts = {"units": units, "sites": [],
                 "files": [{"path": p, "is_docs": False, "status": "modified",
                            "added": 1, "deleted": 0, "lines_base": 1,
                            "lines_now": 2, "crossed_1k": False}
                           for p in paths]}
        scope = {"version": 1, "round": 1, "full": True, "head": "h",
                 "review_units": [u["id"] for u in units],
                 "review_files": list(paths), "sealed_units": [],
                 "resolve_checks": [], "open_findings": [], "waived": [],
                 "resolved_recent": [], "dependency_dirty_files": [],
                 "stats": {"units_total": len(units), "units_changed": len(units),
                           "units_dependency_dirty": 0, "units_sealed": 0,
                           "units_in_scope": len(units)}}
        return facts, scope

    def test_reemit_removes_the_previous_rounds_stale_briefs(self):
        with tempfile.TemporaryDirectory() as out:
            facts, scope = self.docs([f"relate/c/f{i}.rs" for i in range(5)])
            sharded = briefs.write_briefs(facts, scope, "", out, cap=2)
            self.assertIn("structure-1", sharded)  # the sharded shape wrote -N files
            unsharded = briefs.write_briefs(facts, scope, "", out, cap=None)
            self.assertEqual(set(os.listdir(out)),
                             {os.path.basename(p) for p in unsharded.values()})
            self.assertNotIn("brief-structure-1.md", os.listdir(out))


if __name__ == "__main__":
    unittest.main()
