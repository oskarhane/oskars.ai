# Load functions reference

## Contents
- Server vs universal load
- Layout load and inheritance
- `parent()`, sequencing, and waterfalls
- Streaming with promises
- `depends()` and `invalidate()`
- The provided `fetch`
- Cookies, headers, setHeaders
- Common findings

## Server vs universal load

| File | Runs on | Use for |
|---|---|---|
| `+page.server.ts` | Server only | DB queries, secrets, private API calls, cookies, anything sensitive |
| `+page.ts` | Server and client | Public APIs without credentials, non-serializable returns (e.g. component constructors) |
| `+page.svelte` | Client (and SSR for first render) | UI |

Same pattern for layouts. Default: **use the server version** unless you specifically need the universal version. The universal layer is the default for some older tutorials but the server layer is safer and more common in production code.

**Both can exist for the same route.** When both exist:
1. `+page.server.ts` runs first
2. Its return value is passed to `+page.ts` as `data`
3. `+page.ts` returns the merged data to the page

This is the "universal layer for transformation" pattern — server fetches sensitive data, universal load augments with a component constructor or similar.

```ts
// +page.server.ts
export const load: PageServerLoad = async ({ locals }) => {
  const user = await db.user.findUnique({ where: { id: locals.userId } });
  return { user };  // user is in `data` for +page.ts
};

// +page.ts
import Avatar from '$lib/components/Avatar.svelte';
export const load: PageLoad = async ({ data }) => {
  return { ...data, AvatarComponent: Avatar };
};
```

Findings:

- Universal load that imports from `$lib/server/` — Vite blocks but flag attempts.
- Universal load that calls a third-party API with a secret key — leaks via the client fetch.
- Both files exist but the universal one only re-passes `data` — useless wrapper.
- Server load returns `{ user: locals.user }` — fine, but verify sensitive fields are stripped.

## Layout load

`+layout.server.ts` runs for every route under that layout. Its data merges into the page's `data` prop.

Don't put per-page data in layout loads — they re-run more often than needed and increase coupling. Layout loads are for genuinely shared data (user, navigation, theme).

## `parent()` and waterfalls

```ts
export const load: PageServerLoad = async ({ parent }) => {
  const { user } = await parent();
  const dashboard = await getDashboard(user.id);
  return { dashboard };
};
```

**`await parent()` is a synchronization point** — the layout load must finish before this line runs. If the dashboard fetch doesn't actually need the user, don't await parent:

```ts
// ❌ Waterfall: layout load → dashboard load, sequential
export const load: PageServerLoad = async ({ parent, locals }) => {
  await parent();  // unnecessary
  return { dashboard: await getDashboard(locals.userId) };
};

// ✅ Parallel
export const load: PageServerLoad = async ({ locals }) => {
  return { dashboard: await getDashboard(locals.userId) };
};
```

Real waterfall to look for: multiple `await`s in sequence where the data is independent.

```ts
// ❌ Sequential
const a = await fetchA();
const b = await fetchB();
const c = await fetchC();

// ✅ Parallel
const [a, b, c] = await Promise.all([fetchA(), fetchB(), fetchC()]);
```

Findings: any `await parent()` with no use of parent data; any block of three+ sequential `await`s for independent queries; sequential awaits inside `Promise.all` arguments.

## Streaming with promises

A non-awaited promise inside the returned object is streamed to the client. The page renders without waiting; the promise resolves later.

```ts
export const load: PageServerLoad = async () => {
  return {
    fast: await fetchFast(),       // blocks load
    slow: fetchSlow()              // streams in background
  };
};
```

```svelte
<script>
  let { data } = $props();
</script>

<h1>{data.fast.title}</h1>

{#await data.slow}
  <p>Loading...</p>
{:then slow}
  <p>{slow.value}</p>
{:catch error}
  <p>Failed: {error.message}</p>
{/await}
```

**Critical gotcha**: an unhandled rejection on a streamed promise crashes the server with "unhandled promise rejection" if it fires before rendering starts. SvelteKit's provided `fetch` handles this internally. For your own promises, attach a noop `.catch()` defensively, or always handle in the `{:catch}` block.

```ts
// Defensive: mark as handled
const slow = fetchSlow().catch((e) => {
  // log here if you want
  throw e;  // re-throw so the {:catch} block still fires
});
return { fast: await fetchFast(), slow };
```

Findings:

