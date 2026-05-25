---
name: sveltekit-code-review
description: Reviews SvelteKit codebases for security vulnerabilities, framework misuse, Svelte 5 rune anti-patterns, file/route convention violations, performance issues, and accessibility gaps. Use when the user asks to review, audit, lint, critique, or check a SvelteKit project, a +page/+layout/+server file, a route, a Svelte component, hooks.server.ts, or asks about SvelteKit best practices, security, or production-readiness.
---

# SvelteKit code review

A structured, opinionated review of a SvelteKit codebase. Targets SvelteKit 2 + Svelte 5 (runes). Surfaces issues, not preferences — every finding maps to a real bug class, security risk, or framework convention.

## How to run a review

1. **Decide scope.** Ask the user once if unclear: whole project, a specific route, a single file, or a focused concern (e.g. "just security"). Don't ask multiple questions — pick the most likely scope and state your assumption.

2. **Map the project first.** Before reviewing any file, get a layout of the codebase. Run:
   ```bash
   ls -la                              # root: package.json, svelte.config, vite.config, .env*
   find src -type f \( -name "+*.svelte" -o -name "+*.ts" -o -name "+*.js" -o -name "hooks.*" \) | head -50
   cat package.json                    # versions, scripts, deps
   cat svelte.config.js 2>/dev/null || cat svelte.config.ts 2>/dev/null
   ```
   This tells you: Svelte version (4 vs 5), adapter, route structure, whether `$lib/server` is used, whether TS is on.

3. **Walk the checklists below in order.** Each section corresponds to a real failure mode. Read the linked reference file when you hit something you need to inspect carefully — don't load references preemptively.

