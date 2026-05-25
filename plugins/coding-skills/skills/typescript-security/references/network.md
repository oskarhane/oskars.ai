# Network / Web Security Rules

Network-layer mistakes expose services to downgrade attacks, header-based browser exploits, CSRF, SSRF, open redirects, and session hijacking.

**Rules:**

1. TLS servers MUST set `minVersion: 'TLSv1.2'` and a vetted cipher list — never accept SSLv3 or TLSv1.0/1.1.
2. HTTP responses MUST set security headers (HSTS, CSP, X-Content-Type-Options, X-Frame-Options, Referrer-Policy) — use `helmet` or equivalent middleware.
3. Cookie-authenticated state-changing requests MUST be protected against CSRF via double-submit token or origin check.
4. Redirect targets MUST be validated against an allowlist of paths or hosts.
5. Outbound URLs from user input MUST be allowlisted by host AND blocked at the DNS layer for private/link-local IPs.
6. Token / MAC / hash comparisons MUST use `crypto.timingSafeEqual` on equal-length `Buffer`s.
7. Session IDs MUST be regenerated on login and on privilege change; cookies MUST carry `Secure`, `HttpOnly`, and `SameSite`.

---

## TLS Configuration — High

Defaults are reasonable on recent Node versions, but legacy code or copy-pasted configs may still allow TLSv1.0/1.1 or weak ciphers, enabling downgrade and known protocol attacks.

**Bad:**

```ts
import { createServer } from "node:https";
import { readFileSync } from "node:fs";

createServer({
  key: readFileSync("key.pem"),
  cert: readFileSync("cert.pem"),
  // no minVersion — older Node defaults accepted TLSv1
}).listen(443);
```

**Good:**

```ts
import { createServer } from "node:https";
import { readFileSync } from "node:fs";
import { constants } from "node:crypto";

createServer({
  key: readFileSync("key.pem"),
  cert: readFileSync("cert.pem"),
  minVersion: "TLSv1.2",
  ciphers: [
    "TLS_AES_256_GCM_SHA384",
    "TLS_CHACHA20_POLY1305_SHA256",
    "TLS_AES_128_GCM_SHA256",
    "ECDHE-ECDSA-AES256-GCM-SHA384",
    "ECDHE-RSA-AES256-GCM-SHA384",
    "ECDHE-ECDSA-CHACHA20-POLY1305",
    "ECDHE-RSA-CHACHA20-POLY1305",
  ].join(":"),
  honorCipherOrder: true,
  secureOptions:
    constants.SSL_OP_NO_SSLv2 |
    constants.SSL_OP_NO_SSLv3 |
    constants.SSL_OP_NO_TLSv1 |
    constants.SSL_OP_NO_TLSv1_1,
}).listen(443);
```

Prefer terminating TLS at a vetted proxy (nginx, Caddy, a managed load balancer) whose defaults are continuously updated. When TLS terminates upstream, set `app.set('trust proxy', ...)` correctly so the app sees real client IPs.

---

## Missing Security Headers — Medium

Without HSTS, CSP, and frame controls, browsers fall back to permissive behavior that enables clickjacking, MIME sniffing, mixed-content, and reflected XSS escalation.

**Bad:**

```ts
import express from "express";

const app = express();
app.use((_req, res, next) => {
  next();
});
```

No headers at all. Any reflected content runs with the page's full privilege.

**Good — helmet:**

```ts
import express from "express";
import helmet from "helmet";

const app = express();
app.use(
  helmet({
    contentSecurityPolicy: {
      directives: {
        defaultSrc: ["'self'"],
        scriptSrc: ["'self'"],
        styleSrc: ["'self'"],
        imgSrc: ["'self'", "data:"],
        connectSrc: ["'self'"],
        frameAncestors: ["'none'"],
        objectSrc: ["'none'"],
        baseUri: ["'self'"],
        formAction: ["'self'"],
      },
    },
    strictTransportSecurity: {
      maxAge: 63072000,
      includeSubDomains: true,
      preload: true,
    },
    referrerPolicy: { policy: "strict-origin-when-cross-origin" },
    crossOriginOpenerPolicy: { policy: "same-origin" },
    crossOriginResourcePolicy: { policy: "same-origin" },
  }),
);
```

