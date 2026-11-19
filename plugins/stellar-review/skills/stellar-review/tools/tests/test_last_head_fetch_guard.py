"""Drift guard for the stellar-prep LAST-fetch (LABS-844): the ledger's
last_head is fetched with --depth=1 ONLY when the commit is missing
locally. On a shallow clone, an unconditional --depth=1 fetch of an
already-present LAST rewrites the shallow boundary and can sever the
commit from parents the repo already has — observed live in CI (the
merge-base resolved during input derivation, then incremental.py got
no-common-ancestor and the anchoring patch degraded to empty). The
present-locally guard (`git cat-file -e "$LAST^{commit}"`) must live in
ONE helper every mode routes through — a second forked spelling of the
fetch, or a call site that fetches before checking, reopens the bug."""

import os
import re
import unittest

from helpers import ROOT, read, region_between  # also puts tools/ on sys.path

PREP = os.path.join(ROOT, "scripts", "stellar-prep.sh")

HELPER = r"^fetch_last_head\(\) \{"
HELPER_END = r"^\}"
# The present-locally guard: skip the fetch when the commit is here.
GUARD = r'git cat-file -e "\$LAST\^\{commit\}"'
# Any git fetch naming LAST — spelling-agnostic, so a future edit cannot
# fork a second fetch variant outside the guard.
ANY_LAST_FETCH = r"git[^\n]*fetch[^\n]*LAST"


def helper_body():
    """The fetch_last_head function body, definition line through the
    closing brace at column 0."""
    return region_between(read(PREP), HELPER, HELPER_END, PREP)


class TestLastHeadFetchGuard(unittest.TestCase):
    def test_guard_runs_before_the_fetch(self):
        body = helper_body()
        guard = re.search(GUARD, body)
        fetches = list(re.finditer(ANY_LAST_FETCH, body))
        self.assertTrue(
            fetches, "stellar-prep.sh: fetch_last_head must fetch LAST"
        )
        self.assertIsNotNone(
            guard,
            "stellar-prep.sh: the LAST-fetch must be guarded by "
            'git cat-file -e "$LAST^{commit}"',
        )
        for m in fetches:
            self.assertLess(
                guard.start(),
                m.start(),
                "stellar-prep.sh: the present-locally guard must run "
                "before the LAST-fetch, never after it",
            )

    def test_one_spelling_no_last_fetch_outside_the_helper(self):
        text = read(PREP)
        outside = text.replace(helper_body(), "")
        self.assertNotRegex(
            outside,
            ANY_LAST_FETCH,
            "stellar-prep.sh: the LAST-fetch has one spelling "
            "(fetch_last_head); a fetch naming LAST anywhere else is a "
            "forked second copy",
        )
        self.assertNotRegex(
            outside,
            GUARD,
            "stellar-prep.sh: the present-locally guard has one spelling "
            "(inside fetch_last_head); a second copy at a call site forks "
            "the policy",
        )

    def test_all_modes_route_through_the_helper(self):
        # The helper carries both credential paths itself (local: the
        # repo's own; model/post: the endpoint library's git_authed —
        # the env-numbered credential channel, never a token on the
        # command line), so every mode — local, model, post — funnels
        # through the one guarded fetch.
        body = helper_body()
        self.assertIn('"$MODE" = "local"', body)
        self.assertRegex(body, r'git_authed "\$AUTH" fetch')
        # And the incremental branch invokes it — spelling-agnostic like
        # ANY_LAST_FETCH above: the name appears exactly twice, the
        # definition and the one call, however the call is written.
        occurrences = re.findall(r"\bfetch_last_head\b", read(PREP))
        self.assertEqual(
            len(occurrences),
            2,
            "stellar-prep.sh: fetch_last_head must appear exactly twice "
            "— the definition and the one call from the incremental "
            "branch; more = forked copies, fewer = an unguarded path "
            "returned",
        )


if __name__ == "__main__":
    unittest.main()
