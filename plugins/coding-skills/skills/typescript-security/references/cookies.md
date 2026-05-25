# Cookie Security Rules

Cookie security is critical for preventing session hijacking, CSRF, and XSS exploitation.

**Rules:**

1. Cookies MUST set `httpOnly: true` for session and authentication cookies.
2. Cookies MUST set `secure: true` in production (HTTPS only).
3. `sameSite` SHOULD be `'strict'` or `'lax'` — use `'none'` only when cross-site access is required (and only with `secure: true`).
4. Authentication cookies SHOULD use the `__Host-` prefix when scope allows it.
5. Cookies carrying state MUST be signed (HMAC) or encrypted — never trust raw cookie values.

---

## HttpOnly Flag Missing — Medium

Without `httpOnly`, cookies can be read via `document.cookie` from any JavaScript that runs in the page — turning any XSS into session theft.

**Bad:**

```ts
import express from 'express';
const app = express();

app.post('/login', (req, res) => {
  // DON'T: missing httpOnly, secure, sameSite
  res.cookie('session', sessionId);
  res.sendStatus(204);
});
```

**Good:**

```ts
import express from 'express';
const app = express();

app.post('/login', (req, res) => {
  res.cookie('session', sessionId, {
    httpOnly: true,                                  // no document.cookie access
    secure: true,                                    // HTTPS only
    sameSite: 'strict',                              // CSRF defense
    path: '/',
    maxAge: 60 * 60 * 1000,                          // 1h
  });
  res.sendStatus(204);
});
```

---

## Insecure Cookie (Missing Secure Flag) — Medium

Without `secure`, cookies travel over plain HTTP and can be captured by any network observer.

**Bad:**

```ts
res.cookie('auth_token', token, {
  httpOnly: true,
  // DON'T: missing secure + sameSite
});
```

**Good:**

```ts
res.cookie('auth_token', token, {
  httpOnly: true,
  secure: true,
  sameSite: 'lax',
  path: '/',
  maxAge: 24 * 60 * 60 * 1000,
  // omit `domain` so the cookie is sent only to the exact host
});
```

In development on `http://localhost`, set `secure` from an env flag rather than hardcoding `false`:

```ts
const isProd = process.env.NODE_ENV === 'production';

res.cookie('session', sessionId, {
  httpOnly: true,
  secure: isProd,
  sameSite: 'lax',
});
```

---

## SameSite Cookie Protection — Medium

`sameSite` defends against CSRF by limiting when the browser attaches the cookie to cross-site requests.

| Value | Behavior | When to use |
| --- | --- | --- |
| `'strict'` | Never sent on cross-site requests | Auth, password change, money transfer |
| `'lax'` | Sent on top-level GET navigations only | Default for most session cookies |
| `'none'` | Sent on all cross-site requests | Required for cross-origin embeds / third-party SSO; MUST set `secure: true` |

**Bad:**

```ts
res.cookie('session', token, {
  httpOnly: true,
  secure: true,
  // DON'T: defaults vary by browser; specify explicitly
});
```

**Good:**

```ts
// Strict for high-value cookies (admin, auth)
res.cookie('auth', token, {
  httpOnly: true,
  secure: true,
  sameSite: 'strict',
});

// Lax for general session cookies — survives clicking inbound links
res.cookie('session', token, {
  httpOnly: true,
  secure: true,
  sameSite: 'lax',
});

// None only for cross-site iframes / third-party SSO callbacks
res.cookie('embed', token, {
  httpOnly: true,
  secure: true,           // required when sameSite is 'none'
  sameSite: 'none',
});
```

---

## `__Host-` Prefix — Low (High when omitted on auth cookies)

The `__Host-` prefix tells the browser to enforce strong scoping rules. A cookie named `__Host-...` is rejected by the browser unless it satisfies all of these:

- `secure: true`
- `path: '/'`
- No `domain` attribute set (so it is bound to the exact host that set it)

That prevents a subdomain from overriding the cookie and prevents cookie fixation across hosts.

`__Secure-` is a weaker variant — it only requires `secure: true`.

**Example (Express):**

```ts
res.cookie('__Host-session', sessionId, {
  httpOnly: true,
  secure: true,                 // required
  sameSite: 'strict',
  path: '/',                    // required
  // domain: undefined          // MUST be omitted
  maxAge: 60 * 60 * 1000,
});
```

**Example (via the `cookie` library on a raw Node response):**

```ts
import { serialize } from 'cookie';
import type { ServerResponse } from 'node:http';

function setSessionCookie(res: ServerResponse, sessionId: string): void {
  const value = serialize('__Host-session', sessionId, {
    httpOnly: true,
    secure: true,
    sameSite: 'strict',
    path: '/',
    maxAge: 60 * 60,            // seconds in the cookie lib
  });
  res.setHeader('Set-Cookie', value);
}
```

