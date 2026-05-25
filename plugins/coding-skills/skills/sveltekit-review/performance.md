# Performance reference

## Contents
- Rendering modes: SSR, CSR, SSG, ISR
- Bundle size
- Hydration cost
- Preloading
- Streaming
- Image and font handling
- Adapter-specific notes
- Common findings

## Rendering modes

SvelteKit can mix modes per route via `+page.ts` / `+layout.ts` exports:

```ts
export const ssr = true;       // server-rendered first paint (default)
export const csr = true;       // hydrated, interactive (default)
export const prerender = true; // built at build time, static HTML output
```

Combinations:

| ssr | csr | prerender | Result |
|---|---|---|---|
| true | true | false | SSR + hydration (default; fast first paint, interactive) |
| true | true | true | SSG + hydration (deploy as static, hydrate for interactivity) |
| true | false | true | Pure static, no JS (marketing pages) |
| false | true | false | SPA route (no SSR, JS-only) |
| true | false | false | SSR-only (no JS) — niche |

**`prerender = true`** crashes the build if the route accesses:
- `event.cookies` (no request to read from)
- `event.locals` (no hook ran)
- `event.url.searchParams` (no specific request)
- `$env/dynamic/private` (not known at build)

**`prerender = 'auto'`** prerenders only routes that work, falls back to SSR otherwise. Reasonable default for mixed sites.

**`ssr = false`** disables server rendering — page renders only on the client. First paint is a blank/skeleton until JS loads. Use case: routes with heavy client-only deps, or admin areas where SEO doesn't matter.

**`csr = false`** ships no JS for the route — fastest possible page, but no interactivity (forms still work via standard HTML POST).

Findings:

- `prerender = true` on a page reading user-specific data — build error or stale build.
- `ssr = false` as a workaround for an SSR bug somewhere — hides the bug.
- `csr = false` on an interactive page — buttons silently broken.
- Conflict between root `+layout.ts` setting `prerender = true` and a child page that can't prerender — child wins, but flag confusion.

## Bundle size

Inspect the production build:

```bash
npm run build
ls -lh .svelte-kit/output/client/_app/immutable/
du -sh .svelte-kit/output/client/_app/immutable/chunks/
du -sh .svelte-kit/output/client/_app/immutable/entry/
```

For breakdown by package, add `rollup-plugin-visualizer`:

```ts
// vite.config.ts
import { visualizer } from 'rollup-plugin-visualizer';

export default {
  plugins: [
    sveltekit(),
    visualizer({ filename: 'stats.html', gzipSize: true, brotliSize: true })
  ]
};
```

Open `stats.html` after build. Common culprits:

- `moment` (270KB+) — replace with `date-fns` (tree-shakeable), `dayjs`, or native `Intl.DateTimeFormat`.
- Full `lodash` instead of `lodash-es` with named imports.
- Whole charting library bundled when only one chart type used (Chart.js, Plotly).
- Polyfills imported globally for browser features used by 0.1% of users.
- SVG sprite sheets imported eagerly instead of inlined per-icon.
- Duplicate copies of the same lib at different versions (`npm ls <pkg>` to detect).

Tools: `npx source-map-explorer` on a built JS file for line-level analysis.

## Hydration cost

For routes that are mostly static, consider `csr = false` to skip hydration entirely. The page renders with no JS download, no hydration walk.

If hydration is needed, minimize per-component JS:

- Don't ship analytics/tracking inline — use deferred / partytown.
- Move heavy below-the-fold widgets to dynamic imports:

```svelte
<script lang="ts">
  let Heavy = $state<typeof import('./Heavy.svelte').default | null>(null);
  $effect(() => {
    import('./Heavy.svelte').then(m => Heavy = m.default);
  });
</script>
{#if Heavy}<Heavy />{/if}
```

For above-the-fold content, static import keeps it in the main bundle (good for perceived perf).

## Preloading

SvelteKit auto-preloads JS/CSS for adjacent routes when the user hovers a link (`data-sveltekit-preload-data="hover"` is the default for internal links). Tune at the layout level:

```svelte
<!-- +layout.svelte -->
<svelte:body data-sveltekit-preload-data="tap" />
```

Strategies:
- `eager` — preload as soon as the link is in the viewport
- `hover` — preload on hover
- `tap` — preload on pointerdown (mobile-friendly, avoids speculative downloads)
- `off` — don't preload

Per-link override: `<a data-sveltekit-preload-data="off" href="/heavy">`.

`data-sveltekit-preload-code` similarly for JS only (no data fetch).

