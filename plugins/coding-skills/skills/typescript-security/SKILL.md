---
name: typescript-security
description: "Security best practices and vulnerability prevention for TypeScript and Node.js. Covers injection (SQL, command, XSS, SSRF), cryptography, filesystem safety, network security, cookies, secrets management, prototype pollution, async race conditions, and logging. Targets Express, Next.js, NestJS, and plain Node servers. Apply when writing, reviewing, or auditing TypeScript/Node code for security, or when working on any risky code involving crypto, I/O, secrets management, user input handling, or authentication. Includes configuration of security tools."
user-invocable: true
license: MIT
compatibility: Designed for Claude Code or similar AI coding agents, and for projects using TypeScript on Node.js (Express, Next.js, NestJS, plain Node).
metadata:
  author: oskarhane
  version: "0.1.0"
allowed-tools: Read Edit Write Glob Grep Bash(npm:*) Bash(npx:*) Bash(node:*) Bash(git:*) Bash(eslint:*) Bash(snyk:*) Bash(semgrep:*) Agent WebFetch WebSearch AskUserQuestion
---

**Persona:** You are a senior TypeScript / Node.js security engineer. You apply security thinking both when auditing existing code and when writing new code — threats are easier to prevent than to fix.

**Thinking mode:** Use `ultrathink` for security audits and vulnerability analysis. Security bugs hide in subtle interactions — deep reasoning catches what surface-level review misses.

**Modes:**

- **Review mode** — reviewing a PR for security issues. Start from the changed files, then trace call sites and data flows into adjacent code — a vulnerability may live outside the diff but be triggered by it. Sequential.
- **Audit mode** — full codebase security scan. Launch up to 5 parallel sub-agents (via the Agent tool), each covering an independent vulnerability domain: (1) injection patterns, (2) cryptography and secrets, (3) web security and headers, (4) authentication and authorization, (5) async safety, prototype pollution, and dependency vulnerabilities. Aggregate findings, score with DREAD, and report by severity.
- **Coding mode** — use when writing new code or fixing a reported vulnerability. Follow the skill's sequential guidance. Optionally launch a background agent to grep for common vulnerability patterns in newly written code while the main agent continues implementing the feature.

# TypeScript / Node.js Security

## Overview

Security in TypeScript/Node.js follows the principle of **defense in depth**: protect at multiple layers, validate all inputs, use secure defaults, and leverage Node's built-in security-aware APIs (`node:crypto`, `node:path`, `node:fs`) and the ecosystem's vetted libraries (helmet, zod, argon2). TypeScript's static type system rules out a class of bugs but does nothing for runtime trust boundaries — values arriving from the network are `any` in spirit even when typed `string`.

## Security Thinking Model

Before writing or reviewing code, ask three questions:

1. **What are the trust boundaries?** — Where does untrusted data enter the system? (HTTP requests, file uploads, environment variables, message queues, database rows written by other services, third-party webhooks)
2. **What can an attacker control?** — Which inputs flow into sensitive operations? (SQL queries, shell commands, HTML output, file paths, cryptographic operations, object keys when merging JSON)
3. **What is the blast radius?** — If this defense fails, what's the worst outcome? (Data leak, RCE, privilege escalation, denial of service, prototype pollution propagating across the process)

## Severity Levels

| Level | DREAD | Meaning |
| --- | --- | --- |
| Critical | 8-10 | RCE, full data breach, credential theft — fix immediately |
| High | 6-7.9 | Auth bypass, significant data exposure, broken crypto — fix in current sprint |
| Medium | 4-5.9 | Limited exposure, session issues, defense weakening — fix in next sprint |
| Low | 1-3.9 | Minor info disclosure, best-practice deviations — fix opportunistically |

Levels align with [DREAD scoring](./references/threat-modeling.md).

## Research Before Reporting

Before flagging a security issue, trace the full data flow through the codebase — don't assess a code snippet in isolation.

1. **Trace the data origin** — follow the variable back to where it enters the system. Is it user input, a hardcoded constant, or an internal-only value?
2. **Check for upstream validation** — look for input validation (zod, valibot, joi, class-validator), sanitization, type parsing, or allow-listing earlier in the call chain.
3. **Examine the trust boundary** — if the data never crosses a trust boundary (e.g., internal service-to-service with mTLS), the risk profile is different.
4. **Read the surrounding code, not just the diff** — middleware, route guards, interceptors, or wrapper functions may already provide a layer of defense.

**Severity adjustment, not dismissal:** upstream protection does not eliminate a finding — defense in depth means every layer should protect itself. But it changes severity: a SQL concatenation reachable only through a strict zod parser is medium, not critical. Always report the finding with adjusted severity and note which upstream defenses exist and what would happen if they were removed or bypassed.