---

## Signed Cookies — High

Never trust raw cookie values from the browser. Sign or encrypt anything used for identity, authorization, or state.

### Option 1: Express `cookie-parser` signed cookies

`cookie-parser` HMAC-signs the value and verifies it on read.

**Bad:**

```ts
import cookieParser from 'cookie-parser';
app.use(cookieParser('hardcoded-secret-key'));  // DON'T: hardcoded
```

**Good:**

```ts
import cookieParser from 'cookie-parser';

const cookieSecret = process.env.COOKIE_SECRET;
if (!cookieSecret) throw new Error('COOKIE_SECRET required');

app.use(cookieParser(cookieSecret));

app.post('/login', (req, res) => {
  res.cookie('uid', String(userId), {
    httpOnly: true,
    secure: true,
    sameSite: 'strict',
    signed: true,                    // value gets HMAC-signed
  });
  res.sendStatus(204);
});

app.get('/me', (req, res) => {
  const uid = req.signedCookies.uid; // `false` if signature invalid
  if (!uid) return res.sendStatus(401);
  res.json({ uid });
});
```

### Option 2: HMAC by hand

When you need a cookie outside Express, sign with `node:crypto` and compare in constant time.

```ts
import { createHmac, timingSafeEqual } from 'node:crypto';

const secret = process.env.COOKIE_SECRET;
if (!secret) throw new Error('COOKIE_SECRET required');

function sign(value: string): string {
  const mac = createHmac('sha256', secret).update(value).digest('base64url');
  return `${value}.${mac}`;
}

function verify(signed: string): string | null {
  const dot = signed.lastIndexOf('.');
  if (dot < 0) return null;
  const value = signed.slice(0, dot);
  const mac = signed.slice(dot + 1);
  const expected = createHmac('sha256', secret).update(value).digest('base64url');
  const a = Buffer.from(mac);
  const b = Buffer.from(expected);
  if (a.length !== b.length) return null;
  return timingSafeEqual(a, b) ? value : null;
}
```

For values that must remain confidential (not just integrity-checked), encrypt with AES-256-GCM instead — see [cryptography.md](./cryptography.md).

---

## Session Cookie vs Persistent Cookie

A **session cookie** has no `maxAge` / `expires` — the browser drops it when the user closes the browser. A **persistent cookie** has an explicit lifetime and survives restarts.

| Cookie purpose | Type | Rationale |
| --- | --- | --- |
| Logged-in session for a sensitive app (banking, admin) | Session | Forces re-auth on browser close; smaller window of theft |
| "Remember me" for a consumer app | Persistent (`maxAge` 7–30 days) | UX benefit outweighs marginal risk when paired with rotation |
| CSRF token | Session | Lives only as long as the user is interacting |
| Locale / theme preference | Persistent (long `maxAge`) | Not sensitive; UX wins |
| Analytics / consent | Persistent (consent-gated) | Survives sessions by design |

**Session cookie:**

```ts
res.cookie('session', sessionId, {
  httpOnly: true,
  secure: true,
  sameSite: 'strict',
  // no maxAge / expires => session cookie
});
```

**Persistent "remember me":**

```ts
res.cookie('remember', rememberToken, {
  httpOnly: true,
  secure: true,
  sameSite: 'lax',
  maxAge: 30 * 24 * 60 * 60 * 1000,      // 30d
});
```

Always pair persistent auth cookies with server-side rotation: on use, issue a new token, invalidate the old one, and bind to a device/IP fingerprint where appropriate.

---

## Cookie Best Practices Checklist

- [ ] `httpOnly: true` on all authentication and session cookies
- [ ] `secure: true` in production (drive via `NODE_ENV` for local dev)
- [ ] `sameSite` set explicitly (`'strict'` for auth, `'lax'` for general sessions, `'none'` only with `secure`)
- [ ] `__Host-` prefix on auth cookies when path `/` and no subdomain sharing
- [ ] Cookies signed (HMAC) or encrypted — never trust raw values
- [ ] `maxAge` set to the minimum lifetime the use case requires
- [ ] `domain` omitted unless cross-subdomain access is required
- [ ] Cookies cleared on logout (`res.clearCookie(name, { path: '/' })`)
- [ ] Rotate cookie secrets on schedule and on suspected leak
- [ ] Validate signed cookie values with `crypto.timingSafeEqual`, never `===`

---

## CWE References

- **CWE-1004**: Sensitive Cookie Without 'HttpOnly' Flag
- **CWE-614**: Sensitive Cookie in HTTPS Session Without 'Secure' Attribute
- **CWE-352**: Cross-Site Request Forgery (CSRF)
- **CWE-285**: Improper Authorization
- **CWE-565**: Reliance on Cookies without Validation
