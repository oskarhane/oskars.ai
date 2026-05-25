# Threat Modeling Guide

Systematic methodology for identifying and prioritizing security threats in TypeScript / Node.js applications.

See also: [SKILL.md](../SKILL.md) for the high-level skill overview and severity matrix.

## STRIDE Methodology

Apply STRIDE to every element in your system's data flow diagram. Each element type is susceptible to specific threat categories:

### STRIDE per Element Matrix

| DFD Element                                  | S   | T   | R   | I   | D   | E   |
| -------------------------------------------- | --- | --- | --- | --- | --- | --- |
| External Entity (browser, mobile app, API)   | X   |     | X   |     |     |     |
| Process (Express handler, Next.js route)     | X   | X   | X   | X   | X   | X   |
| Data Store (Postgres, Redis, S3, filesystem) |     | X   | X   | X   | X   |     |
| Data Flow (HTTP, WebSocket, BullMQ, Kafka)   |     | X   |     | X   | X   |     |

### TypeScript-Specific STRIDE Analysis

**Spoofing** — Can an attacker impersonate a user or service?

```ts
// Check: Is every endpoint behind authentication?
// Check: Are JWTs validated (algorithm pinned, issuer, audience, expiry)?
// Check: Is mTLS configured for service-to-service calls?
import express from "express";
import { requireAuth } from "./middleware/auth.js";

const app = express();
app.use("/api", requireAuth); // every API route enforces auth
```

**Tampering** — Can data be modified in transit or at rest?

```ts
// Check: Are all external inputs validated (zod / valibot)?
// Check: Is HMAC used for webhook / callback signature verification?
import { createHmac, timingSafeEqual } from "node:crypto";

function verifyWebhook(payload: Buffer, signatureHex: string, secret: string) {
  const expected = createHmac("sha256", secret).update(payload).digest();
  const provided = Buffer.from(signatureHex, "hex");
  if (provided.length !== expected.length) throw new Error("tampered payload");
  if (!timingSafeEqual(provided, expected)) throw new Error("tampered payload");
}
```

**Repudiation** — Can a user deny performing an action?

```ts
// Check: Are security-relevant actions logged with structured data?
import { pino } from "pino";
const logger = pino({ redact: ["req.headers.authorization", "*.password"] });

logger.info({
  event: "action_performed",
  userId,
  action: "delete_account",
  ip: req.ip,           // requires app.set('trust proxy', ...) set correctly
  ts: new Date().toISOString(),
});
```

**Information Disclosure** — Can sensitive data leak?

```ts
// Check: Are error messages generic to clients?
// Check: Are logs free of PII (pino redact, no secrets in stringified objects)?
// Check: Is TLS enforced (no rejectUnauthorized: false, minVersion TLSv1.2)?
// Check: Are debug surfaces (inspector, source maps, /debug routes) disabled in prod?
app.use((err: Error, _req, res, _next) => {
  logger.error({ err }, "request failed");      // detail goes to logs
  res.status(500).json({ error: "internal error" }); // generic to client
});
```

**Denial of Service** — Can the service be overwhelmed?

```ts
// Check: Are timeouts set on the HTTP server?
// Check: Are request body sizes limited?
// Check: Is rate limiting in place?
import express from "express";
import rateLimit from "express-rate-limit";

const app = express();
app.use(express.json({ limit: "100kb" }));
app.use(rateLimit({ windowMs: 60_000, max: 100 }));

const server = app.listen(3000);
server.headersTimeout = 10_000;
server.requestTimeout = 15_000;
server.keepAliveTimeout = 5_000;
```

**Elevation of Privilege** — Can a user gain unauthorized access?

```ts
// Check: Is authorization checked server-side on every request?
// Check: Are object references validated (no IDOR — user owns the resource)?
// Check: Are admin routes protected by a real permission check, not a UI flag?
app.delete("/api/projects/:id", requireAuth, async (req, res) => {
  const project = await db.project.findUnique({ where: { id: req.params.id } });
  if (!project || project.ownerId !== req.user.id) {
    return res.status(404).end(); // 404, not 403 — don't reveal existence
  }
  if (!req.user.permissions.includes("project:delete")) {
    return res.status(403).end();
  }
  await db.project.delete({ where: { id: project.id } });
  res.status(204).end();
});
```

