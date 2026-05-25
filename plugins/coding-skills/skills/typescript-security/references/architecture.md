# Security Architecture Patterns

Defense-in-depth, Zero Trust, and authentication patterns for TypeScript / Node.js services.

See also: [SKILL.md](../SKILL.md) for the high-level skill overview, and [Threat Modeling Guide](./threat-modeling.md) for STRIDE / DREAD and trust boundary analysis.

## Defense-in-Depth Layers

Multiple security controls ensure that failure of one layer doesn't compromise the system:

```
Layer 1: PERIMETER   — Rate limiting, DDoS mitigation, WAF
Layer 2: NETWORK     — TLS / mTLS, network segmentation, private VPCs
Layer 3: APPLICATION — Input validation, auth, authz, secure coding
Layer 4: DATA        — Encryption at rest / in transit, access controls, backups
```

### Node.js Implementation by Layer

**Layer 1 — Rate Limiting Middleware (single instance):**

```ts
import express from "express";
import rateLimit from "express-rate-limit";

const app = express();

// Global limiter — coarse defense against bursty abuse
app.use(
  rateLimit({
    windowMs: 60_000,      // 1 minute
    max: 100,              // per IP
    standardHeaders: "draft-7",
    legacyHeaders: false,
  }),
);

// Stricter limiter on sensitive endpoints
app.post(
  "/login",
  rateLimit({ windowMs: 60_000, max: 5, skipSuccessfulRequests: true }),
  loginHandler,
);
```

> Note: `express-rate-limit` defaults to in-memory state — state is per-process. Behind multiple Node workers or replicas, use a shared store (Redis / Memcached) so limits are enforced globally.

**Layer 1 — Distributed Rate Limiting with Redis:**

```ts
import express from "express";
import rateLimit from "express-rate-limit";
import RedisStore from "rate-limit-redis";
import { createClient } from "redis";

const redis = createClient({ url: process.env.REDIS_URL });
await redis.connect();

app.use(
  rateLimit({
    windowMs: 60_000,
    max: 100,
    store: new RedisStore({
      // The library's typings call this `sendCommand`.
      sendCommand: (...args: string[]) => redis.sendCommand(args),
    }),
    standardHeaders: "draft-7",
    legacyHeaders: false,
  }),
);
```

**Layer 1 — Edge Rate Limiting with `@upstash/ratelimit`:**

Useful for Next.js / serverless deployments where you can't hold per-process memory across invocations.

```ts
import { Ratelimit } from "@upstash/ratelimit";
import { Redis } from "@upstash/redis";

const ratelimit = new Ratelimit({
  redis: Redis.fromEnv(),
  limiter: Ratelimit.slidingWindow(100, "1 m"),
  analytics: true,
  prefix: "rl:api",
});

export async function POST(req: Request) {
  const ip = req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ?? "unknown";
  // Only honor x-forwarded-for if the request is from a trusted proxy / edge.
  const { success, limit, remaining, reset } = await ratelimit.limit(ip);
  if (!success) {
    return new Response("Too Many Requests", {
      status: 429,
      headers: {
        "RateLimit-Limit": String(limit),
        "RateLimit-Remaining": String(remaining),
        "RateLimit-Reset": String(reset),
      },
    });
  }
  // ... handle request
}
```

**Layer 2 — TLS Configuration:**

```ts
import https from "node:https";
import { readFileSync } from "node:fs";
import app from "./app.js";

https
  .createServer(
    {
      key: readFileSync(process.env.TLS_KEY_PATH!),
      cert: readFileSync(process.env.TLS_CERT_PATH!),
      minVersion: "TLSv1.2",
      // ciphers: ... use Node defaults unless you have a reason; never lower
    },
    app,
  )
  .listen(8443);
```

For client connections (outbound HTTPS), never set `rejectUnauthorized: false` and never set `NODE_TLS_REJECT_UNAUTHORIZED=0` — both disable certificate validation entirely.

