# File and route conventions reference

## Contents
- File naming reference
- Routing primitives
- Layout system and `@` resets
- Route groups
- Param matchers
- Page options
- `$lib`, `$lib/server`, `$app/*` aliases
- Larger app organization
- Common structural smells

## File naming reference

Files with names starting with `+` are special to SvelteKit. Anything else is treated as a component or utility colocated with the route.

| File | Purpose |
|---|---|
| `+page.svelte` | Page component |
| `+page.ts` / `+page.js` | Universal load + page options |
| `+page.server.ts` / `+page.server.js` | Server load, form actions, page options |
| `+layout.svelte` | Layout component (wraps children) |
| `+layout.ts` / `+layout.js` | Universal layout load |
| `+layout.server.ts` / `+layout.server.js` | Server layout load |
| `+error.svelte` | Error boundary for this route subtree |
| `+server.ts` / `+server.js` | Standalone API endpoint (GET, POST, etc.) |
| `+layout@.svelte` | Reset layout inheritance to root |
| `+layout@named.svelte` | Reset to a specific named ancestor |
| `+page@.svelte` | Page that opts out of all ancestor layouts |

Filename typos that silently break things:

- `page.svelte` (missing `+`) — treated as a regular component, no routing.
- `+Page.svelte` (capital P) — not recognized.
- `+page.tsx` — not supported; TypeScript JSX isn't a SvelteKit concept.
- `+server.svelte` — nonsense, but the kind of typo that compiles to a component you can't reach.
- `+layout.server.svelte` — there's no such thing; servers don't have UI.

## Routing primitives

| Pattern | Behavior |
|---|---|
| `/about` | Static |
| `/posts/[slug]` | Dynamic param (`params.slug`) |
| `/files/[...path]` | Rest param, matches any depth |
| `/items/[[id]]` | Optional param |
| `/users/[id=integer]` | Param with matcher (defined in `src/params/integer.ts`) |

Param matchers in `src/params/<name>.ts`:

```ts
import type { ParamMatcher } from '@sveltejs/kit';
export const match: ParamMatcher = (param) => /^\d+$/.test(param);
```

Findings:

- Routes with `[id]` that should be `[id=integer]` — invalid input reaches the load function instead of falling through to 404.
- Rest param at the wrong depth — `/[...path]` at the root catches everything and breaks other routes.

## Layout system

Layouts wrap pages. They render via `{@render children()}` (Svelte 5) or `<slot/>` (Svelte 4):

```svelte
<!-- +layout.svelte (Svelte 5) -->
<script lang="ts">
  import type { Snippet } from 'svelte';
  let { children }: { children: Snippet } = $props();
</script>
<nav>...</nav>
<main>{@render children()}</main>
```

```svelte
<!-- +layout.svelte (Svelte 4) -->
<nav>...</nav>
<main><slot/></main>
```

Inheritance: each `+layout.svelte` wraps everything under it. Root layout (`src/routes/+layout.svelte`) wraps the entire app.

**Layout reset** with `@`: `+layout@.svelte` resets to the root, `+layout@foo.svelte` resets to the layout in `routes/foo/`. Used to escape nested layouts for specific pages (e.g. a full-screen page in an app shell).

Findings:

- Per-page logic in a layout — bloats layout load, affects siblings.
- Root layout with no error boundary — uncaught errors hit SvelteKit's default error page.
- Multiple layout files with conflicting concerns — refactor opportunity.

## Route groups

Directories wrapped in parens don't add URL segments:

```
src/routes/
  (marketing)/
    +layout.svelte         ← marketing site layout
    +page.svelte           ← /
    pricing/+page.svelte   ← /pricing
  (app)/
    +layout.svelte         ← app shell
    +layout.server.ts      ← auth gate for the group
    dashboard/+page.svelte ← /dashboard
```

Used for grouping routes that share a layout or auth check without affecting URLs.

Findings:

- Auth group lacks a `+layout.server.ts` — group is "protected" only by client-side wrappers.
- Group has nested groups with duplicate auth checks — collapse.
- Group named after a feature but containing unrelated routes.

## Page options

Configurable per page/layout via exports from `+page.ts`/`+layout.ts`/etc:

```ts
export const prerender = true;       // build-time static generation
export const ssr = true;             // server-side render this page (default true)
export const csr = true;             // client-side render (hydration) (default true)
export const trailingSlash = 'never'; // 'always' | 'never' | 'ignore'
export const config = { ... };       // adapter-specific
```

Findings:

