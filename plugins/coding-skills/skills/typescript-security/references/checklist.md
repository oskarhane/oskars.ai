# Security Review Checklist

Severity: Critical, High, Medium, Low

## Input Handling

- [ ] **High** All user input validated at trust boundaries with a schema validator (zod, valibot, joi, class-validator) — internal code trusts the boundary
- [ ] **High** Validators use allowlists, not blocklists — blocklists always miss something
- [ ] **High** Output sanitized per context (HTML, SQL, shell, URL, JSON) — context-dependent escaping
- [ ] **High** No TypeScript `any` or unchecked `as` casts at trust boundaries — types lie when runtime data is untrusted
- [ ] **High** `JSON.parse` of attacker-controlled input is followed by schema validation that rejects `__proto__`, `constructor`, `prototype` keys — raw parse can carry polluted keys
- [ ] **Medium** Length, depth, and array-size limits enforced on parsed payloads — prevents memory abuse and DoS
- [ ] **Medium** `Content-Type` and charset validated on request bodies — wrong parser path leaks structure

## Database

- [ ] **Critical** SQL queries use parameterized placeholders (`pg` `$1`, `mysql2` `?`, Prisma / Drizzle / Knex bindings) — keeps data and code separate
- [ ] **Critical** No template literals or string concatenation building SQL with user input — single biggest injection vector
- [ ] **Critical** ORM raw-query escape hatches (`prisma.$queryRawUnsafe`, `knex.raw`) used only with bound parameters
- [ ] **High** NoSQL queries reject operator-shaped objects from user input (`$ne`, `$gt`, `$where`) — operator injection bypasses auth
- [ ] **High** Identifiers (table / column names) come from an allowlist, not user input — placeholders only bind values
- [ ] **Medium** DB connection user has least-privilege grants — limits blast radius of a successful injection

## Code Execution

- [ ] **Critical** No `child_process.exec` / `execSync` with interpolated input — shell metacharacters enable injection
- [ ] **Critical** Subprocesses use `execFile` / `spawn` with an arg array and `shell: false` — separates command from arguments
- [ ] **Critical** No `eval`, `new Function`, `vm.runInNewContext`, `vm.runInThisContext` on untrusted input — direct RCE
- [ ] **Critical** No dynamic `require()` / `import()` of user-controlled paths — module-graph injection
- [ ] **Critical** No deserialization of untrusted data via `node-serialize`, `funcster`, or YAML loaders that allow tags — can trigger arbitrary constructors
- [ ] **High** Worker threads / child processes started from a fixed allowlist of scripts — not user-derived paths

## Cryptography

- [ ] **High** Security-critical randomness uses `node:crypto` (`randomBytes`, `randomUUID`, `randomInt`) — `Math.random` is predictable
- [ ] **High** Uses vetted algorithms (AES-256-GCM, Argon2id, bcrypt, ChaCha20-Poly1305) — custom crypto hasn't been analyzed
- [ ] **High** Passwords hashed with Argon2id (preferred) or bcrypt — intentionally slow to resist brute-force
- [ ] **High** Secret comparison uses `crypto.timingSafeEqual` on equal-length `Buffer`s — `===` short-circuits and leaks timing
- [ ] **Critical** No hardcoded secrets, keys, or tokens in source — leak via VCS, logs, backups
- [ ] **High** Symmetric encryption uses authenticated mode (AES-GCM) with unique IVs — CBC/ECB without MAC is tamperable
- [ ] **High** Asymmetric keys are ≥2048-bit RSA or ≥256-bit ECDSA / Ed25519 — short keys are factorable
- [ ] **Medium** HMAC used for message authentication where AEAD is not available — prevents tampering

## Web Security

- [ ] **High** TLS configured with `minVersion: 'TLSv1.2'` (prefer 1.3) and modern cipher suites — older versions have known attacks
- [ ] **High** XSS-prone sinks (`dangerouslySetInnerHTML`, `innerHTML`, `document.write`, `v-html`) reviewed and either avoided or wrapped with DOMPurify — direct XSS
- [ ] **High** React / template output relied on for auto-escaping; never bypass without sanitization
- [ ] **Medium** Security headers set via `helmet()` or equivalent (HSTS, CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy) — prevents framing, sniffing, downgrade
- [ ] **Medium** CSRF protection on state-changing cookie-authenticated requests (CSRF tokens or SameSite=strict + custom header check) — prevents cross-origin action forgery
- [ ] **Medium** Open redirects validated against an allowlist of paths/hosts — attackers use your domain to redirect to phishing
- [ ] **High** SSRF defenses: outbound URLs validated against host allowlist; resolved IPs rejected if private / link-local / loopback; redirects disabled or re-validated — server-side request forgery hits internal services
- [ ] **Medium** Cookies set `httpOnly`, `secure`, `sameSite`; session cookies use `__Host-` prefix where applicable — defense in depth on the session
- [ ] **Medium** CORS allowlist is explicit (no `Access-Control-Allow-Origin: *` with credentials) — wildcard + credentials exposes session