**Layer 3 — Request Body Size Limiting:**

```ts
app.use(express.json({ limit: "100kb" }));
app.use(express.urlencoded({ limit: "100kb", extended: false }));
```

For file uploads, configure `multer` with `limits.fileSize` and validate magic bytes — do not trust the `Content-Type` header or the filename.

**Layer 4 — Encryption at Rest (AES-256-GCM):**

Use `node:crypto` `aes-256-gcm` for authenticated encryption. See [Cryptography Security](./cryptography.md) for full `encrypt` / `decrypt` implementations, algorithm selection, and envelope encryption for key rotation.

---

## Zero Trust Principles

| Principle           | Implementation                                                                                  |
| ------------------- | ----------------------------------------------------------------------------------------------- |
| Verify explicitly   | Authenticate and authorize every request — no implicit trust from network location              |
| Least privilege     | Grant minimum permissions; use short-lived tokens (15 min access, 7 d refresh)                  |
| Assume breach       | Segment services, encrypt all communication, log all access for anomaly detection               |

```ts
// Zero Trust middleware: verify identity + permissions on every request
import type { Request, Response, NextFunction } from "express";
import { verifyJwt } from "./auth/jwt.js";
import { hasPermission } from "./auth/rbac.js";
import { logger } from "./logger.js";

export async function zeroTrust(req: Request, res: Response, next: NextFunction) {
  try {
    // 1. Verify token (algorithm pinned, issuer + audience + exp checked)
    const claims = await verifyJwt(req.headers.authorization);

    // 2. Verify permissions for this specific resource
    const allowed = await hasPermission(claims.sub, req.method, req.path);
    if (!allowed) {
      return res.status(403).json({ error: "forbidden" });
    }

    // 3. Audit log
    logger.info({
      event: "access_granted",
      user: claims.sub,
      method: req.method,
      path: req.path,
      ip: req.ip,        // depends on app.set('trust proxy', ...)
    });

    (req as Request & { user: typeof claims }).user = claims;
    next();
  } catch (err) {
    logger.warn({ err: (err as Error).message }, "auth_failed");
    res.status(401).json({ error: "unauthorized" });
  }
}
```

---

## Authentication Patterns

Three common patterns. Pick based on the client and the threat model.

### Session Cookies (Server-side sessions)

Best for: classic server-rendered apps, dashboards, anything where the browser is the only client and CSRF is a manageable problem.

**With `connect-pg-simple` (Postgres-backed):**

```ts
import express from "express";
import session from "express-session";
import connectPgSimple from "connect-pg-simple";
import { pool } from "./db.js";

const PgStore = connectPgSimple(session);
const app = express();
app.set("trust proxy", 1); // trust the first proxy hop (your LB)

app.use(
  session({
    store: new PgStore({ pool, tableName: "user_sessions" }),
    secret: process.env.SESSION_SECRET!,    // long random string, per-env
    name: "__Host-sid",                     // __Host- prefix locks domain + path + Secure
    resave: false,
    saveUninitialized: false,
    rolling: true,
    cookie: {
      httpOnly: true,
      secure: true,                         // required by __Host- prefix
      sameSite: "lax",                      // 'strict' if you have no cross-site nav
      maxAge: 1000 * 60 * 60 * 8,           // 8 h idle
      path: "/",
    },
  }),
);
```

**With Redis (`connect-redis`):**

```ts
import session from "express-session";
import RedisStore from "connect-redis";
import { createClient } from "redis";

const redis = createClient({ url: process.env.REDIS_URL });
await redis.connect();

app.use(
  session({
    store: new RedisStore({ client: redis, prefix: "sess:" }),
    secret: process.env.SESSION_SECRET!,
    name: "__Host-sid",
    resave: false,
    saveUninitialized: false,
    cookie: { httpOnly: true, secure: true, sameSite: "lax", path: "/", maxAge: 28_800_000 },
  }),
);
```

