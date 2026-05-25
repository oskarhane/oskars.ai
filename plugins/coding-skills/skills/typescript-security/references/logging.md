# Logging Security Rules

Logs are a security surface. Tokens, cookies, request bodies, and PII that land in logs end up in log aggregators, backups, and developer terminals — multiplying the blast radius of any compromise.

**Rules:**

1. Secrets, tokens, cookies, and authorization headers MUST NEVER be logged.
2. PII MUST be redacted at the logger — passwords, emails, names, IPs (where required), and personal data.
3. Logs MUST be structured (JSON) — user input is never used as the format string.
4. Error messages returned to users MUST NOT expose internals; full detail goes to server-side logs only.

---

## Use Structured (JSON) Logging by Default

`pino` is the de-facto Node.js structured logger — fast, JSON-by-default, and ships built-in redaction. Use it (or an equivalent: `winston`, `bunyan`) instead of `console.log` / `console.error` in any production code.

```ts
import { pino } from 'pino';

export const logger = pino({
  level: process.env.LOG_LEVEL ?? 'info',
  // JSON output is the default; configured for clarity below
  formatters: {
    level: (label) => ({ level: label }),
  },
  timestamp: pino.stdTimeFunctions.isoTime,
});
```

Use it via key/value fields, never via string interpolation of user input:

```ts
logger.info({ userId, action: 'login' }, 'user logged in');
```

---

## Pino Redaction — High

`pino` redacts fields at JSON-serialize time, so secrets and PII never reach stdout / your log shipper. Configure redaction once at logger creation.

```ts
import { pino } from 'pino';

export const logger = pino({
  level: process.env.LOG_LEVEL ?? 'info',
  redact: {
    paths: [
      // request headers
      'req.headers.authorization',
      'req.headers.cookie',
      'req.headers["set-cookie"]',
      'req.headers["x-api-key"]',
      'req.headers["x-csrf-token"]',
      // response headers
      'res.headers["set-cookie"]',
      // common payload fields
      '*.password',
      '*.passwordHash',
      '*.token',
      '*.accessToken',
      '*.refreshToken',
      '*.apiKey',
      '*.secret',
      '*.sessionId',
      // nested user payloads
      'user.password',
      'user.email',
      'user.phone',
      'user.ssn',
      'body.password',
      'body.creditCard',
    ],
    censor: '[REDACTED]',
    remove: false,                     // keep the key but blank the value
  },
});
```

Verify the config catches what you expect — `redact` paths are not wildcards over arbitrary depths; `*.password` matches `*.password` one level deep, not `a.b.password`. Add explicit paths for nested structures.

For Express integrations, `pino-http` automatically attaches `req` / `res` to log records, so the `req.headers.*` redact paths above kick in for free:

```ts
import pinoHttp from 'pino-http';
import { logger } from './logger';

app.use(pinoHttp({ logger }));
```

---

## Sensitive Data in Logs — Medium

Logging an entire user or request object is the single most common way secrets leak.

**Bad:**

```ts
interface User {
  id: string;
  email: string;
  passwordHash: string;
  apiToken: string;
}

function handleLogin(user: User): void {
  logger.info({ user }, 'user login');   // DON'T: leaks passwordHash, apiToken
}
```

**Good:**

```ts
function handleLogin(user: User): void {
  logger.info(
    { userId: user.id },                // log identifiers, not payloads
    'user login',
  );
}
```

Even with `redact` configured, don't rely on it as the only defense — pass only the fields you intend to log.

---

## Log Injection — Low

Log injection happens when user input is concatenated into a log line, letting an attacker forge fake log entries (CRLF newlines), break log parsers, or smuggle ANSI escapes into terminal-tailed logs.