- `prerender = true` on a route that reads cookies, locals, or runtime env — build crashes or produces a frozen-in-time response.
- `ssr = false` as a workaround for an SSR bug — hides the bug; usually wrong.
- `csr = false` on a page with interactivity — buttons won't work after hydration.
- `prerender = 'auto'` everywhere without thought — works but trades flexibility for opaqueness.

## `$lib`, `$lib/server`, `$app/*`

| Alias | Maps to |
|---|---|
| `$lib` | `src/lib/` |
| `$lib/server` | `src/lib/server/` — server-only enforcement |
| `$app/state` | Runes-based state (page, navigating, updated) |
| `$app/stores` | Legacy store-based state (still works) |
| `$app/environment` | `browser`, `dev`, `building`, `version` |
| `$app/navigation` | `goto`, `invalidate`, `invalidateAll`, `preloadData`, etc. |
| `$app/forms` | `enhance`, `applyAction`, `deserialize` |
| `$app/paths` | `base`, `assets` for path manipulation |
| `$app/server` | `read` for filesystem reads on the server |
| `$env/static/private` | Build-time private env (server-only) |
| `$env/dynamic/private` | Runtime private env (server-only) |
| `$env/static/public` | Build-time public env |
| `$env/dynamic/public` | Runtime public env |

Findings:

- Relative imports (`../../../lib/...`) instead of `$lib/...` — works but brittle.
- `$app/stores` and `$app/state` mixed.
- `$lib/server` imports leaking — Vite blocks but flag attempts.
- Custom aliases in `vite.config.ts` for `$components` etc — fine, but `$lib/components` already works.

## Larger app organization

For apps over ~50 routes, flat `$lib/` becomes painful. The pattern that scales:

```
src/lib/
  server/                 # server-only (DB, auth, secrets)
    db.ts
    auth.ts
  domains/
    billing/
      types.ts
      client.svelte.ts    # runes-based state
      server.ts           # server logic (gets re-exported under server/)
      components/
        BillingForm.svelte
    auth/
      types.ts
      server.ts
      components/
    inventory/
      ...
  shared/                 # truly cross-domain
    components/
      Button.svelte
      Modal.svelte
    ui/                   # design system primitives
    utils/
```

`src/routes/` stays thin — each `+page.svelte` imports from `$lib/domains/<x>/components/` and renders data from the load function.

Findings in larger codebases:

- `src/lib/components/` with 60+ unrelated components — split by domain.
- `src/lib/utils.ts` as a 1000-line dumping ground — split by purpose.
- Business logic in `+page.svelte` — should be in `$lib/domains/<x>/` or in load/actions.
- Cross-domain imports forming a dependency graph that's hard to follow — domain isolation broken.

## Common structural smells

### Smell 1: Business logic in `+page.svelte`

```svelte
<!-- ❌ -->
<script>
  let { data } = $props();
  async function complexCalc() {
    const result = await db.something(...);  // can't even access db on client
    // ...
  }
</script>
```

Move to load (for derivations on render data) or actions (for mutations).

### Smell 2: Component logic duplicated across routes

Three routes have the same form pattern with minor differences → extract to `$lib/components/SomeForm.svelte` with props.

### Smell 3: Routes deeply nested without grouping

`src/routes/a/b/c/d/e/+page.svelte` for a URL that's already at `/a/b/c/d/e` may be legitimate. But often it's accidental nesting where a flat structure under a route group would be cleaner.

### Smell 4: Server logic outside server-only files

```ts
// src/lib/api.ts (NOT server-only)
import { SECRET } from '$env/static/private';  // ← Vite error
```

Move to `src/lib/server/api.ts` or rename to `src/lib/api.server.ts`.

### Smell 5: One-off types in route files instead of `app.d.ts`

`App.Locals`, `App.Error`, `App.PageData`, `App.Platform` should be defined in `src/app.d.ts`. Each route inventing local types for these is repetition.

### Smell 6: No `static/` discipline

`static/` is served as-is. Putting large or per-environment files here breaks deploys. Build-time assets that should be processed go through Vite (`src/lib/assets/`).

### Smell 7: `+page.svelte` over 200 lines

Usually a sign one of:
- Multiple pages worth of UI on one route → split into components.
- Inline state management that should be in a `.svelte.ts` file.
- Style block that should be extracted (small per-route styles are fine).

## Testing the conventions

`svelte-check` enforces some conventions. Findings:

- No `svelte-check` script in `package.json` — flag.
- `svelte-check` running but with errors — flag.
- `eslint-plugin-svelte` not present in a TS project — recommended.
