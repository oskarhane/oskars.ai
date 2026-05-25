# Fast-scan checklist

Dense, copy-pasteable. Walk top to bottom on any SvelteKit codebase. Each line is one check; if it fails, it's a finding. Severity in brackets.

## Versions & setup
- [ ] `@sveltejs/kit` ≥ 2.0 — older is legacy [HIGH if < 1.15.1, security]
- [ ] `svelte` ≥ 5 for new projects; consistent paradigm if 4
- [ ] `node` engine pinned in `package.json` [LOW]
- [ ] `tsconfig.json` extends `./.svelte-kit/tsconfig.json` with `strict: true` [MEDIUM]
- [ ] `app.d.ts` has `App.Locals` and `App.Error` typed (not `any`) [MEDIUM]
- [ ] `svelte-check` script present and clean [MEDIUM]
- [ ] `npm audit` / `pnpm audit` shows no high/critical advisories [CRITICAL]

## Server/client boundary
- [ ] No `$env/static/private` import in `.svelte`, `+page.ts`, `+layout.ts` [CRITICAL]
- [ ] No `$env/dynamic/private` import in `.svelte`, `+page.ts`, `+layout.ts` [CRITICAL]
- [ ] No `import.meta.env.VITE_SECRET*` or similar [CRITICAL]
- [ ] All secrets in `$lib/server/` or `*.server.ts` [CRITICAL]
- [ ] DB clients in `$lib/server/` only [CRITICAL]
- [ ] No `PUBLIC_` prefix on actual secrets [CRITICAL]
- [ ] `event.locals.user` populated in hook, only minimal claims forwarded to client [MEDIUM]

## Auth & sessions
- [ ] Session cookie `httpOnly: true` [CRITICAL]
- [ ] Session cookie `secure: true` in production [CRITICAL]
- [ ] Session cookie `sameSite: 'lax'` (or `'strict'` if appropriate) [HIGH]
- [ ] Logout deletes cookie with matching `path` [HIGH]
- [ ] Auth resolved in `hooks.server.ts`, not per-page [HIGH]
- [ ] Protected route groups have `+layout.server.ts` (not just `+layout.svelte`) [HIGH]
- [ ] Every form action re-checks `locals.user` [HIGH]
- [ ] Authorization checks ownership/role, not just auth presence [CRITICAL]
- [ ] Returned user object strips sensitive fields (no password hash, no internal tokens) [HIGH]
- [ ] Sessions checked for expiry, not just existence [HIGH]
- [ ] Rate limiting on login / signup / password reset [HIGH]

## CSRF & input validation
- [ ] `kit.csrf.checkOrigin` is true (default) [CRITICAL]
- [ ] `trustedOrigins` short and justified [MEDIUM]
- [ ] Every form action validates input server-side [CRITICAL]
- [ ] String inputs capped with `.max()` [MEDIUM]
- [ ] `formData.get(...)` results checked for type before use [MEDIUM]
- [ ] File uploads check size, MIME, and use sanitized filenames [HIGH]
- [ ] File destination paths don't include user-controlled segments [CRITICAL]
- [ ] `+server.ts` state-changing methods auth-checked [HIGH]
- [ ] No mutations in load functions [HIGH]

## XSS, headers, CSP
- [ ] Every `{@html}` is sanitized or from a trusted source [CRITICAL]
- [ ] User-controlled URLs in `href`/`src` validated for scheme [HIGH]
- [ ] `Content-Security-Policy` configured (via `kit.csp` or hook) [HIGH]
- [ ] `X-Content-Type-Options: nosniff` set [MEDIUM]
- [ ] `Referrer-Policy` set [MEDIUM]
- [ ] `Strict-Transport-Security` in production [MEDIUM]
- [ ] `frame-ancestors` set (CSP) or `X-Frame-Options` [MEDIUM]
- [ ] No `unsafe-inline` in `script-src` without nonces/hashes [HIGH]

## Load functions
- [ ] Server load for anything sensitive [HIGH]
- [ ] No module-level mutable state acting as cache [CRITICAL — data leak between users]
- [ ] `await parent()` only when parent data is used [LOW]
- [ ] Independent fetches in `Promise.all` [LOW perf]
- [ ] Streamed promises have `{:catch}` blocks [HIGH]
- [ ] `invalidate()` targeted; `invalidateAll()` justified [LOW]
- [ ] Provided `fetch` used, not global [LOW]
- [ ] `setHeaders` not used for cookies [MEDIUM]
- [ ] `cache-control` on per-user routes is `private` or absent [HIGH — CDN leak]
- [ ] Load functions typed via `./$types` [MEDIUM]