**Good — manual middleware (frameworks without helmet):**

```ts
app.use((_req, res, next) => {
  res.setHeader("Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload");
  res.setHeader("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'");
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("X-Frame-Options", "DENY");
  res.setHeader("Referrer-Policy", "strict-origin-when-cross-origin");
  res.setHeader("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  next();
});
```

CSP nonces (`script-src 'self' 'nonce-<random>'`) are required if inline scripts are unavoidable. Generate the nonce per request with `randomBytes(16).toString("base64")`.

---

## CSRF — High

Cookie-authenticated browsers attach credentials to cross-site requests automatically. Without a CSRF defense, any state-changing endpoint is reachable from any origin.

**Bad:**

```ts
import express from "express";
import cookieParser from "cookie-parser";

const app = express();
app.use(cookieParser());
app.use(express.json());

app.post("/account/email", (req, res) => {
  // session pulled from cookie, no anti-CSRF token
  updateEmail(req.session.userId, req.body.email);
  res.sendStatus(204);
});
```

**Good — double-submit token (csrf-csrf):**

```ts
import express from "express";
import cookieParser from "cookie-parser";
import { doubleCsrf } from "csrf-csrf";

const { doubleCsrfProtection, generateToken } = doubleCsrf({
  getSecret: () => process.env.CSRF_SECRET!,
  cookieName: "__Host-csrf",
  cookieOptions: { sameSite: "lax", secure: true, httpOnly: true, path: "/" },
  size: 32,
  getTokenFromRequest: (req) => req.headers["x-csrf-token"] as string,
});

const app = express();
app.use(cookieParser());
app.use(express.json());

app.get("/csrf-token", (req, res) => {
  res.json({ token: generateToken(req, res) });
});

app.post("/account/email", doubleCsrfProtection, (req, res) => {
  updateEmail(req.session.userId, req.body.email);
  res.sendStatus(204);
});
```

CSRF protection is NOT needed for:

- Pure `Authorization: Bearer <token>` APIs where the browser does not auto-attach the token.
- Requests already pinned by `SameSite=Strict` cookies AND validated via `Origin` / `Sec-Fetch-Site` headers (defense-in-depth: still prefer a token for high-value flows).

CSRF protection IS needed for:

- Any cookie-authenticated form POST, PUT, PATCH, DELETE.
- GraphQL endpoints that accept cookie auth (even via POST).
- File upload endpoints.

Always pair tokens with `SameSite=Lax` (or `Strict` where UX permits) on the session cookie.

---

## Open Redirect — Medium

Redirecting to an attacker-controlled URL is the foundation of phishing and OAuth token theft.

**Bad:**

```ts
app.get("/login/callback", (req, res) => {
  const next = String(req.query.next ?? "/");
  res.redirect(next);
});
```

`next=https://evil.example/steal` redirects authenticated users off-site.

**Good — path-only allowlist:**

```ts
app.get("/login/callback", (req, res) => {
  const next = String(req.query.next ?? "/");
  if (!next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) {
    return res.redirect("/");
  }
  res.redirect(next);
});
```

`//evil.example` is parsed as a protocol-relative URL by browsers — reject leading `//` and `/\`.

**Good — host allowlist when off-site redirects are required:**

```ts
const ALLOWED_HOSTS = new Set(["app.example.com", "docs.example.com"]);

app.get("/redirect", (req, res) => {
  try {
    const url = new URL(String(req.query.url), "https://app.example.com");
    if (url.protocol !== "https:") return res.status(400).end();
    if (!ALLOWED_HOSTS.has(url.host)) return res.status(400).end();
    res.redirect(url.toString());
  } catch {
    res.status(400).end();
  }
});
```

`new URL` parses authority correctly — string-prefix checks like `target.startsWith("https://app.example.com")` are bypassed by `https://app.example.com.evil/`.

