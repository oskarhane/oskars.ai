# Security reference

## Contents
- Server/client boundary
- Environment variables
- `$lib/server` enforcement
- XSS vectors specific to Svelte/SvelteKit
- CSP configuration
- Security headers in hooks
- Known CVE history
- Audit grep patterns

## Server/client boundary

SvelteKit splits code into server-only and client-reachable at the module level. The boundary is enforced at build time by Vite, but only if you use the framework's mechanisms. Bypasses are easy.

**Server-only contexts** (safe for secrets):
- `hooks.server.ts` / `hooks.server.js`
- `+page.server.ts` / `+page.server.js`
- `+layout.server.ts` / `+layout.server.js`
- `+server.ts` / `+server.js` (API endpoints)
- Any file under `$lib/server/`
- Any file with `.server.ts` / `.server.js` suffix
- `src/params/<matcher>.ts` (param matchers run server-side initially)

**Universal contexts** (reach the client, do not put secrets here):
- `+page.ts` / `+page.js`
- `+layout.ts` / `+layout.js`
- `.svelte` files
- Anything in `$lib/` not under `$lib/server/`

If a universal file imports from a server-only file, Vite throws:
```
Cannot import $lib/server/secrets.ts into code that runs in the browser
```

The check is transitive: A → B → C, where C is server-only, fails even if A only uses an unrelated export from B.

**Bypass trap**: `import type` is allowed across the boundary (types are erased). This is fine for types but flag any non-type import that crosses the line.

## Environment variables

Four modules. Pick correctly:

| Module | When | Use case |
|---|---|---|
| `$env/static/private` | Server-only, build-time | Most secrets. Build-time inlined, enables dead code elimination. Cannot be read at prerender time in SvelteKit 2 (use this if you only build once per env). |
| `$env/dynamic/private` | Server-only, runtime | Secrets that vary between deploys without rebuilding (containers, edge runtimes). |
| `$env/static/public` | Universal, build-time | Public values inlined at build. Names must start with `PUBLIC_` (configurable via `kit.env.publicPrefix`). |
| `$env/dynamic/public` | Universal, runtime | Public values resolved at runtime. Slightly larger client cost. |

**Critical rule**: `PUBLIC_` ships to the browser. Never put a secret behind `PUBLIC_FOO` thinking the name "public" is just convention.

**Vite legacy trap**: `import.meta.env.VITE_*` is the older Vite-native API. Any var prefixed `VITE_` is inlined into the client bundle. Old SvelteKit tutorials reference this — flag it in new code unless explicitly intentional.