**Pros:** Server controls the session lifecycle — revoking a session is just deleting a row. Easy to add MFA, step-up auth, device tracking. No token-in-JS pitfalls.

**Cons:** Requires a session store. CSRF protection is mandatory (use double-submit cookie or `sameSite: 'strict'`). Less suited to mobile / native clients.

### JWT (Stateless tokens)

Best for: APIs consumed by mobile apps, SPAs that can't rely on cookies, machine-to-machine calls inside a trusted network.

```ts
import { jwtVerify, SignJWT } from "jose";

const issuer = "https://auth.example.com";
const audience = "https://api.example.com";

// On login: issue a short-lived access token + a longer refresh token
async function issueAccessToken(userId: string, secret: Uint8Array) {
  return new SignJWT({ scope: "user" })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(userId)
    .setIssuer(issuer)
    .setAudience(audience)
    .setIssuedAt()
    .setExpirationTime("15m")
    .sign(secret);
}

// On request: verify — algorithm is pinned via the verify options
export async function verifyJwt(authHeader: string | undefined) {
  if (!authHeader?.startsWith("Bearer ")) throw new Error("missing bearer token");
  const token = authHeader.slice("Bearer ".length);
  const { payload } = await jwtVerify(token, JWT_SECRET, {
    issuer,
    audience,
    algorithms: ["HS256"],  // pin — prevents alg confusion / 'none' attacks
  });
  return payload;
}
```

If using asymmetric keys (RS256 / ES256), pin to the asymmetric algorithm and load the public key from a JWKS endpoint — never accept a key embedded in the token (`jku`, `jwk`).

**Pros:** Stateless — no DB lookup per request. Works across origins and platforms. Easy horizontal scaling.

**Cons:** Revocation is hard — a stolen token is valid until it expires. Keep access tokens short-lived (5 – 15 min) and pair with rotating refresh tokens stored server-side. JWTs in `localStorage` are XSS-readable — prefer `HttpOnly` cookies or in-memory storage with refresh-on-load.

### OAuth 2.1 / OpenID Connect

Best for: "Sign in with Google / Microsoft / Okta", delegated access to third-party APIs, multi-tenant SaaS.

Use a vetted library — `openid-client` (the maintained OIDC client) handles PKCE, state, nonce, and discovery for you. Do not hand-roll the flow.

```ts
import { Issuer, generators } from "openid-client";

const issuer = await Issuer.discover("https://accounts.google.com");
const client = new issuer.Client({
  client_id: process.env.OIDC_CLIENT_ID!,
  client_secret: process.env.OIDC_CLIENT_SECRET!,
  redirect_uris: ["https://app.example.com/auth/callback"],
  response_types: ["code"],
});

// Start flow (PKCE — required for public clients, recommended everywhere)
const code_verifier = generators.codeVerifier();
const code_challenge = generators.codeChallenge(code_verifier);
const state = generators.state();
const nonce = generators.nonce();
// Store code_verifier + state + nonce in the user's session
const authUrl = client.authorizationUrl({
  scope: "openid profile email",
  code_challenge,
  code_challenge_method: "S256",
  state,
  nonce,
});

// Callback handler
const params = client.callbackParams(req);
const tokenSet = await client.callback(
  "https://app.example.com/auth/callback",
  params,
  { code_verifier, state, nonce },         // library validates these
);
const userInfo = await client.userinfo(tokenSet.access_token!);
```

**Pros:** No password storage. MFA / account recovery handled by the identity provider. Industry standard.

**Cons:** External dependency on the IdP's availability. More moving parts (discovery, JWKS rotation, ID token validation). Easy to misuse if hand-rolled — always pick a maintained library.

### Pattern selection summary