---

## SSRF — High

User-supplied URLs that the server fetches can reach internal services (`169.254.169.254` metadata, `127.0.0.1` admin ports, RFC1918 ranges) and exfiltrate secrets.

Defense layers:

1. Parse the URL with `new URL`; require `https:` (or `http:` if truly needed).
2. Allowlist hosts where possible. For broader fetches, allowlist by registered domain.
3. Resolve the hostname yourself and reject private/link-local/loopback ranges BEFORE the fetch — protect against DNS rebinding by pinning the resolved IP.
4. Disable redirect-following or re-validate each hop's resolved IP.

**Bad:**

```ts
app.get("/proxy", async (req, res) => {
  const url = String(req.query.url);
  const upstream = await fetch(url);
  res.send(await upstream.text());
});
```

**Good:**

```ts
import { lookup } from "node:dns/promises";
import { isIP } from "node:net";

const ALLOWED_HOSTS = new Set(["images.example.com", "cdn.example.com"]);

function isPrivate(ip: string): boolean {
  if (ip === "::1" || ip.startsWith("fc") || ip.startsWith("fd") || ip.startsWith("fe80")) return true;
  if (ip === "127.0.0.1" || ip.startsWith("10.") || ip.startsWith("192.168.")) return true;
  if (ip.startsWith("169.254.")) return true; // link-local + cloud metadata
  if (ip.startsWith("172.")) {
    const second = Number(ip.split(".")[1]);
    if (second >= 16 && second <= 31) return true;
  }
  return false;
}

app.get("/proxy", async (req, res) => {
  let parsed: URL;
  try {
    parsed = new URL(String(req.query.url));
  } catch {
    return res.status(400).end();
  }
  if (parsed.protocol !== "https:") return res.status(400).end();
  if (!ALLOWED_HOSTS.has(parsed.host)) return res.status(400).end();

  const target = isIP(parsed.hostname) ? parsed.hostname : (await lookup(parsed.hostname)).address;
  if (isPrivate(target)) return res.status(400).end();

  const upstream = await fetch(parsed.toString(), {
    redirect: "error",
    signal: AbortSignal.timeout(5000),
  });
  res.send(await upstream.text());
});
```

For higher assurance use the `undici` agent's `connect` hook to pin the dialed IP — this defeats DNS rebinding where the name resolves to a public IP at validation time and a private IP at connect time.

---

## Timing Attacks — Medium

`===` and `==` short-circuit on the first mismatched byte, leaking equal-prefix length to attackers via response-time measurement. Token, MAC, and signature comparisons must be constant-time.

**Bad:**

```ts
export function checkToken(input: string, expected: string): boolean {
  return input === expected;
}
```

**Good:**

```ts
import { timingSafeEqual } from "node:crypto";

export function checkToken(input: string, expected: string): boolean {
  const a = Buffer.from(input);
  const b = Buffer.from(expected);
  if (a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}
```

`timingSafeEqual` requires equal-length buffers; check lengths first and return early on mismatch (the length itself is not generally sensitive).

For HMAC verification:

```ts
import { createHmac, timingSafeEqual } from "node:crypto";

export function verifyHmac(message: Buffer, mac: Buffer, key: Buffer): boolean {
  const expected = createHmac("sha256", key).update(message).digest();
  if (mac.length !== expected.length) return false;
  return timingSafeEqual(mac, expected);
}
```

For passwords use `argon2.verify` or `bcrypt.compare` — both do constant-time comparison internally; never compare hashes by hand.

---

## Session Fixation & Hijacking — High

If the session ID survives login, an attacker who set a known ID in the victim's browser (via subdomain, URL parameter, or earlier XSS) can hijack the authenticated session.

**Bad:**

```ts
import session from "express-session";

app.use(session({
  secret: process.env.SESSION_SECRET!,
  resave: false,
  saveUninitialized: true,
  cookie: { httpOnly: true },
}));

app.post("/login", async (req, res) => {
  const user = await authenticate(req.body.email, req.body.password);
  if (!user) return res.sendStatus(401);
  req.session.userId = user.id;
  res.sendStatus(204);
});
```

