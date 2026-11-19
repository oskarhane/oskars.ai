"""Drift guard for the one local-round entry point: local pre-push
stellar rounds run the plugin's scripts/stellar-prep.sh local, the same
pipeline body CI's `model` mode runs — never a hand-rolled subset of
Step 0 (the abbreviated hand-copy let CI re-find findings the local
round never saw). SKILL.md's Step 0 must lead with the script invocation
and forbid the hand-rolled subset; the script must offer the `local`
mode that invocation depends on and cite Step 0's scope rule instead of
restating it; the quick-mode contract (pre-filter, never a gate; the
full round stays mandatory before every push) must appear in BOTH the
script's usage and SKILL.md in the same words; and the CI template must
keep calling the CI modes — so the two pipelines cannot silently
diverge again."""

import os
import re
import unittest

from helpers import ROOT, read, region_between  # also puts tools/ on sys.path

SKILL = os.path.join(ROOT, "skills", "stellar-review", "SKILL.md")
PREP = os.path.join(ROOT, "scripts", "stellar-prep.sh")
TEMPLATE = os.path.join(ROOT, "templates", "ci", "stellar-review.yml")

# The one-command local round, as SKILL.md Step 0 must spell it (the
# plugin-root token is translated per harness at load/registration time;
# on disk it is the literal ${CLAUDE_PLUGIN_ROOT}).
LOCAL_INVOCATION = r"\$\{CLAUDE_PLUGIN_ROOT\}/scripts/stellar-prep\.sh local"
# The manual-reference marker: the old hand-copy path, which must stay
# below the one-command lead, never above it.
MANUAL_MARKER = re.compile(r"^TOOLS=", re.M)
# The quick-mode contract, in the same words on every surface that
# states it (stellar-prep.sh's usage comment and SKILL.md Step 0).
QUICK_PREFILTER = re.compile(r"Quick is a PRE-FILTER, never a gate")
QUICK_FULL_ROUND_MANDATORY = re.compile(
    r"the full round \(carried ledger \+ expansion \+ shards\) "
    r"is still mandatory before every push"
)
# The mode-choice comparison, same words on the docs surface — an agent
# chooses modes by it. Matching runs on whitespace-collapsed prose
# because the surfaces hard-wrap lines mid-sentence.
COMPARISON = re.compile(
    r"[Aa] clean quick round does NOT predict a clean CI round; "
    r"a clean full round is the best local predictor of CI's verdict"
)
# every `git merge-base ...` call outside comment lines, any number per line
COMMENT_LINE = re.compile(r"(?m)^[ \t]*#.*$")
MERGE_BASE_CALL = re.compile(r"git (merge-base [^;)\n]*)")

# The base-ref override: STELLAR_BASE_REF replaces the hardcoded
# origin/main so repos on other default branches resolve round-1 bases.
BASE_REF_ENV = re.compile(r'\$\{STELLAR_BASE_REF:-origin/main\}')


def step0():
    """SKILL.md's Step 0 section, through the next `## ` heading."""
    return region_between(read(SKILL), r"^## Step 0 ", r"^## ", SKILL)


def local_branch():
    """stellar-prep.sh's local-mode input derivation branch."""
    return region_between(
        read(PREP), r'^if \[ "\$MODE" = "local" \]; then', r"^else$", PREP
    )


def merge_base_calls(region):
    """Every `git merge-base ...` call in a shell region, outside comment
    lines, in order — one scanner for the guard and its self-test."""
    return [c.strip() for c in MERGE_BASE_CALL.findall(COMMENT_LINE.sub("", region))]


def unwrapped(text):
    """Whitespace-collapsed text, so a sentence matches across the
    surface's own line wrapping."""
    return re.sub(r"\s+", " ", text)


def comment_prose(path):
    """The leading `#` comment block of a shell script as one prose line
    (shebang, comment padding, and line wraps removed), so a contract
    sentence matches however the comment is wrapped. One normalizer for
    the result: the same whitespace collapse `unwrapped` applies."""
    lines = []
    for line in read(path).splitlines():
        if line.startswith("#!"):
            continue
        if not line.startswith("#"):
            break
        lines.append(line[1:].strip())
    return unwrapped(" ".join(part for part in lines if part))