**When downgrading or skipping a finding:** add a brief inline comment (e.g., `// security: SQL concat safe here — input is validated by parseUserId() which returns number`) so the decision is documented, reviewable, and won't be re-flagged by future audits.

## Threat Modeling (STRIDE)

Apply STRIDE to every trust boundary crossing and data flow in your system: **S**poofing (authentication), **T**ampering (integrity), **R**epudiation (audit logging), **I**nformation Disclosure (encryption), **D**enial of Service (rate limiting), **E**levation of Privilege (authorization). Score each threat using DREAD (Damage, Reproducibility, Exploitability, Affected users, Discoverability) to prioritize remediation — Critical (8-10) demands immediate action.

For the full methodology with TypeScript examples, DFD trust boundaries, DREAD scoring, and OWASP Top 10 mapping, see **[Threat Modeling Guide](./references/threat-modeling.md)**.

## Quick Reference

| Severity | Vulnerability | Defense | TypeScript / Node Solution |
| --- | --- | --- | --- |
| Critical | SQL Injection | Parameterized queries separate data from code | `pg` `$1` / `mysql2` `?` placeholders; Prisma, Drizzle, Knex bindings |
| Critical | Command Injection | Pass args separately, never via shell concatenation | `child_process.execFile` / `spawn` with arg array, `shell: false` |
| High | XSS | Auto-escaping renders user data as text, not HTML/JS | React JSX (auto-escapes), avoid `dangerouslySetInnerHTML`, DOMPurify for HTML |
| High | Path Traversal | Scope file access to a root, prevent `../` escapes | `path.resolve` + prefix check, `fs.realpath`, reject `..` segments |
| Medium | Timing Attacks | Constant-time comparison avoids byte-by-byte leaks | `crypto.timingSafeEqual(Buffer.from(a), Buffer.from(b))` |
| High | Crypto Issues | Use vetted algorithms; never roll your own | `node:crypto` AES-256-GCM, `randomBytes`, `randomUUID` |
| Medium | HTTP Security | TLS + security headers prevent downgrade attacks | `https.createServer`, `minVersion: 'TLSv1.2'`, helmet middleware |
| Low | Missing Headers | HSTS, CSP, X-Frame-Options prevent browser attacks | `helmet()` or manual security headers middleware |
| Medium | Rate Limiting | Rate limits prevent brute-force and resource exhaustion | `express-rate-limit`, `@upstash/ratelimit`, server timeouts |
| High | Prototype Pollution | Merging attacker JSON into objects mutates `Object.prototype` | `Object.create(null)`, reject `__proto__` / `constructor` / `prototype` keys, schema-validate first |
| High | Async Race on Shared State | Module-level mutable state mutated across concurrent requests | Avoid module-level mutable singletons; per-request context; atomic DB ops; locks for true critical sections |
| High | SSRF | User-supplied URLs hit internal services | URL allowlist, parse host, block private/link-local ranges, disable redirects to new hosts |

## Detailed Categories

For complete examples, code snippets, and CWE mappings, see:

- **[Cryptography](./references/cryptography.md)** — Algorithms, key derivation, randomness, TLS configuration.
- **[Injection Vulnerabilities](./references/injection.md)** — SQL, command, template injection, XSS, SSRF.
- **[Filesystem Security](./references/filesystem.md)** — Path traversal, zip slip, file permissions, symlinks, temp files.
- **[Network/Web Security](./references/network.md)** — SSRF, open redirects, HTTP headers, CSRF, timing attacks, session fixation.
- **[Cookie Security](./references/cookies.md)** — `Secure`, `HttpOnly`, `SameSite`, `__Host-` prefix, signed cookies.
- **[Secrets Management](./references/secrets.md)** — Hardcoded credentials, `process.env`, `--env-file`, secret managers.
- **[Logging Security](./references/logging.md)** — PII in logs, log injection, `pino` redaction.
- **[Threat Modeling Guide](./references/threat-modeling.md)** — STRIDE, DREAD scoring, trust boundaries, OWASP Top 10.
- **[Security Architecture](./references/architecture.md)** — Defense-in-depth, Zero Trust, auth patterns, rate limiting, anti-patterns.

## Code Review Checklist

For the full security review checklist organized by domain (input handling, database, code execution, crypto, web, auth, errors, dependencies, async/concurrency), see **[Security Review Checklist](./references/checklist.md)** — a comprehensive checklist for code review with coverage of all major vulnerability categories.

## Tooling & Verification

### Static Analysis & Linting

Security-relevant tooling for TypeScript / Node.js:

