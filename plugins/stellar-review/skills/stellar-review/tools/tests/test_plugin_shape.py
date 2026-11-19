"""Shape guard for the plugin's single-source layout. The pass agents
ship once, in agents/ (Claude Code plugin-agent format; OpenCode
dispatches general subagents that read the same files — see index.ts's
runtime notes). Every `${CLAUDE_PLUGIN_ROOT}` path an agent or SKILL.md
references must resolve to a real file or directory in this plugin, so a
renamed or moved asset fails here instead of in a review round."""

import os
import re
import unittest

from helpers import PASSES, ROOT, read, split_frontmatter  # also puts tools/ on sys.path

AGENTS = os.path.join(ROOT, "agents")
SKILL = os.path.join(ROOT, "skills", "stellar-review", "SKILL.md")

# A plugin-root reference plus its optional path suffix (stops at
# whitespace, brackets, quotes and backticks).
PLUGIN_REF = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}(/[A-Za-z0-9_./-]+)?")


def referenced_paths(text):
    """Every (path, suffix) an asset references through the plugin-root
    token; bare `${CLAUDE_PLUGIN_ROOT}` mentions carry no path."""
    out = []
    for m in PLUGIN_REF.finditer(text):
        suffix = m.group(1)
        if suffix:
            out.append((os.path.join(ROOT, suffix.lstrip("/")), suffix))
    return out


class TestAgentShape(unittest.TestCase):
    def test_one_agent_file_per_pass(self):
        for name in PASSES:
            path = os.path.join(AGENTS, f"stellar-{name}.md")
            self.assertTrue(os.path.exists(path), path)

    def test_claude_frontmatter_on_every_agent(self):
        for name in PASSES:
            path = os.path.join(AGENTS, f"stellar-{name}.md")
            fm, body = split_frontmatter(read(path))
            self.assertIn(f"name: stellar-{name}", fm, name)
            self.assertRegex(fm, r"(?m)^description: ", name)
            self.assertIn("tools: Read, Grep, Glob", fm, name)
            self.assertIn(f"**{name}**", body, name)

    def test_agent_reading_lists_resolve(self):
        for name in PASSES:
            path = os.path.join(AGENTS, f"stellar-{name}.md")
            with self.subTest(agent=f"stellar-{name}"):
                refs = referenced_paths(read(path))
                self.assertTrue(refs, "the reading list must use plugin-root paths")
                for resolved, suffix in refs:
                    self.assertTrue(
                        os.path.exists(resolved),
                        f"stellar-{name} references {suffix}, which does not exist",
                    )

    def test_mandate_files_exist(self):
        for name in PASSES:
            p = os.path.join(ROOT, "skills", "stellar-review", "passes", f"{name}.md")
            self.assertTrue(os.path.exists(p), p)
        refs = ("full-checklist.md", "finding-schema.md", "severity-rubric.md")
        for r in refs:
            p = os.path.join(ROOT, "skills", "stellar-review", "references", r)
            self.assertTrue(os.path.exists(p), p)


class TestSkillShape(unittest.TestCase):
    def test_frontmatter(self):
        fm, _ = split_frontmatter(read(SKILL))
        self.assertIn("name: stellar-review", fm)
        self.assertRegex(fm, r"(?m)^description: ", "description required")
        self.assertIn("disable-model-invocation: true", fm)

    def test_plugin_refs_resolve(self):
        refs = referenced_paths(read(SKILL))
        self.assertTrue(refs, "SKILL.md must reference its assets via plugin-root paths")
        for resolved, suffix in refs:
            self.assertTrue(
                os.path.exists(resolved),
                f"SKILL.md references {suffix}, which does not exist",
            )

    def test_prep_script_and_tools_ship(self):
        for p in (
            os.path.join(ROOT, "scripts", "stellar-prep.sh"),
            os.path.join(ROOT, "scripts", "lib", "review-endpoints.sh"),
            os.path.join(ROOT, "skills", "stellar-review", "tools", "ledger.py"),
            os.path.join(ROOT, "skills", "stellar-review", "tools", "post.py"),
        ):
            self.assertTrue(os.path.exists(p), p)


if __name__ == "__main__":
    unittest.main()
