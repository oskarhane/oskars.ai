// Tests for scripts/bump-versions.mjs, the lockstep bump for gbuild's two
// manifests. Spawns the script as a subprocess (the way the release process
// invokes it) against fixture manifests in a throwaway temp dir — never the
// real package.json / .claude-plugin/plugin.json — covering the three bump
// levels and the version-drift refusal. Run via repo-root `npm test`.
import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { dirname, join } from "node:path"
import test from "node:test"
import { fileURLToPath } from "node:url"

const root = dirname(fileURLToPath(import.meta.url))
const script = join(root, "scripts", "bump-versions.mjs")

// The script must exist where the contract says it does — the assertions below
// spawn it via its documented relative path instead.
assert.ok(existsSync(script), `missing ${script}`)

// Fixtures modeled on the real manifests' formatting — including the inline
// keywords array a re-serializing bump would clobber — so the byte-exact
// assertions below prove only the version line moved.
const packageJsonText = (version: string) => `{
  "name": "opencode-gbuild",
  "version": "${version}",
  "type": "module",
  "keywords": ["fixture", "inline", "array"]
}
`

const pluginJsonText = (version: string) => `{
  "name": "gbuild",
  "version": "${version}",
  "description": "fixture standing in for .claude-plugin/plugin.json"
}
`

const writeFixtures = (packageVersion: string, pluginVersion: string = packageVersion) => {
  const dir = mkdtempSync(join(tmpdir(), "gbuild-bump-"))
  const packageJson = join(dir, "package.json")
  const pluginJson = join(dir, "plugin.json")
  writeFileSync(packageJson, packageJsonText(packageVersion))
  writeFileSync(pluginJson, pluginJsonText(pluginVersion))
  return { packageJson, pluginJson }
}

// The documented invocation, run the way the release process runs it: node
// scripts/bump-versions.mjs <level> with plugins/gbuild/ as the cwd, paths
// overridden at the fixtures. `root` is plugins/gbuild/ wherever the runner
// starts from, so this holds under repo-root `npm test` too.
const bump = (level: string, packageJson: string, pluginJson: string) =>
  spawnSync(
    process.execPath,
    ["scripts/bump-versions.mjs", level, "--package-json", packageJson, "--plugin-json", pluginJson],
    { cwd: root, encoding: "utf8" },
  )

test("patch, minor and major each bump both manifests from 0.11.0 and print the new version", () => {
  for (const [level, expected] of [
    ["patch", "0.11.1"],
    ["minor", "0.12.0"],
    ["major", "1.0.0"],
  ] as const) {
    const { packageJson, pluginJson } = writeFixtures("0.11.0")
    const r = bump(level, packageJson, pluginJson)
    assert.equal(r.status, 0, `${level}: bump failed: ${r.stderr}`)
    assert.equal(r.stdout, `${expected}\n`, `${level}: stdout is exactly the new semver`)
    assert.equal(readFileSync(packageJson, "utf8"), packageJsonText(expected), `${level}: package.json rewritten`)
    assert.equal(readFileSync(pluginJson, "utf8"), pluginJsonText(expected), `${level}: plugin.json rewritten`)
  }
})

test("disagreeing manifests: exits nonzero, names both files, rewrites nothing", () => {
  const { packageJson, pluginJson } = writeFixtures("0.11.0", "0.10.9")
  const before = [readFileSync(packageJson, "utf8"), readFileSync(pluginJson, "utf8")]
  const r = bump("patch", packageJson, pluginJson)
  assert.notEqual(r.status, 0, "drift must fail the bump")
  assert.ok(r.stderr.includes(packageJson), "message names the package manifest")
  assert.ok(r.stderr.includes(pluginJson), "message names the plugin manifest")
  assert.equal(readFileSync(packageJson, "utf8"), before[0], "package.json untouched")
  assert.equal(readFileSync(pluginJson, "utf8"), before[1], "plugin.json untouched")
})

test("an unknown level is rejected with usage before anything runs", () => {
  const { packageJson, pluginJson } = writeFixtures("0.11.0")
  const before = [readFileSync(packageJson, "utf8"), readFileSync(pluginJson, "utf8")]
  const r = bump("premajor", packageJson, pluginJson)
  assert.notEqual(r.status, 0)
  assert.match(r.stderr, /usage: node scripts\/bump-versions\.mjs/)
  assert.equal(readFileSync(packageJson, "utf8"), before[0], "package.json untouched")
  assert.equal(readFileSync(pluginJson, "utf8"), before[1], "plugin.json untouched")
})