Issues: session ID is unchanged across login, cookie lacks `Secure` / `SameSite`, no absolute or idle timeout.

**Good:**

```ts
import session from "express-session";

app.use(session({
  name: "__Host-sid",
  secret: process.env.SESSION_SECRET!,
  resave: false,
  saveUninitialized: false,
  rolling: true,
  cookie: {
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    path: "/",
    maxAge: 30 * 60 * 1000, // 30 min idle timeout
  },
}));

app.post("/login", async (req, res) => {
  const user = await authenticate(req.body.email, req.body.password);
  if (!user) return res.sendStatus(401);

  req.session.regenerate((err) => {
    if (err) return res.sendStatus(500);
    req.session.userId = user.id;
    req.session.loggedInAt = Date.now();
    res.sendStatus(204);
  });
});

const ABSOLUTE_TIMEOUT_MS = 12 * 60 * 60 * 1000;

app.use((req, res, next) => {
  if (req.session.loggedInAt && Date.now() - req.session.loggedInAt > ABSOLUTE_TIMEOUT_MS) {
    return req.session.destroy(() => res.sendStatus(401));
  }
  next();
});

app.post("/logout", (req, res) => {
  req.session.destroy(() => {
    res.clearCookie("__Host-sid", { path: "/" });
    res.sendStatus(204);
  });
});
```

Key points:

- `regenerate` on login, password change, MFA upgrade, and privilege escalation.
- `destroy` + clear cookie on logout — do not just unset `userId`.
- Idle timeout via `maxAge` + `rolling: true`. Absolute timeout via a stored `loggedInAt` timestamp.
- `__Host-` prefix forces `Secure`, `Path=/`, and no `Domain` attribute — see [Cookie Security](./cookies.md).
- Store sessions in a server-side store (Redis, Postgres) — the default in-memory store is not safe for production or multi-instance deployments.

---

## Server Timeouts — Medium

Without request timeouts, slow-client (Slowloris) attacks tie up connections until the process exhausts memory or file descriptors.

**Bad:**

```ts
import { createServer } from "node:http";

const server = createServer(handler);
server.listen(8080);
```

**Good:**

```ts
import { createServer } from "node:http";

const server = createServer(handler);
server.headersTimeout = 10_000;
server.requestTimeout = 30_000;
server.keepAliveTimeout = 5_000;
server.maxRequestsPerSocket = 1000;
server.listen(8080);
```

For Express, also enforce body-parser limits: `express.json({ limit: "100kb" })`. Apply per-route rate limits (`express-rate-limit`) on auth, signup, and password-reset endpoints.

---

## Bind to Localhost for Internal Services — Medium

Admin, metrics, and debug endpoints bound to `0.0.0.0` are reachable from any interface — including cloud-provider link-local networks.

**Bad:**

```ts
metricsServer.listen(9090, "0.0.0.0");
```

**Good:**

```ts
metricsServer.listen(9090, "127.0.0.1");
```

Or bind to a Unix socket consumed by a sidecar:

```ts
metricsServer.listen("/run/myapp/metrics.sock");
```

For public services that legitimately need external reach, pair with authentication and a reverse proxy that adds rate limiting and TLS.

---

## CWE References

- **CWE-319**: Cleartext Transmission of Sensitive Information
- **CWE-326**: Inadequate Encryption Strength
- **CWE-352**: Cross-Site Request Forgery (CSRF)
- **CWE-601**: URL Redirection to Untrusted Site (Open Redirect)
- **CWE-918**: Server-Side Request Forgery (SSRF)
- **CWE-208**: Observable Timing Discrepancy
- **CWE-384**: Session Fixation
- **CWE-613**: Insufficient Session Expiration
- **CWE-693**: Protection Mechanism Failure (missing security headers)
- **CWE-770**: Allocation of Resources Without Limits (Slowloris)
- **CWE-200**: Exposure of Sensitive Information