**Prerender + dynamic private**: SvelteKit 2 forbids reading `$env/dynamic/private` during prerendering (the values aren't known at build time). If a load function reads a dynamic private var and the route is prerendered, the build crashes. Either switch to `$env/static/private` or disable prerender for that route.

## `$lib/server` enforcement

Two equivalent ways to mark code as server-only:
1. Place file under `$lib/server/` (e.g. `src/lib/server/db.ts`)
2. Use `.server.ts` / `.server.js` suffix (e.g. `src/lib/db.server.ts`)

Both produce the same Vite-level import-restriction. Pick one convention per project. Mixing both is harmless but messy.

**Don't put `$lib/server/` files inside `src/routes/`** — they collide with route handlers. Server-only utilities live in `src/lib/server/`.

**Test environments**: Vitest disables the illegal-import check when `process.env.TEST === 'true'`. This is fine for tests but means you cannot rely on the check to catch issues in test files.

## XSS in Svelte/SvelteKit

Svelte auto-escapes mustache expressions (`{value}` becomes safe text). Three known bypasses:

### 1. `{@html ...}`

Renders raw HTML. The primary XSS vector in any Svelte codebase.

```svelte
<!-- ❌ Dangerous if `userBio` is user-controlled -->
<div>{@html userBio}</div>

<!-- ✅ Sanitize first -->
<script>
  import DOMPurify from 'isomorphic-dompurify';
  let safeBio = $derived(DOMPurify.sanitize(userBio));
</script>
<div>{@html safeBio}</div>
```

In review: `grep -rn "{@html" src/` and verify every hit. Markdown rendered server-side by a trusted lib (`marked` with sanitization on, `markdown-it` with default escapes) is generally OK; anything passing through `{@html}` after coming from the DB needs a clear sanitization step.

### 2. URL attribute injection

```svelte
<!-- ❌ `javascript:alert(1)` works here -->
<a href={userUrl}>Click</a>

<!-- ✅ Validate scheme -->
<script>
  function safeUrl(u) {
    try {
      const url = new URL(u);
      return ['http:', 'https:', 'mailto:'].includes(url.protocol) ? u : '#';
    } catch { return '#'; }
  }
</script>
<a href={safeUrl(userUrl)}>Click</a>
```

Svelte does not strip `javascript:` URLs. Same applies to `src`, `formaction`, `action`, `xlink:href`.

### 3. CSS injection via inline styles

```svelte
<!-- ❌ `style={userStyle}` -->
<div style={userStyle}>...</div>
```

`expression(...)` and other CSS-based vectors are largely closed in modern browsers, but `behavior:`, data-URIs in `background-image`, and CSS exfiltration via `@import` remain. Don't let user input drive inline style strings.

## Content Security Policy

SvelteKit can auto-generate CSP via `svelte.config.js`:

```js
const config = {
  kit: {
    csp: {
      mode: 'auto',                    // 'hash' for prerendered, 'nonce' for SSR
      directives: {
        'script-src': ['self'],
        'style-src': ['self', 'unsafe-inline'],
        'img-src': ['self', 'data:', 'https:'],
        'connect-src': ['self'],
        'frame-ancestors': ['none']
      },
      reportOnly: {                    // tune with reports before enforcing
        'script-src': ['self'],
        'report-uri': ['/api/csp-report']
      }
    }
  }
};
```

`mode: 'auto'` uses hashes for prerendered pages and nonces for SSR. This is what most apps want.

**Manual CSP via headers** is fragile because SvelteKit emits inline hydration scripts. If a project sets CSP manually in `hooks.server.ts`, audit whether `'unsafe-inline'` is in `script-src` (often the only way to make it work, which defeats the purpose) or whether hashes/nonces are computed correctly.

`frame-ancestors 'none'` makes `X-Frame-Options: DENY` redundant but harmless. Use both for older browsers.

## Security headers

Set in `hooks.server.ts` via the `handle` hook:

```ts
import type { Handle } from '@sveltejs/kit';

export const handle: Handle = async ({ event, resolve }) => {
  const response = await resolve(event);
  response.headers.set('X-Content-Type-Options', 'nosniff');
  response.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');
  response.headers.set('Permissions-Policy', 'camera=(), microphone=(), geolocation=()');
  if (process.env.NODE_ENV === 'production') {
    response.headers.set('Strict-Transport-Security', 'max-age=31536000; includeSubDomains');
  }
  return response;
};
```

Note: setting `Content-Security-Policy` manually here will conflict with `kit.csp` config. Pick one mechanism.

**Cookies always**:
```ts
cookies.set('session', token, {
  httpOnly: true,
  secure: true,           // false only in dev over HTTP
  sameSite: 'lax',        // 'strict' breaks OAuth redirects
  path: '/',
  maxAge: 60 * 60 * 24 * 7
});
```

Adapter-level headers (Vercel, Cloudflare, Netlify) can override or duplicate — check `vercel.json`, `_headers`, `wrangler.toml`.

## CSRF

SvelteKit ships with origin-check CSRF protection enabled by default. It blocks cross-origin form submissions with form content types. Configuration:

```js
const config = {
  kit: {
    csrf: {
      checkOrigin: true,                              // default; keep on
      trustedOrigins: ['https://trusted.example.com'] // for cross-origin POST from listed origins
    }
  }
};
```

Findings:

- **`checkOrigin: false`** without an explicit comment explaining why is a red flag. Often added to "fix" CORS issues that should be solved differently.
- **`trustedOrigins` with wildcards or many entries** — each origin is a potential attack vector if compromised.
- **`+server.ts` accepting POST/PUT/PATCH/DELETE from JS clients across origins** needs token-based protection on top of origin check.

### CVE-2023-29003 (SvelteKit < 1.15.1)

CSRF bypass via `Content-Type: text/plain` — the built-in check missed this content type. Also, method-override hacks in `handle` could bypass. Fixed in 1.15.1. Flag any project pinned below this version.

## Other known CVE history (quick reference)

- **CVE-2023-29003** (< 1.15.1): CSRF bypass via Content-Type
- **CVE-2024-23331** (< 2.5.1, 1.30.4): Path traversal in dev server via `vite-plugin-svelte-kit`
- Periodically search GHSA for `@sveltejs/kit` advisories; the framework moves fast.

For any audit, run `npm audit` or `pnpm audit` and inspect output. `@sveltejs/kit` advisories are usually worth treating as critical.

## Quick audit grep patterns

```bash
# Secrets imported into client/universal contexts
grep -rn "from '\$env/static/private'" src --include="*.svelte" --include="+page.ts" --include="+page.js" --include="+layout.ts" --include="+layout.js"
grep -rn "from '\$env/dynamic/private'" src --include="*.svelte" --include="+page.ts" --include="+page.js" --include="+layout.ts" --include="+layout.js"

# Vite-legacy env reads (review case-by-case)
grep -rn "import.meta.env" src

# All @html usage — verify each
grep -rn "{@html" src

# Disabled CSRF
grep -rn "checkOrigin" svelte.config.js svelte.config.ts

# Disabled a11y warnings (often hide real issues)
grep -rn "svelte-ignore" src

# Client-side auth checks pretending to protect data
grep -rn "if (.*user)" src --include="*.svelte"

# `any` types in load functions / locals
grep -rn ": any" src/app.d.ts src/hooks.server.ts
```
