"""Tests for ledger.py — cross-round incremental scope (ADR-0271)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ledger  # noqa: E402
import facts  # noqa: E402
from helpers import RepoFixture  # noqa: E402


def finding(unit, path, severity="medium", why="w"):
    return {"area": "boundaries", "severity": severity, "path": path,
            "start_line": 1, "end_line": 2, "unit": unit, "checklist_id": "std-5",
            "quote": "q", "why": why, "remedy": "r", "confidence": "high"}


def review(findings=(), resolutions=()):
    return {"version": 1, "findings": list(findings),
            "resolutions": list(resolutions), "coverage": [], "notes": ""}


class TestRounds(RepoFixture):
    LIB = "relate/relate-core/src/lib.rs"
    USER = "relate/relate-core/src/user.rs"

    def setUp(self):
        super().setUp()
        self.write(self.LIB, "pub fn untouched() {}\n\npub fn parse(s: &str) -> Option<u16> {\n    s.parse().ok()\n}\n")
        self.write(self.USER, "use crate::parse;\npub fn go(s: &str) -> u16 {\n    parse(s).unwrap_or(0)\n}\n\npub fn unrelated() -> u16 {\n    0\n}\n")
        self.base = self.commit("base")
        # the "PR": a commit touching lib.rs — parse's body (in the hunk)
        # and a new unit `extra`, so round 1 judges both (ADR-0347)
        self.write(self.LIB, "pub fn untouched() {}\n\npub fn parse(s: &str) -> Option<u16> {\n    s.parse().ok()\n    // touched\n}\n\npub fn extra() {}\n")
        self.commit("pr")

    def facts_with(self, include):
        """The two-phase expansion re-run: facts rebuilt with the dirty
        files' units pulled in (--include-units). One canonical helper
        for every expansion test (the pipeline's own second pass)."""
        head = facts.git(self.dir, "rev-parse", "HEAD").strip()
        return facts.build_facts(self.dir, self.base, head, include_units=include)

    def facts_now(self):

        head = facts.git(self.dir, "rev-parse", "HEAD").strip()
        return facts.build_facts(self.dir, self.base, head)

    def test_round1_full_round2_empty_without_push(self):
        f = self.facts_now()
        led = ledger.empty_ledger()
        s1 = ledger.compute_scope(f, led)
        self.assertTrue(s1["full"])
        # ADR-0347: the out-of-hunk `untouched` unit of a changed file is
        # context — sealed in round 1, not judged
        self.assertEqual(s1["stats"]["units_sealed"], 1)

        led = ledger.apply_update(f, led, review(), [])
        s2 = ledger.compute_scope(f, led)
        self.assertFalse(s2["full"])
        self.assertEqual(s2["stats"]["units_in_scope"], 0)
        self.assertEqual(s2["stats"]["units_sealed"], s1["stats"]["units_total"])

    def test_round1_seals_units_outside_the_hunks(self):
        # ADR-0347: the PR touches lib.rs (parse + extra land in the hunk);
        # user.rs is unchanged by the diff — its `go` unit is context:
        # sealed in round 1, carried to the night-shift, never judged.
        f = self.facts_now()
        led = ledger.empty_ledger()
        s = ledger.compute_scope(f, led)
        self.assertTrue(s["full"])
        self.assertIn(f"{self.LIB}::parse", s["review_units"])
        self.assertIn(f"{self.LIB}::extra", s["review_units"])
        self.assertIn(f"{self.LIB}::untouched", s["sealed_units"])
        self.assertNotIn(f"{self.LIB}::untouched", s["review_units"])
        # user.rs is not part of the diff: its units are not in facts at all
        self.assertNotIn(f"{self.USER}::go", s["review_units"])
        self.assertNotIn(f"{self.USER}::go", s["sealed_units"])

    def test_push_rescopes_to_touched_units(self):
        f1 = self.facts_now()
        led = ledger.apply_update(f1, ledger.empty_ledger(), review(
            findings=[finding(f"{self.LIB}::parse", self.LIB)]), [])
        s = ledger.compute_scope(f1, led)
        self.assertEqual(s["stats"]["units_in_scope"], 0)
        self.assertEqual([f["id"] for f in s["open_findings"]], ["F-1-1"])
        self.assertEqual(s["resolve_checks"], [])

        # author pushes a fix to the flagged unit: only it re-scopes, and
        # the open finding becomes a resolution check
        self.write(self.LIB, "pub fn parse(s: &str) -> Option<u16> {\n    s.trim().parse().ok()\n}\n")
        self.commit("fix")
        f2 = self.facts_now()
        s2 = ledger.compute_scope(f2, led)
        self.assertEqual(s2["review_units"], [f"{self.LIB}::parse"])
        self.assertEqual(len(s2["resolve_checks"]), 1)
        self.assertEqual(s2["resolve_checks"][0]["finding_id"], "F-1-1")

        # model says addressed → finding resolved, next round is empty
        led = ledger.apply_update(f2, led, review(
            resolutions=[{"finding_id": "F-1-1", "addressed": True}]), [])
        self.assertEqual(led["findings"]["F-1-1"]["status"], "resolved")
        s3 = ledger.compute_scope(f2, led)
        self.assertEqual(s3["stats"]["units_in_scope"], 0)
        self.assertEqual(s3["open_findings"], [])

    def test_signature_change_dirties_dependents_body_change_does_not(self):
        f1 = self.facts_now()
        led = ledger.apply_update(f1, ledger.empty_ledger(), review(), [])

        # body-only change: dependent stays sealed
        self.write(self.LIB, "pub fn parse(s: &str) -> Option<u16> {\n    s.trim().parse().ok()\n}\n")
        self.commit("body")
        s = ledger.compute_scope(self.facts_now(), led)
        self.assertEqual(s["review_units"], [f"{self.LIB}::parse"])
        self.assertEqual(s["dependency_dirty_files"], [])

        # signature change: dependent file dirties; its units join scope
        # after facts expansion
        led = ledger.apply_update(self.facts_now(), led, review(), [])
        self.write(self.LIB, "pub fn parse(s: &str) -> Option<u32> {\n    s.trim().parse().ok().map(u32::from)\n}\n")
        self.commit("sig")
        f3 = self.facts_now()
        s = ledger.compute_scope(f3, led)
        self.assertEqual(s["dependency_dirty_files"], [self.USER])
        self.assertNotIn(f"{self.USER}::go", s["review_units"])  # needs expansion

        head = facts.git(self.dir, "rev-parse", "HEAD").strip()
        f3x = facts.build_facts(self.dir, self.base, head, include_units=[self.USER])
        sx = ledger.compute_scope(f3x, led)
        self.assertIn(f"{self.USER}::go", sx["review_units"])
        self.assertEqual(sx["stats"]["units_dependency_dirty"], 1)
        # the expansion unit itself is unchanged content: recorded with
        # its hash baseline (compact "hash:sighash" form)
        led = ledger.apply_update(f3x, led, review(), [])
        self.assertIn(f"{self.USER}::go", led["units"])

    def test_expansion_is_unit_granular(self):
        # ADR-0356: a signature change joins only the dependent units that
        # reference the changed symbol; a same-file sibling that does not
        # use it stays sealed.
        f1 = self.facts_now()
        led = ledger.apply_update(f1, ledger.empty_ledger(), review(), [])
        self.write(self.LIB, "pub fn parse(s: &str) -> Option<u32> {\n    s.trim().parse().ok().map(u32::from)\n}\n")
        self.commit("sig change, granular dependent")
        # two-phase, like the pipeline: pass 1 names the dirty file, the
        # expansion re-runs facts with --include-units, pass 2 scopes units
        f = self.facts_now()
        s = ledger.compute_scope(f, led)
        self.assertEqual(s["dependency_dirty_files"], [self.USER])
        fx = self.facts_with([self.USER])
        sx = ledger.compute_scope(fx, led)
        self.assertIn(f"{self.USER}::go", sx["review_units"])
        self.assertNotIn(f"{self.USER}::unrelated", sx["review_units"])
        self.assertEqual(sx["stats"]["units_dependency_dirty"], 1)

    def test_expansion_falls_back_to_whole_file(self):
        # ADR-0356's conservative fallbacks: a truncated body in the
        # dirty file keeps the whole file in scope.
        f1 = self.facts_now()
        led = ledger.apply_update(f1, ledger.empty_ledger(), review(), [])
        self.write(self.LIB, "pub fn parse(s: &str) -> Option<u32> {\n    s.trim().parse().ok().map(u32::from)\n}\n")
        self.commit("truncation fallback")
        fx = self.facts_with([self.USER])
        for u in fx["units"]:
            if u["path"] == self.USER:
                u["body_truncated"] = True
        sx = ledger.compute_scope(fx, led)
        self.assertIn(f"{self.USER}::unrelated", sx["review_units"])
        self.assertIn(f"{self.USER}::go", sx["review_units"])

    def test_waiver_survives_until_unit_changes(self):
        f1 = self.facts_now()
        led = ledger.apply_update(f1, ledger.empty_ledger(), review(
            findings=[finding(f"{self.LIB}::parse", self.LIB)]),
            waivers=["F-1-1:accept the fallback here"])
        self.assertEqual(led["findings"]["F-1-1"]["status"], "waived")
        s = ledger.compute_scope(f1, led)
        self.assertEqual(s["open_findings"], [])
        self.assertEqual(len(s["waived"]), 1)
        self.assertEqual(s["waived"][0]["reason"], "accept the fallback here")

    def test_deleted_unit_resolves_via_check(self):
        f1 = self.facts_now()
        led = ledger.apply_update(f1, ledger.empty_ledger(), review(
            findings=[finding(f"{self.LIB}::parse", self.LIB)]), [])
        self.write(self.LIB, "// parse moved elsewhere\n")
        self.commit("remove fn")
        s = ledger.compute_scope(self.facts_now(), led)
        self.assertEqual(len(s["resolve_checks"]), 1)
        self.assertEqual(s["resolve_checks"][0]["reason"], "unit no longer exists")

    def test_unitless_finding_gets_resolution_check_on_file_change(self):
        f1 = self.facts_now()
        led = ledger.apply_update(f1, ledger.empty_ledger(), review(
            findings=[finding(None, self.LIB)]), [])
        s = ledger.compute_scope(f1, led)
        self.assertEqual(s["resolve_checks"], [])  # unchanged: no check
        self.write(self.LIB, "pub fn parse(s: &str) -> Option<u16> {\n    s.trim().parse().ok()\n}\n\npub fn extra() {}\n")
        self.commit("touch file")
        s2 = ledger.compute_scope(self.facts_now(), led)
        self.assertEqual(len(s2["resolve_checks"]), 1)
        self.assertEqual(s2["resolve_checks"][0]["reason"], "file changed since filing")
        self.assertIsNone(s2["resolve_checks"][0]["unit"])

    def test_unitless_finding_fires_on_reorder_only_change(self):
        # round 1 state is the setUp "pr" commit; file a file-level finding
        f1 = self.facts_now()
        led = ledger.apply_update(f1, ledger.empty_ledger(), review(
            findings=[finding(None, self.LIB)]), [])
        # round 2: pure reorder — no unit body changes, but the file-level
        # finding must still get its resolution check
        self.write(self.LIB, "pub fn extra() {}\n\npub fn parse(s: &str) -> Option<u16> {\n    s.parse().ok()\n}\n")
        self.commit("reorder")
        s = ledger.compute_scope(self.facts_now(), led)
        self.assertEqual(len(s["resolve_checks"]), 1)
        self.assertEqual(s["resolve_checks"][0]["reason"], "file changed since filing")

    def test_sibling_unit_fix_fires_resolution_check(self):
        # finding anchored on unit A; the fix lands in sibling unit B of
        # the same file — the file-hash rule must fire the check
        f1 = self.facts_now()
        led = ledger.apply_update(f1, ledger.empty_ledger(), review(
            findings=[finding(f"{self.LIB}::parse", self.LIB)]), [])
        # parse stays byte-identical to round 1; only the sibling changes
        self.write(self.LIB, "pub fn untouched() {}\n\npub fn parse(s: &str) -> Option<u16> {\n    s.parse().ok()\n    // touched\n}\n\npub fn extra() { println!(\"fixed elsewhere\"); }\n")
        self.commit("fix in sibling unit")
        s = ledger.compute_scope(self.facts_now(), led)
        self.assertEqual(len(s["resolve_checks"]), 1)
        self.assertIn("sibling unit", s["resolve_checks"][0]["reason"])

    def test_resolve_escape_hatch(self):
        f1 = self.facts_now()
        led = ledger.apply_update(f1, ledger.empty_ledger(), review(
            findings=[finding(f"{self.LIB}::parse", self.LIB)]), [])
        led = ledger.apply_update(f1, led, review(), [],
                                  resolves=["F-1-1:fixed in a sibling unit before file hashes"])
        f = led["findings"]["F-1-1"]
        self.assertEqual(f["status"], "resolved")
        self.assertEqual(f["resolve_note"], "fixed in a sibling unit before file hashes")

    def test_filing_stores_quote_and_file_hash(self):
        f1 = self.facts_now()
        led = ledger.apply_update(f1, ledger.empty_ledger(), review(
            findings=[finding(f"{self.LIB}::parse", self.LIB)]), [])
        f = led["findings"]["F-1-1"]
        self.assertEqual(f["quote"], "q")
        self.assertTrue(f["file_hash_at_filing"])

    def test_out_of_scope_resolution_is_ignored(self):
        # trust boundary: findings.json is model output; a resolution for
        # a finding whose unit was never in this round's resolve_checks
        # must not close it
        f1 = self.facts_now()
        led = ledger.apply_update(f1, ledger.empty_ledger(), review(
            findings=[finding(f"{self.LIB}::parse", self.LIB)]), [])
        led = ledger.apply_update(f1, led, review(
            resolutions=[{"finding_id": "F-1-1", "addressed": True}]), [],
            allowed_resolve_ids=set())
        self.assertEqual(led["findings"]["F-1-1"]["status"], "open")
        # and with the id allowed, it resolves
        led = ledger.apply_update(f1, led, review(
            resolutions=[{"finding_id": "F-1-1", "addressed": True}]), [],
            allowed_resolve_ids={"F-1-1"})
        self.assertEqual(led["findings"]["F-1-1"]["status"], "resolved")

    def test_trim_for_comment_drops_resolved(self):
        f1 = self.facts_now()
        led = ledger.apply_update(f1, ledger.empty_ledger(), review(
            findings=[finding(f"{self.LIB}::parse", self.LIB)]), [])
        led = ledger.apply_update(f1, led, review(
            resolutions=[{"finding_id": "F-1-1", "addressed": True}]), [])
        trimmed = ledger.trim_for_comment(led)
        self.assertEqual(trimmed["findings"], {})
        self.assertIn(f"{self.LIB}::parse", trimmed["units"])

    def test_resolved_tail_survives_trimming_and_reaches_scope(self):
        # ADR-0275: later rounds must see what was already litigated —
        # the trimmed (comment-embedded) ledger keeps the resolved tail
        # and scope exposes it for the briefs.
        f1 = self.facts_now()
        led = ledger.apply_update(f1, ledger.empty_ledger(), review(
            findings=[finding(f"{self.LIB}::parse", self.LIB, why="dup table")]), [])
        led = ledger.apply_update(f1, led, review(
            resolutions=[{"finding_id": "F-1-1", "addressed": True}]), [])
        trimmed = ledger.trim_for_comment(led)
        [entry] = trimmed["resolved_tail"]
        self.assertEqual(entry["id"], "F-1-1")
        self.assertEqual(entry["summary"], "dup table")
        self.assertEqual(entry["remedy"], "r")
        self.assertEqual(entry["round_closed"], 2)
        scope = ledger.compute_scope(f1, trimmed)
        self.assertEqual(scope["resolved_recent"][0]["id"], "F-1-1")

    def test_round_dispositions_buckets_from_entry_schema(self):
        # the disposition query lives in ledger.py so the poster never
        # pattern-matches entry internals
        f1 = self.facts_now()
        led = ledger.apply_update(f1, ledger.empty_ledger(), review(
            findings=[finding(f"{self.LIB}::parse", self.LIB, why="one")]), [])
        led = ledger.apply_update(f1, led, review(
            findings=[finding(f"{self.LIB}::extra", self.LIB, why="two")],
            resolutions=[{"finding_id": "F-1-1", "addressed": True}]),
            ["F-1-1:wont-fix"], allowed_resolve_ids={"F-1-1"})
        disp = ledger.round_dispositions(led, 2)
        self.assertEqual([f["id"] for f in disp["new"]], ["F-2-1"])
        self.assertEqual(disp["carried"], [])
        self.assertEqual(disp["resolved"], ["F-1-1"])
        self.assertEqual(disp["waived"], [])
        # a waiver filed this round lands in the waived bucket
        led = ledger.apply_update(f1, led, review(), ["F-2-1:not-today"])
        disp = ledger.round_dispositions(led, 3)
        self.assertEqual([f["id"] for f in disp["waived"]], ["F-2-1"])

    def test_resolved_tail_is_capped(self):
        f1 = self.facts_now()
        led = ledger.empty_ledger()
        for i in range(ledger.RESOLVED_TAIL_CAP + 3):
            led = ledger.apply_update(f1, led, review(
                findings=[finding(f"{self.LIB}::parse", self.LIB, why=f"w{i}")]), [])
            fid = f"F-{led['rounds']}-1"
            led = ledger.apply_update(f1, led, review(
                resolutions=[{"finding_id": fid, "addressed": True}]), [])
        self.assertEqual(len(led["resolved_tail"]), ledger.RESOLVED_TAIL_CAP)
        # most recent first
        self.assertEqual(led["resolved_tail"][0]["round_closed"], led["rounds"])


if __name__ == "__main__":
    unittest.main()
