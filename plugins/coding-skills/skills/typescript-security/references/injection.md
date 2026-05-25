# Injection Security Rules

Injection vulnerabilities allow attackers to execute arbitrary code, queries, or commands.

**Rules:**

1. SQL queries MUST use parameterized placeholders — NEVER concatenate or template-literal user input.
2. Command execution MUST use `execFile` / `spawn` with an arg array and `shell: false` — NEVER `exec` with string interpolation.
3. HTML output MUST rely on the framework's auto-escaping (React JSX) or DOMPurify — NEVER assemble HTML from template literals.
4. SSRF: outbound URLs MUST be validated against an allowlist and resolve to non-private addresses.

---

## SQL Injection — Critical

Building SQL queries by concatenating or template-literal-interpolating user input. Always use prepared statements with placeholders. The placeholder syntax varies by driver — `$1` for `pg`, `?` for `mysql2`/`better-sqlite3`, and ORM-specific binding for Prisma / Drizzle / Knex.

**Bad:**

```ts
const rows = await pool.query(`SELECT * FROM users WHERE name = '${input}'`);
const rows2 = await pool.query("SELECT * FROM users WHERE id = " + id);
await conn.query(`DELETE FROM orders WHERE id = ${orderId}`);
```

**Good:**

```ts
import { Pool } from "pg";
const pool = new Pool();

const rows = await pool.query("SELECT * FROM users WHERE name = $1", [input]);
await pool.query("DELETE FROM orders WHERE id = $1", [orderId]);
```

With `mysql2` (uses `?` placeholders):

```ts
import { createPool } from "mysql2/promise";
const pool = createPool({ /* ... */ });

const [rows] = await pool.execute(
    "SELECT * FROM users WHERE name = ? AND status = ?",
    [name, status],
);
```

With Prisma — bindings are automatic for the typed API; for raw queries use `$queryRaw` (tagged template) or `$queryRawUnsafe` with explicit parameters:

```ts
await prisma.user.findMany({ where: { name } });

const rows = await prisma.$queryRaw`SELECT * FROM users WHERE name = ${name}`;

const rows2 = await prisma.$queryRawUnsafe(
    "SELECT * FROM users WHERE name = $1",
    name,
);
```

With Drizzle — `sql` template tag parameterizes interpolations automatically:

```ts
import { sql } from "drizzle-orm";
const rows = await db.execute(sql`SELECT * FROM users WHERE name = ${name}`);
```

With Knex — query builder bindings or `.raw()` with bindings array:

```ts
const rows = await knex("users").where({ name });
const rows2 = await knex.raw("SELECT * FROM users WHERE name = ?", [name]);
```

### Dynamic IN clauses