---

## DREAD Risk Scoring

Score each identified threat to prioritize remediation:

| Factor              | 1-3 (Low)                            | 4-6 (Medium)                       | 7-10 (High)                              |
| ------------------- | ------------------------------------ | ---------------------------------- | ---------------------------------------- |
| **D**amage          | Minor info disclosure                | Partial data breach                | Full system compromise, data destruction |
| **R**eproducibility | Timing-dependent, hard to reproduce  | Reproducible with some effort      | Always reproducible, automated tools exist |
| **E**xploitability  | Custom exploit, advanced skills      | Basic tools available              | No skills required, public exploit exists |
| **A**ffected users  | Individual user                      | Subset of users                    | All users                                |
| **D**iscoverability | Requires insider knowledge           | Found via scanning                 | Publicly documented, obvious             |

**Score** = (D + R + E + A + D) / 5. Severity bands match [SKILL.md](../SKILL.md):

| Band     | Score   | Action                          |
| -------- | ------- | ------------------------------- |
| Critical | 8 – 10  | Fix immediately                 |
| High     | 6 – 7.9 | Fix in current sprint           |
| Medium   | 4 – 5.9 | Fix in next sprint              |
| Low      | 1 – 3.9 | Fix opportunistically           |

### Example: SQL Injection in an Express Login Handler

```ts
// Vulnerable: template literal interpolation into the SQL string
app.post("/login", async (req, res) => {
  const { email, password } = req.body;
  const rows = await pool.query(
    `SELECT id, pw_hash FROM users WHERE email = '${email}'`,
  );
  // ...
});
```

| Factor          | Score | Justification                                        |
| --------------- | ----- | ---------------------------------------------------- |
| Damage          | 9     | Full database access, credential theft               |
| Reproducibility | 9     | Consistent, automated tools (sqlmap) exploit easily  |
| Exploitability  | 8     | Well-documented attack, trivial payloads             |
| Affected Users  | 10    | All users with accounts                              |
| Discoverability | 7     | Scanners detect string-concatenated SQL trivially    |

**DREAD Score: 8.6 — Critical. Immediate remediation required.**

Fix: use parameterized queries (`$1` for `pg`, `?` for `mysql2`, prepared bindings in Prisma / Drizzle / Knex). See **[Injection Vulnerabilities](./injection.md)**.

### Example: Prototype Pollution via `Object.assign` on Body

```ts
// Vulnerable: merging request body directly into a config object
app.post("/api/settings", (req, res) => {
  Object.assign(currentSettings, req.body); // attacker sends {"__proto__": {"isAdmin": true}}
  res.json(currentSettings);
});
```

| Factor          | Score | Justification                                  |
| --------------- | ----- | ---------------------------------------------- |
| Damage          | 8     | Process-wide pollution, possible auth bypass   |
| Reproducibility | 9     | Single POST request                            |
| Exploitability  | 7     | Public PoCs widely known                       |
| Affected Users  | 8     | All users sharing the polluted process         |
| Discoverability | 6     | Detected by Semgrep / Snyk Code rules          |

**DREAD Score: 7.6 — High.** Fix: schema-validate with zod and reject `__proto__` / `constructor` / `prototype` keys; merge into `Object.create(null)`.

---

## Trust Boundary Analysis

Map where untrusted data enters your Node.js application. Trust boundaries are crossed whenever data moves from a less-trusted context to a more-trusted one — every crossing needs authentication, validation, and authorization.

```
                       ┌─────────────────────────────────────────┐
                       │            TRUST BOUNDARY                │
                       │                                          │
Internet ──→ [CDN/WAF] ──→ [Reverse Proxy] ──→ [Node.js Process] │
                       │                              │           │
                       │                       [Express / Next]   │
                       │                              │           │
                       │   ┌──────────────────────────┴────┐      │
                       │   │  Middleware stack:            │      │
                       │   │  - helmet (security headers)  │      │
                       │   │  - express.json({limit})      │      │
                       │   │  - rateLimit / Upstash        │      │
                       │   │  - requireAuth (JWT/session)  │      │
                       │   │  - zod-validate(body/params)  │      │
                       │   │  - authorize(resource, perm)  │      │
                       │   └──────────────┬────────────────┘      │
                       │                  │                       │
                       │           [Service Layer] ─→ [Redis]     │
                       │                  │                       │
                       │           [Postgres] (parameterized)     │
                       │                                          │
                       └──────────┬───────────────────────────────┘
                                  │
                          External APIs (TLS, signed webhooks)
                          Browser (HttpOnly cookies, CSP)
                          Workers (BullMQ — treat job data as untrusted)
```