- Top-level streamed promise (returning a promise directly, not nested in an object) — that just blocks. Streamed = nested in the returned object.
- `{#await}` block without `{:catch}` — silent failure on slow data.
- Streaming sensitive data from a route that also serves the UI — exposes it in the SSR stream payload, fine, but verify error-handling on the client.

## `depends()` and `invalidate()`

For fine-grained revalidation when the URL or default deps haven't changed:

```ts
export const load: PageServerLoad = async ({ depends }) => {
  depends('app:cart');
  return { cart: await getCart() };
};

// Elsewhere
import { invalidate } from '$app/navigation';
await invalidate('app:cart');  // re-runs any load with this dep
```

Prefix with a namespace (`app:`, `data:`, etc.) to avoid collisions with URL deps.

`invalidateAll()` re-runs every load — sledgehammer, use sparingly. Often misused after a single mutation when `invalidate('app:thing')` would do.

Findings:

- `invalidateAll()` after every mutation — unnecessary network thrashing.
- `depends()` declared but never `invalidate`d — dead code.
- `invalidate()` with a string that doesn't match any `depends()` — silent no-op.

## The provided `fetch`

The `fetch` passed to load functions is special:

- Forwards cookies on same-origin requests.
- Forwards headers SvelteKit chose to forward.
- During SSR, internal API calls (`/api/...`) go directly to the handler — no HTTP round-trip.
- Cached responses survive hydration (the client picks up where SSR left off).

```ts
// ✅ Use the provided fetch
export const load: PageLoad = async ({ fetch }) => {
  const res = await fetch('/api/posts');
  return { posts: await res.json() };
};

// ❌ Global fetch — extra round-trip, no cookie forwarding
import { fetch } from 'node:fetch';
```

Findings:

- Global `fetch` used in a load — flag.
- Provided `fetch` ignored and a separate HTTP client (axios, ky) used — loses framework integration; sometimes intentional (interceptors), often not.

## Cookies, headers, setHeaders

Only available in server loads.

```ts
export const load: PageServerLoad = async ({ cookies, setHeaders }) => {
  cookies.set('seen-banner', '1', { path: '/', maxAge: 60 * 60 * 24 * 365 });
  setHeaders({
    'cache-control': 'public, max-age=60',
    'x-frame-options': 'DENY'
  });
  return {};
};
```

**Cannot set `set-cookie` via `setHeaders`** — must use `cookies.set`. The framework will throw a clear error.

**`setHeaders` from a universal load is a silent no-op on the client** (no headers to set). It only takes effect on SSR.

Findings:

- `setHeaders({ 'set-cookie': ... })` — wrong API.
- `cache-control` set on a route that returns user-specific data — caches across users at CDN.
- No `cache-control` on a route that could safely be edge-cached — perf opportunity, not a bug.

## Module-level state — don't

```ts
// ❌ NEVER
let cachedData = null;

export const load: PageServerLoad = async () => {
  if (!cachedData) cachedData = await db.users.findMany();
  return { users: cachedData };
};
```

Server modules are shared across all requests. The "cache" leaks data between users and across deploys. Use a real cache (Redis, Cloudflare KV) or `setHeaders` for CDN caching.

Same for module-level `Map`s, `Set`s, etc. acting as in-process caches — fine for truly static data, dangerous for per-user data.

## Loading types

```ts
import type { PageServerLoad, PageLoad, LayoutServerLoad, LayoutLoad } from './$types';
```

`./$types` is auto-generated by SvelteKit. Imports look like they don't exist on disk — they're generated under `.svelte-kit/types/`.

**Untyped load functions are a finding** — defeats most of SvelteKit's type safety.

`PageProps` and `LayoutProps` (Kit 2.16+) simplify component prop typing:

```svelte
<script lang="ts">
  import type { PageProps } from './$types';
  let { data, form }: PageProps = $props();
</script>
```

Earlier Kit versions used `PageData` directly:

```svelte
<script lang="ts">
  import type { PageData } from './$types';
  let { data }: { data: PageData } = $props();
</script>
```

Both work; flag the older pattern as a non-urgent modernization.

## Quick findings checklist

- Universal load doing what server load should
- Module-level "cache" in a server load
- `await parent()` without using parent data
- Sequential awaits that should be `Promise.all`
- Streamed promise without `{:catch}`
- `invalidateAll()` instead of targeted `invalidate()`
- Global `fetch` in a load
- `setHeaders` for cookies
- `cache-control` on per-user content
- Untyped load function
- Load function with side effects (logging fine; DB writes wrong)