| Use Case                                     | Recommended Pattern                          | Notes                                                                       |
| -------------------------------------------- | -------------------------------------------- | --------------------------------------------------------------------------- |
| Server-rendered web app, single domain       | Session cookies (`__Host-` prefix, SameSite) | Add CSRF tokens for state-changing routes unless SameSite=Strict            |
| SPA + API, mixed clients                     | Short-lived JWT access + rotating refresh    | Refresh stored `HttpOnly Secure`; access in memory                          |
| Mobile or native client                      | OAuth 2.1 + PKCE                             | Refresh stored in OS keychain; rotate on use                                |
| Federated identity (SSO, "Sign in with …")   | OIDC via `openid-client`                     | Always validate `iss`, `aud`, `exp`, `nonce`; verify ID token signature     |
| Service-to-service inside a private network  | mTLS                                         | Rotate certificates; short validity                                         |
| CLI / automation                             | API keys + IP allowlists                     | Treat keys as passwords — hash before storing                               |

### Password Hashing — Argon2id

Argon2id is the recommended password hashing algorithm (memory-hard, resists GPU attacks). See [Cryptography Security](./cryptography.md) for the full snippet, algorithm comparison (bcrypt, scrypt), and OWASP parameter recommendations.

```ts
import argon2 from "argon2";

export async function hashPassword(pw: string) {
  return argon2.hash(pw, {
    type: argon2.argon2id,
    memoryCost: 64 * 1024,   // 64 MB
    timeCost: 3,
    parallelism: 4,
  });
}

export async function verifyPassword(stored: string, supplied: string) {
  return argon2.verify(stored, supplied); // constant-time comparison inside
}
```

---

## HTTP Security Headers

Set on every response. Use `helmet`, which applies sensible defaults and lets you override per-policy.

```ts
import helmet from "helmet";

app.use(
  helmet({
    contentSecurityPolicy: {
      useDefaults: true,
      directives: {
        "default-src": ["'self'"],
        "script-src": ["'self'"],            // no 'unsafe-inline', no 'unsafe-eval'
        "object-src": ["'none'"],
        "base-uri": ["'self'"],
        "frame-ancestors": ["'none'"],
      },
    },
    crossOriginEmbedderPolicy: false,         // enable if you control all subresources
    referrerPolicy: { policy: "strict-origin-when-cross-origin" },
    strictTransportSecurity: { maxAge: 31_536_000, includeSubDomains: true, preload: true },
  }),
);
```