Structured logging (pino's key/value form) eliminates the format-string class of bug entirely — the value goes into a JSON field, not into the message template.

**Bad:**

```ts
// DON'T: raw user input as format string / concatenated message
console.log(`User logged in: ${req.body.username}`);
logger.info(`login ${req.body.username}`);
```

**Good:**

```ts
// Structured: username is a JSON field, not part of the format
logger.info({ username: req.body.username }, 'user login');
```

If you must emit a human-readable message that includes user data (e.g. into a non-JSON sink), strip control characters first:

```ts
function sanitizeForLog(s: string): string {
  // strip ASCII control chars except \t; \n is escaped by JSON encoding anyway
  return s.replace(/[\x00-\x08\x0B-\x1F\x7F]/g, '');
}
```

---

## PII Redaction — Medium

What counts as PII depends on jurisdiction and your privacy posture (GDPR, CCPA, HIPAA). At minimum, treat as PII:

- Email addresses, phone numbers, full names
- Government IDs (SSN, passport, national ID)
- Credit card / bank details (PCI scope)
- Precise location, IP addresses (in many EU jurisdictions)
- Health information (HIPAA scope)
- Date of birth

Strategies:

```ts
// 1. Don't log it at all — log a stable identifier instead
logger.info({ userId }, 'profile updated');

// 2. Hash for correlation without storing the original
import { createHash } from 'node:crypto';
const emailHash = createHash('sha256').update(email.toLowerCase()).digest('hex').slice(0, 16);
logger.info({ emailHash }, 'signup attempted');

// 3. Mask for human readability
function maskEmail(email: string): string {
  const [local, domain] = email.split('@');
  if (!local || !domain) return '[invalid]';
  return `${local[0]}***@${domain}`;
}
logger.info({ email: maskEmail(email) }, 'password reset requested');
```

IP addresses: redact the last octet (IPv4) or last 80 bits (IPv6) where local law requires anonymization:

```ts
function anonymizeIp(ip: string): string {
  if (ip.includes(':')) return ip.split(':').slice(0, 3).join(':') + '::';
  const parts = ip.split('.');
  return parts.length === 4 ? `${parts[0]}.${parts[1]}.${parts[2]}.0` : '[invalid]';
}
```

---

## Information Leakage in Error Responses — Medium

Stack traces, DB error text, and internal paths help attackers map your system. Log them server-side; return a generic message to the client.

**Bad:**

```ts
app.get('/users/:id', async (req, res) => {
  try {
    const user = await db.getUser(req.params.id);
    res.json(user);
  } catch (err) {
    // DON'T: leaks internal error text
    res.status(500).json({ error: (err as Error).message });
  }
});
```

**Good:**

```ts
app.get('/users/:id', async (req, res) => {
  try {
    const user = await db.getUser(req.params.id);
    res.json(user);
  } catch (err) {
    logger.error({ err, userId: req.params.id }, 'user fetch failed');
    res.status(500).json({ error: 'Internal server error' });
  }
});
```

`pino` serializes `Error` instances correctly via its built-in `err` serializer — you get `message`, `type`, and `stack` as structured fields.

---

## Never Log These

| Field | Why |
| --- | --- |
| Authorization header (`Bearer …`, `Basic …`) | Direct credential theft |
| `Cookie` / `Set-Cookie` headers | Session hijacking |
| Password, password hash, password reset token | Credential exposure |
| API keys, OAuth tokens, JWTs | Account takeover |
| CSRF tokens | Bypass of CSRF defense |
| Full request body of auth endpoints (`/login`, `/register`, `/reset`) | Contains plaintext credentials |
| Full credit card / bank numbers | PCI violation |
| Private keys, signing keys | Crypto compromise |

For auth endpoints specifically, log only **outcome** + a stable user identifier:

```ts
app.post('/login', async (req, res) => {
  const result = await auth.verify(req.body);
  logger.info(
    { outcome: result.ok ? 'success' : 'failure', userId: result.userId ?? null },
    'login attempt',
  );
  // NOT: logger.info({ body: req.body }) — req.body contains the password
  // ...
});
```

---

## Log Storage Hygiene

- Logs MUST go to a managed log aggregator (Datadog, CloudWatch, Loki, etc.) — not flat files an attacker can read after a partial breach.
- Set retention to the minimum your compliance posture requires.
- Restrict who can read production logs (separate role, audited access).
- Local log files MUST have restrictive permissions (`0o600`) and be rotated.

---

## Log Security Checklist

- [ ] Structured JSON logger (pino / winston / bunyan) — no raw `console.log` in production code paths
- [ ] `redact` configured for `authorization`, `cookie`, `set-cookie`, `password`, `token`, API keys
- [ ] No user input passed as a format/template string — always pass as a structured field
- [ ] PII redacted, hashed, or omitted per your privacy posture
- [ ] Request bodies of auth endpoints NOT logged
- [ ] Error responses to clients are generic; full detail in server logs only
- [ ] Logs centralized in a managed aggregator with restricted access
- [ ] Retention policy set; old logs purged on schedule
- [ ] Periodic review: grep production logs for the redaction tokens (`[REDACTED]`) and confirm they appear where expected

---

## CWE References

- **CWE-532**: Insertion of Sensitive Information into Log File
- **CWE-117**: Improper Output Neutralization for Logs
- **CWE-209**: Information Exposure Through an Error Message
- **CWE-200**: Exposure of Sensitive Information
- **CWE-312**: Cleartext Storage of Sensitive Information
- **CWE-359**: Exposure of Private Personal Information