## Svelte 5 runes
- [ ] No `$effect` computing values that should be `$derived` [HIGH]
- [ ] No destructured `$state` (loses reactivity) [HIGH]
- [ ] `$effect` cleanup for timers/subscriptions/listeners [HIGH — leak]
- [ ] `$state.raw` for replace-only data [LOW perf]
- [ ] No legacy `export let`, `$:`, `on:click`, `<slot>`, `createEventDispatcher` in new code [MEDIUM]
- [ ] Runes only in `.svelte` and `.svelte.ts`/`.svelte.js` files [HIGH — won't work otherwise]
- [ ] `$props()` typed [MEDIUM]
- [ ] `$page` from `$app/stores` migrated to `page` from `$app/state` [LOW]
- [ ] `{#each items as item (item.id)}` keyed by stable id [HIGH]
- [ ] No `$inspect` in committed code [LOW]

## Conventions & structure
- [ ] All route files prefixed with `+` (no typos like `page.svelte`) [HIGH]
- [ ] No `.tsx` files [HIGH — not supported]
- [ ] Server-only logic under `$lib/server/` or `*.server.ts` [HIGH]
- [ ] `+page.svelte` under ~150 lines [MEDIUM]
- [ ] Business logic out of `+page.svelte` (in load / actions / `$lib`) [HIGH]
- [ ] Layouts thin; per-page logic not in layouts [MEDIUM]
- [ ] Param matchers used for typed params (`[id=integer]`) [LOW]
- [ ] Route groups used to organize protection / sections [LOW]
- [ ] `$lib/components/` not a 60-file dumping ground [LOW — for large apps]
- [ ] Imports use `$lib/...` aliases, not `../../../` [LOW]

## Performance
- [ ] Bundle analyzed at least once (visualizer) [MEDIUM]
- [ ] No `moment`; no full `lodash` [MEDIUM]
- [ ] Heavy below-the-fold components dynamically imported [LOW]
- [ ] Fonts preloaded if custom; `font-display: swap` set [MEDIUM]
- [ ] `@sveltejs/enhanced-img` or equivalent for images [LOW]
- [ ] `prerender = true` on static marketing pages [LOW perf]
- [ ] `prerender = true` NOT on user-specific pages [CRITICAL — would crash build or leak]
- [ ] `ssr = false` not used as a band-aid [HIGH]
- [ ] Streaming used where one fetch is slow [LOW perf]
- [ ] `data-sveltekit-preload-data` strategy intentional [LOW]
- [ ] `cache-control` headers on cacheable routes [LOW]

## Accessibility
- [ ] Svelte a11y warnings not broadly suppressed [HIGH]
- [ ] Every `<input>` has a label [HIGH]
- [ ] Interactive components have keyboard support [HIGH]
- [ ] Modals/dropdowns have focus management [MEDIUM]
- [ ] `alt` on all images (empty `alt=""` for decorative is correct) [MEDIUM]
- [ ] `lang` attribute on `<html>` [MEDIUM]
- [ ] Color-only signals have non-color alternatives [MEDIUM]

## Error handling & observability
- [ ] `handleError` hook in `hooks.server.ts` [HIGH]
- [ ] Root `+error.svelte` present [MEDIUM]
- [ ] Errors thrown via `error(...)` helper, not raw `throw` [MEDIUM]
- [ ] No stack traces returned to client [CRITICAL — info leak]
- [ ] Structured logging in server code, not `console.log` [LOW]
- [ ] Errors reported to a monitoring service (Sentry, etc.) in production [MEDIUM]

## Testing
- [ ] At least one test runner configured (Vitest, Playwright) [MEDIUM]
- [ ] Critical paths (auth, payment, mutation) covered [HIGH]
- [ ] Tests don't share state across runs [MEDIUM]
- [ ] CI runs `svelte-check` + tests [MEDIUM]

## TypeScript
- [ ] `strict: true` [MEDIUM]
- [ ] No `any` in `App.Locals` [HIGH]
- [ ] Load functions return types inferred (via `./$types` annotations) [MEDIUM]
- [ ] Actions typed as `Actions` [MEDIUM]
- [ ] Server endpoints typed as `RequestHandler` [MEDIUM]
- [ ] Component props typed via `interface` or inline [MEDIUM]