Never build `IN (...)` by joining user strings. Generate numbered placeholders (or use the driver's array binding when available).

**Bad:**

```ts
const rows = await pool.query(
    `SELECT * FROM users WHERE id IN (${ids.join(",")})`,
);
```

**Good (pg with numbered placeholders):**

```ts
const placeholders = ids.map((_, i) => `$${i + 1}`).join(",");
const rows = await pool.query(
    `SELECT * FROM users WHERE id IN (${placeholders})`,
    ids,
);
```

**Good (pg array operator — single placeholder):**

```ts
const rows = await pool.query(
    "SELECT * FROM users WHERE id = ANY($1::int[])",
    [ids],
);
```

**Good (mysql2 array expansion):**

```ts
const [rows] = await pool.query(
    "SELECT * FROM users WHERE id IN (?)",
    [ids],
);
```

### Dynamic column names and ORDER BY

Placeholders only work for **values**, not identifiers (table/column names) or SQL keywords. Allowlist identifiers explicitly.

**Bad:**

```ts
const rows = await pool.query(`SELECT * FROM users ORDER BY ${sortCol}`);
```

**Good:**

```ts
const allowed: Record<string, string> = {
    name: "name",
    created: "created_at",
    email: "email",
};
const col = allowed[sortCol] ?? "created_at";
const rows = await pool.query(`SELECT * FROM users ORDER BY ${col}`);
```

### Dynamic WHERE filters

Build queries incrementally; parameterize every user-supplied value.

```ts
const conditions: string[] = [];
const args: unknown[] = [];

if (name) {
    args.push(name);
    conditions.push(`name = $${args.length}`);
}
if (minAge > 0) {
    args.push(minAge);
    conditions.push(`age >= $${args.length}`);
}

let query = "SELECT * FROM users";
if (conditions.length > 0) {
    query += ` WHERE ${conditions.join(" AND ")}`;
}
const rows = await pool.query(query, args);
```

### Prefer query builders over hand-rolled SQL

Prisma, Drizzle, and Knex parameterize bindings by default and reduce the temptation to fall back to string concatenation for complex queries. The raw-SQL escape hatches (`$queryRawUnsafe`, `knex.raw` without bindings) put the safety burden back on the caller — treat their use as a code smell that needs a security review.

---

## NoSQL Injection — High

MongoDB and similar databases accept query operators inside object values — an attacker who controls the shape of a query body (e.g., raw `req.body` passed to `find`) can inject `$ne`, `$gt`, `$regex` and bypass equality checks.

**Bad:**

```ts
await users.findOne({ username: req.body.username, password: req.body.password });
```

**Good:**

```ts
import { z } from "zod";
const schema = z.object({ username: z.string(), password: z.string() });
const { username, password } = schema.parse(req.body);
await users.findOne({ username, password });
```

---

## Command Injection — Critical

Passing unvalidated input to a shell command. `child_process.exec` and `execSync` spawn `/bin/sh -c <string>`, so any shell metacharacter in the interpolated value (`;`, `&&`, `` ` ``, `$()`) is interpreted. Use `execFile` or `spawn` with the executable name plus a separate args array, and never set `shell: true`.

**Bad:**

```ts
import { exec, execSync } from "node:child_process";

exec(`rm -f /tmp/${filename}`, (err, stdout) => { /* ... */ });
execSync(`grep ${pattern} ${file}`);
```

**Good:**

```ts
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import path from "node:path";

const execFileAsync = promisify(execFile);

const base = path.basename(filename);
if (base !== filename) {
    throw new Error("invalid filename");
}
await execFileAsync("rm", ["-f", path.join("/tmp", base)], { shell: false });
```

With `spawn` for streaming output:

```ts
import { spawn } from "node:child_process";

const child = spawn("grep", [pattern, file], { shell: false });
child.stdout.on("data", (chunk) => { /* ... */ });
```

### Allowlist the executable

When the binary itself comes from configuration, resolve it against an allowlist before invoking — otherwise an attacker who controls config can run arbitrary programs.

```ts
const allowedBinaries = new Set(["rg", "grep", "git"]);
if (!allowedBinaries.has(tool)) {
    throw new Error("tool not allowed");
}
await execFileAsync(tool, args, { shell: false });
```

---

## Code Injection — Critical

`eval`, `new Function(...)`, the `node:vm` module, and dynamic `require`/`import` of attacker-controlled module names all execute arbitrary code in the current process. None of these should ever touch untrusted input.

**Bad:**

```ts
import vm from "node:vm";

const result = eval(userExpression);
const fn = new Function("ctx", userScript);
vm.runInNewContext(userScript, sandbox);
```

**Good:**

```ts
import { evaluate } from "mathjs";
const result = evaluate(userExpression, { x: 1 });
```

For configuration-driven behaviour, route through an allowlist of named handlers rather than evaluating arbitrary code.

---

## Cross-Site Scripting (XSS) — High

XSS allows attackers to execute scripts in another user's browser session. The framework boundary matters: React/Vue/Svelte auto-escape interpolated values, but every framework has an escape hatch (`dangerouslySetInnerHTML`, `v-html`, `{@html ...}`) that bypasses that protection.

**Bad (React with `dangerouslySetInnerHTML`):**

```tsx
function Comment({ body }: { body: string }) {
    return <div dangerouslySetInnerHTML={{ __html: body }} />;
}
```

**Good (let React escape it as text):**

```tsx
function Comment({ body }: { body: string }) {
    return <div>{body}</div>;
}
```

**Good (sanitize first when rich HTML is genuinely required):**

```tsx
import DOMPurify from "isomorphic-dompurify";

function Comment({ body }: { body: string }) {
    const safe = DOMPurify.sanitize(body, {
        ALLOWED_TAGS: ["b", "i", "em", "strong", "a"],
        ALLOWED_ATTR: ["href"],
    });
    return <div dangerouslySetInnerHTML={{ __html: safe }} />;
}
```

### HTML built from template literals in plain Node

Plain HTTP handlers that build HTML with template literals have no auto-escaping — every interpolation is an XSS sink.

**Bad:**

```ts
res.setHeader("Content-Type", "text/html");
res.end(`<div>Welcome, ${name}!</div>`);
```

**Good:**

```ts
function escapeHtml(s: string): string {
    return s
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

res.setHeader("Content-Type", "text/html");
res.end(`<div>Welcome, ${escapeHtml(name)}!</div>`);
```

Prefer a template engine with auto-escaping on (Nunjucks, Eta, Handlebars) or move rendering to a JSX-based framework.

### `javascript:` URLs in attributes

User-controlled URLs interpolated into `href` or `src` attributes can carry `javascript:` schemes. Validate the scheme before rendering.

```tsx
function safeHref(raw: string): string | undefined {
    try {
        const u = new URL(raw, "https://example.com");
        return u.protocol === "http:" || u.protocol === "https:"
            ? u.toString()
            : undefined;
    } catch {
        return undefined;
    }
}
```

---

## Template Injection — High

Server-side template engines that compile templates from untrusted input (or render templates with `eval`-like helpers exposed) can execute arbitrary code on the server.

**Bad:**

```ts
import { compile } from "handlebars";
const tpl = compile(req.body.template);
res.end(tpl({ user }));
```

**Good:**

```ts
import { compile } from "handlebars";
const tpl = compile(STATIC_TEMPLATE_SOURCE);
res.end(tpl({ user, message: req.body.message }));
```

Keep templates as static, code-reviewed assets. Untrusted input goes into the **data**, never the **template source**.

---

## Prototype Pollution — High

Merging attacker-controlled JSON into a plain object via a recursive `merge` helper mutates `Object.prototype` when keys like `__proto__`, `constructor`, or `prototype` appear in the input. Once polluted, every object in the process inherits the attacker's properties.

**Bad:**

```ts
import merge from "lodash.merge";
const config = merge({}, defaults, req.body);
```

**Good:**

```ts
import { z } from "zod";

const ConfigSchema = z.object({
    name: z.string(),
    limit: z.number().int().nonnegative(),
});
const safeBody = ConfigSchema.parse(req.body);
const config = { ...defaults, ...safeBody };
```

For free-form maps, use `Object.create(null)` (no prototype to pollute) and reject reserved keys explicitly:

```ts
const FORBIDDEN = new Set(["__proto__", "constructor", "prototype"]);
const map = Object.create(null) as Record<string, unknown>;
for (const [k, v] of Object.entries(input)) {
    if (FORBIDDEN.has(k)) continue;
    map[k] = v;
}
```

---

## Server-Side Request Forgery (SSRF) — High

Forcing the server to make outbound requests to unintended endpoints — internal services, cloud metadata (`169.254.169.254`), or admin APIs reachable only from inside the network. Validate every user-supplied URL against an allowlist, resolve the hostname, and reject private / link-local / loopback addresses. Also disable transparent redirect following so an allowed host can't bounce to an internal one.

**Bad:**

```ts
const target = req.query.url as string;
const resp = await fetch(target);
```

**Good (allowlist + private-range check + manual redirects):**

```ts
import { lookup } from "node:dns/promises";
import net from "node:net";

const ALLOWED_HOSTS = new Set(["api.partner.com", "images.cdn.example"]);

function isPrivateIp(addr: string): boolean {
    if (net.isIPv4(addr)) {
        const [a, b] = addr.split(".").map(Number);
        if (a === 10) return true;
        if (a === 127) return true;
        if (a === 169 && b === 254) return true;
        if (a === 172 && b >= 16 && b <= 31) return true;
        if (a === 192 && b === 168) return true;
        return false;
    }
    if (net.isIPv6(addr)) {
        const lower = addr.toLowerCase();
        if (lower === "::1") return true;
        if (lower.startsWith("fc") || lower.startsWith("fd")) return true;
        if (lower.startsWith("fe80:")) return true;
        return false;
    }
    return true;
}

async function safeFetch(raw: string): Promise<Response> {
    const u = new URL(raw);
    if (u.protocol !== "https:" && u.protocol !== "http:") {
        throw new Error("invalid scheme");
    }
    if (!ALLOWED_HOSTS.has(u.hostname)) {
        throw new Error("host not allowlisted");
    }
    const { address } = await lookup(u.hostname);
    if (isPrivateIp(address)) {
        throw new Error("resolved to private address");
    }
    const resp = await fetch(u, { redirect: "manual" });
    if (resp.status >= 300 && resp.status < 400) {
        throw new Error("redirect blocked");
    }
    return resp;
}
```

The private ranges to block: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `127.0.0.0/8`, `169.254.0.0/16` (link-local, includes cloud metadata), `::1` (IPv6 loopback), `fc00::/7` (IPv6 unique-local), `fe80::/10` (IPv6 link-local).

With `undici` directly, set `maxRedirections: 0` and inspect the response:

```ts
import { request } from "undici";

const { statusCode, headers } = await request(u, { maxRedirections: 0 });
if (statusCode >= 300 && statusCode < 400) {
    throw new Error(`redirect to ${headers.location} blocked`);
}
```

### DNS rebinding

A hostname resolved at validation time can resolve to a different address at connection time. For high-assurance use cases, resolve the hostname once, validate the address, then connect to the IP directly (passing the original `Host` header for TLS SNI / virtual hosting).

---

## Unsafe Deserialization — Critical

`JSON.parse` is safe (it doesn't execute code), but downstream usage is not — fields still need schema validation. The dangerous patterns in Node are libraries that deserialize *with side effects*: `node-serialize`, the (deprecated) `funcster`, and YAML loaders that resolve typed tags (`!!js/function`).

**Bad:**

```ts
import yaml from "js-yaml";
const obj = yaml.load(req.body, { schema: yaml.DEFAULT_SCHEMA });
```

**Good:**

```ts
import yaml from "js-yaml";
import { z } from "zod";

const raw = yaml.load(req.body, { schema: yaml.FAILSAFE_SCHEMA });
const obj = ConfigSchema.parse(raw);
```

Always parse with the strictest schema available, then validate the result against a typed schema (zod, valibot, joi) before using any field.

---

## CWE References

- **CWE-78**: OS Command Injection
- **CWE-89**: SQL Injection
- **CWE-94**: Code Injection
- **CWE-79**: Cross-site Scripting (XSS)
- **CWE-918**: Server-Side Request Forgery (SSRF)
- **CWE-502**: Deserialization of Untrusted Data
- **CWE-1321**: Improperly Controlled Modification of Object Prototype Attributes
- **CWE-943**: Improper Neutralization of Special Elements in Data Query Logic
- **CWE-20**: Improper Input Validation