## Authentication / Authorization

- [ ] **High** Authentication uses vetted middleware / library (Passport, NextAuth, Lucia, Auth.js, etc.) — rolling your own session is a footgun
- [ ] **High** Session tokens generated from `crypto.randomBytes` (≥128 bits) — predictable tokens hijackable
- [ ] **High** Authorization enforced on every privileged action (handler, route guard, server action) — not just at login
- [ ] **High** JWT tokens validated for algorithm (no `alg: none`), signature, issuer, audience, and expiry — unsigned / unverified JWTs bypass auth
- [ ] **High** JWT secrets / signing keys rotated; HS256 secrets ≥256 bits — weak keys forgeable
- [ ] **High** Logout / password-change invalidates active sessions server-side — stolen tokens otherwise live until expiry
- [ ] **High** No client-supplied identity headers trusted (`X-User-Id`, `X-Is-Admin`) — trivially forged
- [ ] **Medium** `app.set('trust proxy', …)` configured correctly behind a reverse proxy — wrong setting lets clients forge `X-Forwarded-For`
- [ ] **Medium** Multi-factor / step-up for sensitive actions (admin, money movement, key rotation) — limits credential-theft blast radius

## Errors / Error Handling

- [ ] **Medium** Responses return generic error messages to clients — detailed errors help attackers map your system
- [ ] **Medium** Detailed errors and stack traces logged server-side only — never serialized into HTTP responses
- [ ] **Medium** Framework error handlers configured (Express error middleware, Next.js error boundaries) so unhandled errors don't leak internals
- [ ] **Critical** No swallowed errors around crypto, auth, or I/O (`try { … } catch { /* ignore */ }`) — may proceed unencrypted or unauthenticated
- [ ] **Medium** Database / ORM errors not surfaced to clients — reveals schema and query structure
- [ ] **Low** Error codes are stable identifiers (not internal exception class names) — avoids leaking implementation

## Dependencies

- [ ] **High** `npm audit` (or `pnpm audit` / `yarn npm audit`) passes at the policy threshold — catches known CVEs in the dependency tree
- [ ] **High** `npm audit signatures` passes — verifies package provenance against the registry
- [ ] **High** `snyk test` / `osv-scanner --lockfile=package-lock.json` run in CI — second source for advisories
- [ ] **High** Dependencies updated regularly via Renovate / Dependabot — unpatched deps are the #1 attack vector
- [ ] **Medium** New dependencies reviewed for maintenance status, weekly downloads, and known incidents before adoption
- [ ] **Medium** `package-lock.json` / `pnpm-lock.yaml` committed and CI installs with `npm ci` — reproducible, no opportunistic upgrades
- [ ] **Medium** Postinstall / lifecycle scripts audited or disabled (`npm ci --ignore-scripts` in CI where viable) — supply-chain RCE vector

## Async / Concurrency

- [ ] **High** No module-level mutable state shared across requests in middleware or route handlers — async races corrupt data and can leak between users
- [ ] **High** Per-request context kept in `AsyncLocalStorage` or per-handler closures, not module globals
- [ ] **High** Critical sections that span `await` boundaries are protected (DB transactions with appropriate isolation, advisory locks, or atomic operations) — interleaved awaits break invariants
- [ ] **High** Prototype-pollution defenses applied to objects merged from untrusted JSON: schema validation before merge, `Object.create(null)` for maps, reject `__proto__` / `constructor` / `prototype` keys, consider `Object.freeze(Object.prototype)` at process start — pollution propagates process-wide
- [ ] **Medium** `Promise.all` / `Promise.allSettled` failures handled — unhandled rejections crash the process on modern Node
- [ ] **Medium** Long-running async work uses `AbortSignal` and respects client disconnects — prevents resource exhaustion
- [ ] **Medium** Request body size limited (`express.json({ limit })`, `body-parser` limits, `fastify` `bodyLimit`) — prevents memory exhaustion
- [ ] **Medium** HTTP server has `requestTimeout`, `headersTimeout`, `keepAliveTimeout` set — prevents Slowloris

## Tooling

- [ ] **High** `npm audit` runs in CI and blocks on policy-relevant advisories
- [ ] **High** `npm audit signatures` runs in CI to verify package provenance
- [ ] **High** ESLint configured with `eslint-plugin-security` and `eslint-plugin-no-secrets` — catches common sinks and committed secrets at lint time
- [ ] **High** `snyk test` runs in CI (or as a pre-merge check) for a second advisory source
- [ ] **High** `osv-scanner --lockfile=package-lock.json` runs in CI — OSV.dev advisory coverage
- [ ] **Medium** `semgrep --config p/typescript` (plus `p/owasp-top-ten`, `p/nodejsscan`) runs in CI — pattern-based vulnerability detection
- [ ] **Medium** Property-based tests (`fast-check`) cover parsers, validators, and authz predicates — fuzz-like coverage of edge cases
- [ ] **Low** Secret scanning (gitleaks, trufflehog, GitHub secret scanning) enabled on the repo — catches committed credentials