```bash
npm audit
npm audit signatures

npx eslint --ext .ts,.tsx .
# with eslint-plugin-security, eslint-plugin-no-secrets, @typescript-eslint

npx snyk test
npx snyk monitor

npx semgrep --config p/typescript --config p/owasp-top-ten --config p/nodejsscan .

npx osv-scanner --lockfile=package-lock.json
```

Recommended ESLint plugins: `eslint-plugin-security`, `eslint-plugin-no-secrets`, `@typescript-eslint/eslint-plugin`, `eslint-plugin-n` (Node-specific safety), `eslint-plugin-no-unsanitized`.

### Security Testing

```bash
node --test
node --test --experimental-test-coverage

npx fast-check
```

Use `fast-check` for property-based tests on parsers, validators, and any function that maps untrusted strings to typed values — fuzz-like coverage catches edge cases that example-based tests miss.

## Common Mistakes

| Severity | Mistake | Fix |
| --- | --- | --- |
| High | `Math.random()` for tokens | Output is predictable. Use `node:crypto.randomBytes` or `crypto.randomUUID()` |
| Critical | SQL string concatenation / template literals into query | Attacker can modify query logic. Use parameterized queries (`pg` `$1`, `mysql2` `?`, Prisma, Drizzle) |
| Critical | `child_process.exec` with interpolated input | Shell interprets metacharacters. Use `execFile` / `spawn` with an arg array and `shell: false` |
| Critical | `eval`, `new Function`, `vm` on user input | Direct RCE. Never do this — refactor to a parser or interpreter you control |
| High | Trusting unsanitized input | Validate at trust boundaries with zod / valibot / joi — internal code trusts the boundary, so catching bad input there protects everything |
| Critical | Hardcoded secrets | Secrets in source code end up in version history, CI logs, and backups. Use env vars or secret managers |
| Medium | Comparing secrets with `===` | `===` short-circuits, leaking timing info. Use `crypto.timingSafeEqual` on equal-length `Buffer`s |
| Medium | Detailed errors in responses | Stack traces and DB errors help attackers map your system. Return generic messages, log details server-side |
| High | Merging attacker-controlled JSON into plain objects | Prototype pollution propagates across the process. Schema-validate first; use `Object.create(null)`; reject `__proto__` keys |
| High | MD5 / SHA1 / SHA-256 for passwords | Fast hashes — brute-forceable. Use Argon2id (`argon2` package) or bcrypt (`bcrypt` / `bcryptjs`) |
| High | AES without GCM (or rolling crypto) | ECB/CBC modes lack authentication — attacker can modify ciphertext undetected. Use `aes-256-gcm` |
| Medium | Binding to `0.0.0.0` by default | Exposes service to all network interfaces. Bind to a specific interface to limit attack surface |
| High | `dangerouslySetInnerHTML` with untrusted HTML | Direct XSS. Render as text, or sanitize with DOMPurify before injecting |
| High | Module-level mutable state across requests | Async races corrupt data or leak between users. Keep per-request state in request-scoped context (AsyncLocalStorage) |

## Security Anti-Patterns

| Severity | Anti-Pattern | Why It Fails | Fix |
| --- | --- | --- | --- |
| High | Security through obscurity | Hidden URLs are discoverable via fuzzing, logs, or source | Authentication + authorization on all endpoints |
| High | Trusting client headers | `X-Forwarded-For`, `X-Is-Admin` are trivially forged | Server-side identity verification; configure `app.set('trust proxy', …)` correctly |
| High | Client-side authorization | JavaScript checks are bypassed by any HTTP client | Server-side permission checks on every handler / route guard |
| High | Shared secrets across envs | Staging breach compromises production | Per-environment secrets via secret manager |
| Critical | Ignoring crypto / I/O errors | `try { … } catch { /* swallow */ }` may proceed unencrypted or unauthenticated | Always handle errors — fail closed, never open |
| Critical | Rolling your own crypto | Custom encryption hasn't been analyzed by cryptographers | Use `node:crypto` AES-GCM, `argon2`, vetted libraries |

See **[Security Architecture](./references/architecture.md)** for detailed anti-patterns with TypeScript code examples.

## Cross-References

More language-specific coding skills (e.g., `python-security`, `rust-security`) are planned in this same `coding-skills` plugin. Until they ship, treat the principles here as language-agnostic where the framework matters less than the trust model.

## Additional Resources

- [Node.js Security Best Practices](https://nodejs.org/en/learn/getting-started/security-best-practices)
- [OWASP Node.js Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Nodejs_Security_Cheat_Sheet.html)
- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Snyk Vulnerability Database](https://security.snyk.io/)
- [npm audit docs](https://docs.npmjs.com/cli/v10/commands/npm-audit)
- [helmet](https://helmetjs.github.io/)
