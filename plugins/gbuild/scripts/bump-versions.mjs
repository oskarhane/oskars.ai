// Lockstep version bump for gbuild's two manifests — package.json (npm) and
// .claude-plugin/plugin.json (Claude Code) — so a release can never ship the
// two disagreeing. Run from plugins/gbuild/:
//
//   node scripts/bump-versions.mjs <patch|minor|major> \
//     [--package-json <path>] [--plugin-json <path>]
//
// Both path flags exist so tests can point at fixture manifests instead of the
// real ones; they default to this plugin's checked-in files (resolved from the
// script's own location, so the cwd does not matter). Prints the new version —
// and nothing else — on stdout. Exits 1 without rewriting anything when the
// two manifests already disagree, a version is not plain x.y.z, or a file is
// unreadable or invalid JSON. Run via repo-root `npm test`.
import { readFileSync, writeFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

const USAGE =
  "usage: node scripts/bump-versions.mjs <patch|minor|major> [--package-json <path>] [--plugin-json <path>]"

const LEVELS = new Set(["patch", "minor", "major"])
const SEMVER = /^\d+\.\d+\.\d+$/
const pluginRoot = join(dirname(fileURLToPath(import.meta.url)), "..")

const die = (message) => {
  process.stderr.write(`bump-versions: ${message}\n`)
  process.exit(1)
}

// `<level> [--package-json <path>] [--plugin-json <path>]`, level first.
const parseArgs = (argv) => {
  const [level, ...flags] = argv
  const overrides = {}
  for (let i = 0; i < flags.length; i++) {
    const flag = flags[i]
    const key = flag === "--package-json" ? "packageJson" : flag === "--plugin-json" ? "pluginJson" : null
    if (!key) die(`unknown argument: ${flag}\n${USAGE}`)
    const value = flags[++i]
    if (!value || value.startsWith("--")) die(`${flag} needs a path\n${USAGE}`)
    overrides[key] = value
  }
  if (!level || !LEVELS.has(level)) die(`level must be one of patch|minor|major, got: ${level ?? "(none)"}\n${USAGE}`)
  return {
    level,
    packageJson: overrides.packageJson ?? join(pluginRoot, "package.json"),
    pluginJson: overrides.pluginJson ?? join(pluginRoot, ".claude-plugin", "plugin.json"),
  }
}

const readManifest = (path) => {
  let text
  try {
    text = readFileSync(path, "utf8")
  } catch {
    return die(`cannot read ${path}`)
  }
  let json
  try {
    json = JSON.parse(text)
  } catch (error) {
    return die(`${path} is not valid JSON: ${error.message}`)
  }
  if (typeof json.version !== "string" || !SEMVER.test(json.version)) {
    return die(`${path} has no plain x.y.z version field: ${JSON.stringify(json.version)}`)
  }
  return { text, version: json.version }
}

const bump = (version, level) => {
  const [major, minor, patch] = version.split(".").map(Number)
  if (level === "major") return `${major + 1}.0.0`
  if (level === "minor") return `${major}.${minor + 1}.0`
  return `${major}.${minor}.${patch + 1}`
}

// Swap the version value in the raw text rather than re-serializing, so a bump
// diff is exactly one line: key order, the inline keywords array, indentation
// and the trailing newline all survive byte-for-byte. The old value is
// anchored (dots escaped) and must match exactly once.
const setVersion = (path, text, from, to) => {
  const needle = new RegExp(`"version"(\\s*:\\s*)"${from.replace(/\./g, "\\.")}"`, "g")
  const hits = text.match(needle)
  if (!hits || hits.length !== 1) {
    return die(`${path}: expected exactly one "version": "${from}" entry, found ${hits?.length ?? 0}`)
  }
  return text.replace(needle, `"version"$1"${to}"`)
}

const { level, packageJson, pluginJson } = parseArgs(process.argv.slice(2))
const pkg = readManifest(packageJson)
const manifest = readManifest(pluginJson)
if (pkg.version !== manifest.version) {
  die(
    `manifest versions disagree: ${packageJson} has ${pkg.version}, ${pluginJson} has ${manifest.version} — align them first`,
  )
}

const next = bump(pkg.version, level)
const rewritten = [
  { path: packageJson, text: setVersion(packageJson, pkg.text, pkg.version, next) },
  { path: pluginJson, text: setVersion(pluginJson, manifest.text, manifest.version, next) },
]
// Both rewrites are validated before either file is touched, so a failure
// anywhere leaves both manifests exactly as they were.
for (const { path, text } of rewritten) {
  const json = JSON.parse(text)
  if (json.version !== next) die(`${path}: rewrite lost the version field`)
}
for (const { path, text } of rewritten) writeFileSync(path, text)

process.stdout.write(`${next}\n`)