4. **Write the report.** Use the report template at the bottom. Findings are concrete (file:line, what's wrong, why, how to fix). No vague "consider improving readability" filler.

## Review workflow

Copy this checklist into the response and tick items as you complete them:

```
Review progress:
- [ ] 1. Map project structure & versions
- [ ] 2. Server/client boundary (SECURITY-CRITICAL)
- [ ] 3. Authentication, sessions, route protection
- [ ] 4. Form actions, CSRF, input validation
- [ ] 5. Load functions & data flow
- [ ] 6. Svelte 5 runes correctness
- [ ] 7. File/route conventions
- [ ] 8. XSS, headers, CSP
- [ ] 9. Performance (bundle, waterfalls, SSR)
- [ ] 10. Accessibility (compiler warnings, custom widgets)
- [ ] 11. Error handling & observability
- [ ] 12. Testing & type safety
- [ ] 13. Write report
```

Sections 2, 3, 4, 8 are security-critical. If time is constrained, finish those first.

## 1. Project structure & versions

Pin what you're reviewing against. Open `package.json` and check:

- `@sveltejs/kit` version. Anything `< 2.0` is legacy.
- `svelte` version. `5.x` = runes era. `4.x` = legacy `$:` and stores.
- `@sveltejs/adapter-*` — adapter dictates deployment constraints (Cloudflare has no Node APIs; static can't have server endpoints).
- `node` engine pin in `package.json`.

Known-vulnerable SvelteKit versions to flag: anything `< 1.15.1` (CVE-2023-29003, CSRF bypass via Content-Type). Recommend upgrading to the latest 2.x.

Expected top-level layout:

```
src/
  routes/             # file-based routing
  lib/
    server/           # server-only modules (enforced by Vite)
    components/       # shared UI
  hooks.server.ts     # server middleware
  hooks.client.ts     # client error handling (optional)
  app.html            # HTML shell
  app.d.ts            # App.Locals, App.PageData, App.Error types
static/               # served as-is
svelte.config.js
vite.config.ts
```

For domain-organized larger apps, also expect `src/lib/domains/<domain>/` containing colocated state, types, and components for a feature. Flag flat dumping grounds (`src/lib/utils.ts` with 800 lines, `src/lib/components/` with 60 unrelated components) in apps over ~50 routes.

## 2. Server/client boundary — SECURITY-CRITICAL

This is where most real SvelteKit security incidents originate. Read [references/security.md](references/security.md) for the full checklist. Quick scan:

- **`$lib/server/` for all secrets and DB clients.** Files under `$lib/server/` (and any file ending in `.server.ts`/`.server.js`) cannot be imported by client code — Vite throws a build-time error. If secrets live anywhere else, that's a finding.
- **`$env/static/private` and `$env/dynamic/private` only imported in server-only files** (`+page.server.ts`, `+layout.server.ts`, `+server.ts`, `hooks.server.ts`, `$lib/server/*`, `*.server.ts`). Importing in `+page.ts` or `.svelte` is a leak.
- **`import.meta.env.VITE_*`** is a footgun — anything with the `VITE_` prefix ends up in the client bundle. Treat as public regardless of name. Flag any `VITE_SECRET_*`, `VITE_API_KEY`, `VITE_DB_*` as leaks.
- **Universal load functions (`+page.ts`, `+page.js`)** run on both server and client. Anything returned is serialized and sent to the browser. If a server load and a universal load both exist, the server load's return value is passed to the universal load as `data` — never put secrets in the universal layer.
- **`event.locals` never reaches the client** automatically. It's only available in hooks, server load, and `+server.ts`. Returning `locals.user` from a server load is the correct way to expose user info.

```bash
# Quick grep audit
grep -rn "from '\$env/static/private'" src --include="*.svelte" --include="+page.ts" --include="+page.js" --include="+layout.ts"
grep -rn "from '\$env/dynamic/private'" src --include="*.svelte" --include="+page.ts" --include="+page.js" --include="+layout.ts"
grep -rn "import.meta.env.VITE_" src
```

Any hit on the first two is a critical leak. The third needs case-by-case judgment — `VITE_*` is public by Vite design.

## 3. Authentication, sessions, route protection

Read [references/auth.md](references/auth.md) for full patterns.

- **Session token in HttpOnly, Secure, SameSite cookie.** Check `cookies.set(..., { httpOnly: true, secure: true, sameSite: 'lax', path: '/' })`. `sameSite: 'none'` requires `secure: true` and a real reason.
- **Auth resolved in `hooks.server.ts`**, populating `event.locals.user`. Route protection happens there or in `+layout.server.ts`. Doing it only in `+page.svelte` is broken — client-only guards don't protect data.
- **Route guards must check on every request, not just SSR.** Empty `+page.server.ts` / `+layout.server.ts` files exist for a reason: they force the server hook to run on client-side navigations to that route. Missing those for protected route groups = silent auth bypass on SPA navigation.
- **No password/secret in `event.locals`.** Only the user identity and the minimum derived claims.
- **JWT verification in hooks**, not in load functions. Don't decode a token in multiple places.
- **Logout actually clears the cookie**: `cookies.delete('session', { path: '/' })` — `path` must match `set`.
- **Don't trust `data.user` from `+layout.server.ts` for authorization decisions in actions**. Re-check `locals.user` inside the action.

## 4. Form actions, CSRF, input validation

Read [references/forms-and-actions.md](references/forms-and-actions.md).

- **SvelteKit's built-in CSRF check stays on.** `kit.csrf.checkOrigin` defaults to `true`. Flag any `checkOrigin: false` without a documented reason. `trustedOrigins` should be a short, explicit list.
- **Form actions live in `+page.server.ts`**, never `+page.ts`. Mutations on the universal load layer are wrong.
- **Every action validates input server-side**, regardless of any client-side validation. Use Zod, Valibot, or sveltekit-superforms. Returning `fail(400, { ... })` on invalid input is the SvelteKit pattern.
- **Don't pass raw `formData` into DB queries.** Coerce types explicitly; SvelteKit doesn't coerce for you (superforms does).
- **`use:enhance` is opt-in.** Forms still work without JS — flag forms that depend on client JS (custom `onsubmit` with `preventDefault` and no action fallback).
- **File uploads have size limits enforced server-side.** Check `kit.csrf` plus adapter-specific body limits.
- **`+server.ts` endpoints with state-changing methods (POST/PUT/PATCH/DELETE) need CSRF protection.** SvelteKit's built-in origin check covers same-origin form posts; cross-origin API consumers need a token or a documented public API contract.

## 5. Load functions & data flow

Read [references/load-functions.md](references/load-functions.md).

- **Server load (`+page.server.ts`) is the default for anything touching a DB, secret, or auth.** Universal load (`+page.ts`) only when fetching from a public API without credentials, or returning non-serializable values.
- **Use the `fetch` provided to load**, not the global. It forwards cookies for same-origin internal API calls during SSR and avoids HTTP round-trips.
- **Never store fetched data in module-level variables in load functions.** Each request gets its own load call — caching across requests leaks data between users. State belongs in a real store (Redis, DB) or in `cookies` / `locals`.
- **Streaming with promises**: a top-level returned promise blocks; promises nested in the returned object stream. Top-level errors in nested promises crash SSR if unhandled — attach `.catch()` or use Kit's `fetch` which handles it.
- **Waterfalls**: parallel `await Promise.all([...])` instead of sequential `await`s when the queries are independent. `await parent()` only when you actually need parent data — it's a serialization point.
- **`depends()` and `invalidate()`** for fine-grained revalidation. `invalidateAll()` is a sledgehammer.

## 6. Svelte 5 runes correctness

Read [references/svelte5-runes.md](references/svelte5-runes.md). Skip this section entirely if the project is Svelte 4.

The single most common Svelte 5 bug: using `$effect` where `$derived` should be used.

```svelte
<!-- ❌ Wrong: $effect computing a value -->
<script>
  let count = $state(0);
  let double = $state(0);
  $effect(() => { double = count * 2; });
</script>

<!-- ✅ Right: $derived -->
<script>
  let count = $state(0);
  let double = $derived(count * 2);
</script>
```

Other red flags:

- **Destructuring `$state`** loses reactivity: `let { name } = user` is a snapshot, not reactive.
- **`$effect` without cleanup** for subscriptions, intervals, listeners — memory leaks.
- **`$state` on data that's only replaced, never mutated** — use `$state.raw` to skip the Proxy.
- **Legacy syntax in new code**: `export let`, `on:click`, `<slot>`, `createEventDispatcher`, `$:` — flag all of them.
- **Stores wrapped around runes**, or runes wrapped around stores, when one or the other would do.
- **SvelteKit ≥ 2: `$page` from `$app/stores` is legacy**. New code uses `page` from `$app/state`.
- **`{#each}` keyed by index** instead of stable ID — subtle DOM recycling bugs.

## 7. File & route conventions

Read [references/conventions.md](references/conventions.md).

The framework's filename conventions are load-bearing — wrong names silently disable features:

- `+page.svelte` — page UI
- `+page.ts` / `+page.js` — universal load + page options
- `+page.server.ts` / `+page.server.js` — server load, form actions
- `+layout.svelte` — layout UI (renders children via `<slot/>` in Svelte 4, `{@render children()}` in Svelte 5)
- `+layout.ts` / `+layout.server.ts` — layout load
- `+server.ts` / `+server.js` — standalone API endpoint, exports `GET`/`POST`/etc.
- `+error.svelte` — error boundary for the route subtree
- `+layout@.svelte` — break out of layout inheritance
- `(group)/` — route groups (no URL segment)
- `[param]` / `[...rest]` / `[[optional]]` — dynamic, rest, optional params
- `[param=matcher]` — param matchers, defined in `src/params/<matcher>.ts`

Findings to look for: ad-hoc routing files like `page.svelte` (no `+`), TypeScript files named `+page.tsx` (not supported), business logic in `+page.svelte` instead of in load/actions/components, components defined inside `src/routes/` that aren't `+` files (allowed but discouraged — prefer `$lib/components/`).

`+page.svelte` should be thin: import components, render `data` and `form`. If it has > ~100 lines or business logic, that's a structure smell.

## 8. XSS, headers, CSP

Read [references/security.md](references/security.md) for the full list.

- **`{@html}` only on sanitized HTML.** Audit every use. The standard mitigation: pass through DOMPurify before rendering, or restrict to known-safe sources (markdown rendered by a trusted lib with sanitization on).
- **`href={someUrl}`** with user-controlled URL allows `javascript:` URIs. Svelte does not strip these. Validate scheme.
- **Security headers set in `hooks.server.ts`**: `Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Permissions-Policy`, `Strict-Transport-Security` (production), `X-Frame-Options` (or CSP frame-ancestors).
- **CSP via `kit.csp` config** is preferred for SvelteKit — it auto-generates hashes for inline scripts/styles. Manual CSP in headers tends to break with hydration.
- **No secrets in `$env/static/public` or `PUBLIC_*` vars.** The `PUBLIC_` prefix means "ships to the browser."

## 9. Performance

Read [references/performance.md](references/performance.md).

- **Bundle size**: run `vite build` and inspect `.svelte-kit/output/client/_app/immutable/`. Use `rollup-plugin-visualizer` for breakdown. Heavy deps (moment, lodash, full charting libs) are common culprits.
- **`prerender = true`** on routes that are truly static — flag pages that fetch user-specific data but have prerender on (will crash or leak).
- **`ssr = false`** disables SSR for a route — flag if used carelessly; usually the wrong default.
- **Dynamic imports for heavy below-the-fold components**: `const Heavy = (await import('./Heavy.svelte')).default`.
- **Preload fonts manually** via `handle` hook's `resolve(event, { preload })` — Kit doesn't preload fonts by default.
- **Image optimization**: `@sveltejs/enhanced-img` for build-time image processing.
- **`data-sveltekit-preload-data`** strategies on `<a>` tags for fast nav.

## 10. Accessibility

- The Svelte compiler emits a11y warnings — disabling them via `<!-- svelte-ignore -->` should be rare and justified. Flag broad disables.
- Custom interactive components (modals, dropdowns, comboboxes) need focus management, keyboard handling, and ARIA. `use:` actions are the idiomatic way to attach focus traps.
- Form labels: every `<input>` has a `<label for>` or wraps the input. `aria-label` is a fallback, not a default.
- Color contrast and motion-reduction (`prefers-reduced-motion`) — out of scope for this skill unless explicitly asked.

## 11. Error handling & observability

- **`handleError` hook in `hooks.server.ts`** for capturing server errors. Flag projects that crash silently in production with no logging.
- **`+error.svelte`** at appropriate levels — at minimum a root one. Throwing `error(404, ...)` and `error(500, ...)` from load functions is the right pattern, not `return { error: ... }`.
- **`redirect()` from `@sveltejs/kit`** in load/action — not `throw new Response(...)`. Don't catch redirects in try/catch (SvelteKit 2 changed redirects to non-throwing — verify by SvelteKit version).
- **No `console.log` left in server code** in production paths. Structured logging (pino, etc.) preferred.

## 12. Testing & type safety

- **TypeScript on**: `tsconfig.json` extends `./.svelte-kit/tsconfig.json`. `strict: true` is the bar.
- **`./$types` imports**: load functions typed as `PageServerLoad`/`PageLoad`, actions as `Actions`, server endpoints as `RequestHandler`. SvelteKit 2.16+ also exposes `PageProps`/`LayoutProps`.
- **`app.d.ts`** has `App.Locals` typed (not `any`), and `App.Error`, `App.PageData`, `App.Platform` where used.
- **Vitest** for unit tests of pure functions and server logic. **Playwright** for E2E. Flag a project with no tests at all if it's claiming to be production-bound.

## Report template

After the review, output findings in this format:

```markdown
# SvelteKit code review

**Project**: <name>
**SvelteKit**: <version> · **Svelte**: <version> · **Adapter**: <adapter>
**Scope**: <what was reviewed>

## Summary
<2-3 sentences: overall state, top 3 risks, top 3 strengths>

## Critical (security / data-loss)
### C1. <Short title>
- **Where**: `src/routes/admin/+page.svelte:42`
- **What**: <one sentence>
- **Why it matters**: <impact in plain language>
- **Fix**: <concrete change, ideally a code diff>

## High (correctness / framework misuse)
...

## Medium (conventions / maintainability)
...

## Low / nits
...

## What's done well
<3-5 concrete positives — not generic praise>
```

Severity rubric:

- **Critical**: security leak, auth bypass, data corruption, production crash path. Examples: secret in client bundle, missing CSRF on state-changing endpoint, `{@html}` on untrusted input.
- **High**: framework misuse that will cause real bugs or major refactor later. Examples: `$effect` for derivations, auth check only in client, business logic in `+page.svelte`.
- **Medium**: convention violation, perf foot-gun, accessibility gap. Examples: missing `key` in `{#each}`, no `+error.svelte`, no `App.Locals` types.
- **Low**: style, naming, tiny dead code.

Don't pad findings. If there's nothing critical, say so. False positives erode trust faster than missed issues.

## Reference files

When you hit something nontrivial in a section, read the matching reference file. Each is a deep-dive on one topic:

- [references/security.md](references/security.md) — server/client boundary, env vars, secrets, CSP, headers, XSS, CVE history
- [references/auth.md](references/auth.md) — session cookies, route protection patterns, hooks-based middleware
- [references/forms-and-actions.md](references/forms-and-actions.md) — actions, validation, CSRF, superforms, file uploads
- [references/load-functions.md](references/load-functions.md) — server vs universal, streaming, invalidation, parent(), waterfalls
- [references/svelte5-runes.md](references/svelte5-runes.md) — `$state`/`$derived`/`$effect`/`$props`/`$bindable` correct usage and anti-patterns
- [references/conventions.md](references/conventions.md) — file naming, route structure, layout patterns, larger-app organization
- [references/performance.md](references/performance.md) — bundle size, preloading, SSR/CSR/SSG trade-offs, streaming, hydration
- [references/checklist.md](references/checklist.md) — flat, dense, copy-pasteable checklist for fast scans