Every arrow crossing the trust boundary needs:

1. **Authentication** — who is making this request?
2. **Input validation** — is the data well-formed and within bounds? (zod / valibot at the edge)
3. **Authorization** — is this caller allowed to perform this action on this resource?

Common boundaries that get forgotten:

- **BullMQ / SQS / Kafka job payloads** — jobs queued by one service and consumed by another are external input. Validate the payload.
- **Database rows written by other services** — a shared DB makes the other service part of your trust boundary. Validate on read if you don't control the writer.
- **`process.env`** — env vars are configuration, but in CI / container orchestration they can be set by less-trusted sources. Schema-validate startup config.
- **File uploads and `multer` fields** — content type, size, filename, and bytes are all attacker-controlled.

---

## OWASP Top 10 Mapping for TypeScript / Node.js

| Rank | Vulnerability                  | STRIDE | Node / TS Defense                                                                 |
| ---- | ------------------------------ | ------ | --------------------------------------------------------------------------------- |
| A01  | Broken Access Control          | E      | Server-side authz on every handler, RBAC, IDOR checks, route guards               |
| A02  | Cryptographic Failures         | I      | `node:crypto` AES-256-GCM, `randomBytes` / `randomUUID`, TLS 1.2+                 |
| A03  | Injection                      | T, E   | `pg` `$1` / `mysql2` `?` placeholders; `execFile` / `spawn` with arg arrays; JSX auto-escape; DOMPurify |
| A04  | Insecure Design                | All    | Threat modeling with STRIDE, defense-in-depth, secure defaults                    |
| A05  | Security Misconfiguration      | I, E   | helmet headers, no source maps in prod, no debug routes, TLS minVersion, `trust proxy` |
| A06  | Vulnerable Components          | All    | `npm audit`, `osv-scanner`, `snyk test`, Dependabot / Renovate, lockfile integrity |
| A07  | Authentication Failures        | S, E   | Argon2id (`argon2` package) or bcrypt, JWT algorithm pinning, MFA                  |
| A08  | Software / Data Integrity      | T      | npm provenance, `npm audit signatures`, signed releases, locked `package-lock.json` |
| A09  | Logging Failures               | R      | Structured logging with `pino`, redaction config, audit trails, no PII            |
| A10  | SSRF                           | I, T   | URL allowlists, parse host, block private / link-local ranges, no auto-redirects to new hosts |

---

## Conducting a Threat Model

1. **Scope** — identify system boundaries, assets to protect, and threat actors.
2. **Diagram** — draw a data flow diagram with trust boundaries (external entities, processes, data stores, data flows).
3. **STRIDE** — apply STRIDE to each DFD element using the matrix above.
4. **Score** — rate each threat with DREAD.
5. **Prioritize** — fix Critical / High first; document accepted risks with explicit justification.
6. **Verify** — run `npm audit`, `npx osv-scanner --lockfile=package-lock.json`, `npx snyk test`, `npx semgrep --config p/typescript --config p/owasp-top-ten`, `npx eslint --ext .ts,.tsx .` to validate mitigations.
7. **Iterate** — update the model when the system changes (new endpoints, new data flows, new integrations).

---

## Vulnerability Severity Matrix

Use when no DREAD data is available — cross-reference impact with exploitability:

| Impact \ Exploitability | Easy     | Moderate | Difficult |
| ----------------------- | -------- | -------- | --------- |
| Critical                | Critical | Critical | High      |
| High                    | Critical | High     | Medium    |
| Medium                  | High     | Medium   | Low       |
| Low                     | Medium   | Low      | Low       |

---

See also:

- [SKILL.md](../SKILL.md) — overview, severity levels, common mistakes.
- [Security Architecture](./architecture.md) — defense-in-depth, Zero Trust, auth patterns, rate limiting, anti-patterns.