class TestLocalRoundEntry(unittest.TestCase):
    def test_step0_leads_with_the_script_invocation(self):
        region = step0()
        lead = re.search(LOCAL_INVOCATION, region)
        self.assertIsNotNone(
            lead,
            "SKILL.md Step 0: the local round must be spelled as the "
            "stellar-prep.sh local invocation, not as hand-rolled steps",
        )
        manual = MANUAL_MARKER.search(region)
        self.assertIsNotNone(
            manual, "SKILL.md Step 0: the manual reference block is missing"
        )
        self.assertLess(
            lead.start(),
            manual.start(),
            "SKILL.md Step 0: the one-command local round must lead; the "
            "manual steps are the reference below it",
        )

    def test_step0_forbids_the_hand_rolled_subset(self):
        self.assertRegex(
            step0(),
            r"ALWAYS run the script.*never a hand-rolled subset",
            "SKILL.md Step 0: must state that local rounds always use the "
            "script, never a hand-rolled subset of the steps",
        )

    def test_prep_offers_the_local_mode(self):
        self.assertRegex(
            read(PREP),
            re.escape("usage: stellar-prep.sh model|post|local [--quick] [PR_NUMBER]"),
            "stellar-prep.sh: SKILL.md's local invocation requires a local "
            "mode (with the --quick flag) on the script",
        )

    def test_quick_contract_stated_identically_on_both_surfaces(self):
        # quick is a pre-filter, never a gate: the contract must appear,
        # in the same words, in the script's usage comment AND SKILL.md's
        # local-round section — one surface weakening it fails here
        for label, text in ((PREP, comment_prose(PREP)), (SKILL, unwrapped(step0()))):
            with self.subTest(surface=os.path.basename(label)):
                self.assertRegex(
                    text,
                    QUICK_PREFILTER,
                    f"{label}: quick mode must be stated as a PRE-FILTER, "
                    "never a gate",
                )
                self.assertRegex(
                    text,
                    QUICK_FULL_ROUND_MANDATORY,
                    f"{label}: the full round must be stated as still "
                    "mandatory before every push",
                )

    def test_prep_local_cites_the_step0_scope_rule(self):
        # the scope rule's one spelling lives in SKILL.md Step 0; the
        # script's local branch must cite it, never restate it
        branch = local_branch()
        self.assertRegex(
            branch,
            r"SKILL\.md Step 0",
            "stellar-prep.sh: the local branch must cite SKILL.md Step 0's "
            "scope rule instead of restating it",
        )

    def test_diverged_last_head_falls_back_to_the_default_branch_merge_base(self):
        # LABS-955: a rebased branch's stale last_head must not widen the
        # scope via merge-base(LAST, HEAD). The fallback ref is
        # parameterized by STELLAR_BASE_REF (default origin/main) so a
        # repo on another default branch still resolves its real base.
        branch = local_branch()
        self.assertRegex(branch, BASE_REF_ENV)
        calls = merge_base_calls(branch)
        self.assertEqual(
            calls,
            ['merge-base --is-ancestor "$LAST" "$HEAD_SHA" 2>/dev/null',
             'merge-base HEAD "$BASE_REF"'],
        )

    def test_comparison_sentence_kept_on_the_skill_surface(self):
        self.assertRegex(
            unwrapped(step0()),
            COMPARISON,
            "SKILL.md: the quick-vs-full comparison sentence must stay, so "
            "an agent can choose a mode informed",
        )

    def test_ci_template_still_calls_the_model_and_post_modes(self):
        text = read(TEMPLATE)
        for mode in ("model", "post"):
            with self.subTest(mode=mode):
                self.assertRegex(
                    text,
                    r'(?m)^ *"\$STELLAR_ROOT/scripts/stellar-prep\.sh" ' + mode + r' *$',
                    f"templates/ci/stellar-review.yml: CI must keep calling "
                    f"stellar-prep.sh {mode}",
                )


class TestMergeBaseScanner(unittest.TestCase):
    """Self-test of the scanner the guard above relies on."""

    def test_catches_a_call_after_a_semicolon(self):
        # a forbidden call appended after `;` on an allowed line must
        # surface as its own extracted call
        line = (
            'git merge-base --is-ancestor "$LAST" "$HEAD_SHA" 2>/dev/null'
            '; git merge-base "$LAST" "$HEAD_SHA"\n'
        )
        self.assertEqual(
            merge_base_calls(line),
            ['merge-base --is-ancestor "$LAST" "$HEAD_SHA" 2>/dev/null',
             'merge-base "$LAST" "$HEAD_SHA"'],
        )

    def test_ignores_comment_lines(self):
        self.assertEqual(merge_base_calls("# git merge-base x\n"), [])


if __name__ == "__main__":
    unittest.main()