**Fonts are NOT auto-preloaded** — SvelteKit can't know which weights/styles each page actually uses. Manual preload in the handle hook:

```ts
export const handle: Handle = async ({ event, resolve }) => {
  return resolve(event, {
    preload: ({ type, path }) => {
      if (type === 'font' && path.endsWith('.woff2')) return true;
      return type === 'js' || type === 'css';
    }
  });
};
```

Findings:

- Preload strategy never customized (default `hover`) — usually fine, but `tap` is better on mobile-heavy sites.
- Fonts loaded via CSS `@import` with no `font-display: swap` — invisible text during FOIT.
- Heavy preload across an admin app where speculative loading wastes bandwidth.

## Streaming

Returning a non-awaited promise from a server load streams the data:

```ts
return {
  user: await getUser(),         // blocks
  recommendations: getRecs()     // streams
};
```

```svelte
{#await data.recommendations}
  <Skeleton />
{:then recs}
  <Recs {recs} />
{:catch e}
  <Error message={e.message} />
{/await}
```

Result: TTFB is the time to fetch the user; the page renders with a skeleton; recommendations land when ready. Improves perceived perf when one fetch is slow but optional.

Pitfalls:

- Promises that reject without a `.catch()` crash the SSR server. Use `{:catch}` in the template AND attach a defensive `.catch` if the load function may handle the error.
- Top-level returned promise (not nested) blocks — same as await.
- Streaming over HTTP/1.1 has quirks; HTTP/2+ is the assumed target.

## Image and font handling

- `@sveltejs/enhanced-img` for build-time image processing (responsive, AVIF/WebP, blur placeholders).
- `static/` for assets that should pass through unchanged.
- `src/lib/assets/` (any non-`static` path imported via Vite) gets hashed filenames and tree-shaking.

```svelte
<script>
  import hero from '$lib/assets/hero.jpg?enhanced';
</script>
<enhanced:img src={hero} alt="..." />
```

Findings:

- Raw `<img>` tags with multi-megabyte JPGs from `static/` — no responsive sizing, no modern formats.
- Fonts loaded from CDN (Google Fonts) without `&display=swap` — invisible text.
- Multiple variants of the same font (Regular, Bold, Italic, Bold-Italic) shipped when only Regular is used.

## Adapter-specific notes

### Node (`@sveltejs/adapter-node`)

- Long-running process, can use any Node API.
- Body size limit defaults to 512KB — `BODY_SIZE_LIMIT` env var to change.
- No automatic CDN caching; use a reverse proxy.

### Vercel (`@sveltejs/adapter-vercel`)

- ISR available via `config.isr` per route.
- Functions are stateless — no in-process caching between requests.
- Edge runtime opt-in via `config.runtime = 'edge'` (limited Node API).
- Image optimization via `@sveltejs/enhanced-img` + Vercel's CDN.

### Cloudflare (`@sveltejs/adapter-cloudflare`)

- Workers runtime — no Node APIs (`fs`, `path`, `crypto.createHmac` etc).
- `event.platform.env` for KV, D1, R2 bindings.
- Strict CPU time limits per request.
- Body size limits per Cloudflare plan.

### Static (`@sveltejs/adapter-static`)

- Pure SSG — no server endpoints (`+server.ts` files cause build errors).
- Every route must be prerenderable.

Findings:

- Code using Node APIs (`fs.readFileSync`) with Cloudflare adapter — runtime crash.
- Adapter-static with form actions — actions can't run; build error or silent breakage.
- Vercel deployment but no `config.isr` on routes that could benefit.

## Network optimizations

- `cache-control` headers in `setHeaders` for public, non-user-specific routes:
  ```ts
  setHeaders({ 'cache-control': 'public, max-age=300, s-maxage=600' });
  ```
- `Vary: Cookie` if the cache key depends on a cookie.
- Compression usually adapter-level (Vercel, Cloudflare, Netlify do it). For Node adapter, put behind a reverse proxy (Nginx, Caddy) with gzip/brotli on.

## Common findings summary

1. Default `prerender = false` on truly-static marketing pages — leaving perf on the table.
2. `ssr = false` as a quick fix masking real bugs.
3. No bundle analysis — opaque deps.
4. `moment` / full `lodash` / large polyfills in bundle.
5. Fonts loaded via CDN with no `font-display`.
6. No image optimization.
7. Streaming not used where it would clearly help.
8. `data-sveltekit-preload-data="hover"` on mobile-heavy sites (use `tap`).
9. Heavy module-level imports in `hooks.server.ts` slowing cold starts.
10. Cache-control headers not set on cacheable routes.