Manual equivalent (if you can't use helmet):

```ts
app.use((_req, res, next) => {
  res.setHeader("Content-Security-Policy", "default-src 'self'; script-src 'self'; object-src 'none'");
  res.setHeader("X-Frame-Options", "DENY");
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("Strict-Transport-Security", "max-age=31536000; includeSubDomains");
  res.setHeader("Referrer-Policy", "strict-origin-when-cross-origin");
  res.setHeader("Permissions-Policy", "geolocation=(), microphone=(), camera=()");
  next();
});
```

| Header                    | Purpose                                          | Recommended Value                                       |
| ------------------------- | ------------------------------------------------ | ------------------------------------------------------- |
| Content-Security-Policy   | Prevents XSS by restricting resource sources     | `default-src 'self'; script-src 'self'; object-src 'none'` |
| X-Frame-Options           | Prevents clickjacking via framing                | `DENY`                                                  |
| X-Content-Type-Options    | Prevents MIME-type sniffing                      | `nosniff`                                               |
| Strict-Transport-Security | Forces HTTPS, prevents protocol downgrade        | `max-age=31536000; includeSubDomains`                   |
| Referrer-Policy           | Controls referrer header leakage                 | `strict-origin-when-cross-origin`                       |
| Permissions-Policy        | Restricts browser features (camera, mic, geo)    | `geolocation=(), microphone=(), camera=()`              |

---

## Security Anti-Patterns

| Anti-Pattern                              | Why It Fails                                                                          | TypeScript / Node Fix                                                                       |
| ----------------------------------------- | ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| Security through obscurity                | Hidden admin URLs are discoverable via fuzzing, source maps in prod, or commit history | Authentication + authorization on all endpoints; no security relies on URL secrecy          |
| Trusting client headers                   | `X-Forwarded-For`, `X-Is-Admin`, `X-Real-IP` — clients forge any header                | Server-side identity verification; configure `app.set('trust proxy', …)` with explicit hop count or known proxy IPs |
| Client-side authorization                 | JS checks (hiding a button, route guards in a SPA) are bypassed by any HTTP client     | Server-side `if (!user.permissions.includes('admin'))` on every protected handler           |
| Shared secrets across environments        | Staging breach → production compromise                                                | Per-environment secrets via secret manager (Vault, AWS Secrets Manager, Doppler, 1Password) |
| Catching and ignoring crypto / I/O errors | `try { await encrypt(…) } catch { /* nothing */ }` proceeds with unencrypted data      | Always handle errors — fail closed, never open. Re-throw or return an explicit failure      |
| Rolling your own crypto                   | Custom encryption hasn't been analyzed by cryptographers                              | Use `node:crypto` AES-256-GCM, `argon2`, `jose`, vetted libraries                           |
| Verbose error responses                   | Stack traces and DB errors reveal internals to attackers                              | Generic errors to clients (`res.status(500).json({error: 'internal'})`), detailed logs server-side |

### Code Examples

**Anti-pattern: trusting client-provided identity headers**

```ts
// BAD — attacker simply sends X-Is-Admin: true
app.get("/admin", (req, res) => {
  if (req.headers["x-is-admin"] === "true") {
    return adminPanel(req, res);
  }
  res.status(403).end();
});

// GOOD — server-side check against the authenticated user
app.get("/admin", requireAuth, (req, res) => {
  if (!req.user.permissions.includes("admin:read")) {
    return res.status(403).end();
  }
  adminPanel(req, res);
});
```

**Anti-pattern: trusting `X-Forwarded-For` blindly**

```ts
// BAD — anyone can claim any IP
const ip = req.headers["x-forwarded-for"];
await rateLimitByIp(ip as string);

// GOOD — let Express resolve req.ip via configured 'trust proxy'
// In app bootstrap, AFTER deciding how many proxies you have:
app.set("trust proxy", 1);            // trust exactly one hop (your LB)
// or: app.set('trust proxy', ['10.0.0.0/8']);    // trust known proxy CIDRs
// then:
await rateLimitByIp(req.ip!);
```

**Anti-pattern: client-side authorization**

```ts
// BAD — React route guard is the only check
function AdminRoute({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  if (!user?.isAdmin) return <Navigate to="/" />;
  return <>{children}</>;
}
// API has no check → curl -H 'Authorization: Bearer …' /api/admin/users works for any user
```

```ts
// GOOD — UI guard is for UX only; the server enforces.
app.get("/api/admin/users", requireAuth, requirePermission("admin:read"), listUsers);
```

**Anti-pattern: ignoring crypto errors**

```ts
// BAD — on error, ciphertext is undefined and the caller may store plaintext
async function encryptField(plaintext: string): Promise<string> {
  try {
    return await encryptAesGcm(plaintext, key);
  } catch {
    return plaintext;             // silently falls back to plaintext
  }
}

// GOOD — fail closed
async function encryptField(plaintext: string): Promise<string> {
  return await encryptAesGcm(plaintext, key); // throw on failure
}
```

**Anti-pattern: shared secrets across environments**

```ts
// BAD — same JWT_SECRET in dev, staging, prod (.env.shared committed to a private repo)
const secret = process.env.JWT_SECRET; // same value everywhere

// GOOD — per-environment secret material, loaded from a secret manager at boot
const secret = await secrets.get("prod/auth/jwt_signing_key");
```

See [Secrets Management](./secrets.md) for secret-manager integration patterns.

---

See also:

- [SKILL.md](../SKILL.md) — overview, severity levels, common mistakes.
- [Threat Modeling Guide](./threat-modeling.md) — STRIDE, DREAD, trust boundaries, OWASP Top 10.
