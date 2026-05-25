# Authentication & route protection reference

## Contents
- Session cookie pattern
- `event.locals` and `App.Locals`
- Resolving auth in `hooks.server.ts`
- Route protection patterns (route group, prefix check, layout-based)
- Client-side navigation and the empty `+layout.server.ts` trick
- Auth in form actions vs load functions
- OAuth callback patterns
- Common bypass patterns to look for

## Session cookie pattern

The canonical pattern: opaque session token in an HttpOnly, Secure, SameSite cookie. Token maps to a server-side session record (DB, Redis, signed JWT).

```ts
// On login (in a form action)
const sessionId = await createSession(user.id);
cookies.set('session', sessionId, {
  httpOnly: true,
  secure: true,
  sameSite: 'lax',
  path: '/',
  maxAge: 60 * 60 * 24 * 7
});

// On logout
cookies.delete('session', { path: '/' });
```

**`path` must match between `set` and `delete`** — easy bug to introduce.

**`sameSite: 'strict'` breaks the OAuth callback flow.** Returning from an external IdP with `strict` cookies means the cookie isn't sent on the redirect-back request. Use `lax` (the default in modern browsers anyway), or set the cookie only after the callback completes.

**`secure: true` even in dev when possible** — use mkcert. Falling back to `secure: false` in dev is fine, but make it environment-conditional, not hardcoded.

**Don't trust JWT alone for sessions.** Stateless JWTs can't be revoked. If the project uses JWT-as-session and never checks a DB, flag the inability to invalidate compromised tokens. Refresh-token + short-lived JWT works around this but is more complex.

## `App.Locals`

`event.locals` is the request-scoped place to put authenticated user info. Type it in `src/app.d.ts`:

```ts
declare global {
  namespace App {
    interface Locals {
      user: { id: string; email: string; role: 'user' | 'admin' } | null;
      session: { id: string; expiresAt: Date } | null;
    }
  }
}
export {};
```

Untyped `locals` (defaulting to `any`) is a finding — defeats type safety across the request lifecycle.

## Auth in `hooks.server.ts`

Resolve the session once, in the handle hook, before any load function runs:

```ts
import type { Handle } from '@sveltejs/kit';
import { sequence } from '@sveltejs/kit/hooks';
import { redirect } from '@sveltejs/kit';

const authentication: Handle = async ({ event, resolve }) => {
  const sessionId = event.cookies.get('session');
  if (sessionId) {
    const session = await getSession(sessionId);
    if (session && session.expiresAt > new Date()) {
      event.locals.user = await getUser(session.userId);
      event.locals.session = session;
    } else {
      // expired or invalid — clean up
      event.cookies.delete('session', { path: '/' });
      event.locals.user = null;
      event.locals.session = null;
    }
  } else {
    event.locals.user = null;
    event.locals.session = null;
  }
  return resolve(event);
};

const authorization: Handle = async ({ event, resolve }) => {
  if (event.url.pathname.startsWith('/app') && !event.locals.user) {
    redirect(303, `/login?redirectTo=${encodeURIComponent(event.url.pathname)}`);
  }
  if (event.url.pathname.startsWith('/admin') && event.locals.user?.role !== 'admin') {
    redirect(303, '/');
  }
  return resolve(event);
};

export const handle = sequence(authentication, authorization);
```

Why split into two handlers: clear separation, easier to test, easier to skip one for specific routes. `sequence` runs them in order.

## Route protection patterns

Three reasonable patterns. Listed in increasing order of compile-time safety.

### A. Prefix check in hooks (above)

Pros: centralized, simple. Cons: easy to forget when adding a new protected area; auth logic spread between `hooks.server.ts` and any route-specific checks.

### B. Route groups

```
src/routes/
  (public)/
    +layout.svelte
    +page.svelte
    login/+page.server.ts
  (app)/
    +layout.server.ts      ← runs on every protected route
    +layout.svelte
    dashboard/+page.svelte
    settings/+page.svelte
  (admin)/
    +layout.server.ts      ← additional admin check
    +layout.svelte
    users/+page.svelte
```

`(app)/+layout.server.ts`:
```ts
import { redirect } from '@sveltejs/kit';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async ({ locals, url }) => {
  if (!locals.user) {
    redirect(303, `/login?redirectTo=${encodeURIComponent(url.pathname)}`);
  }
  return { user: locals.user };
};
```

Pros: protection co-located with the routes it protects, naturally enforced via the layout chain. Cons: layout load runs only when the route actually has a `+layout.server.ts` and depends on SvelteKit's data invalidation rules; client-side navigation between sibling routes under the same `+layout.server.ts` may not re-run the layout load.

### C. Per-route `+page.server.ts` checks

```ts
export const load: PageServerLoad = async ({ locals }) => {
  if (!locals.user) redirect(303, '/login');
  if (locals.user.role !== 'admin') redirect(303, '/');
  return { user: locals.user };
};
```

Pros: explicit, hard to miss. Cons: massive repetition; easy for one route to drift.

**Recommended**: route groups + a single `+layout.server.ts` per group, with a backstop check in `hooks.server.ts` for any path that should never be reached without auth. Re-check inside individual actions for state-changing operations regardless.

## The empty `+layout.server.ts` trick

For client-side navigation: SvelteKit may not re-run a parent layout's server load on every nav, depending on what changed. To force the server hook to run on every navigation to a route group:

```ts
// src/routes/(app)/+layout.server.ts
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async ({ locals }) => {
  // Even if "empty", presence of this file makes SvelteKit
  // call the server for layout data, which runs hooks.server.ts.
  return { user: locals.user };
};
```

A file with `+layout.svelte` but no `+layout.server.ts` means client-side navs between subroutes won't hit the server hook. This is a common silent auth bypass on SPA-style navigation. Flag when a protected layout has UI but no server load.

Forcing revalidation after login/logout: call `invalidateAll()` after the redirect/action returns.

## Auth in form actions

**Re-check `locals.user` inside every action**, regardless of what the layout did:

```ts
export const actions: Actions = {
  delete: async ({ locals, request }) => {
    if (!locals.user) {
      return fail(401, { message: 'Unauthorized' });
    }
    const form = await request.formData();
    const id = form.get('id');
    // verify ownership too
    const item = await db.item.findUnique({ where: { id: String(id) } });
    if (!item || item.userId !== locals.user.id) {
      return fail(403, { message: 'Forbidden' });
    }
    await db.item.delete({ where: { id: String(id) } });
    return { success: true };
  }
};
```

Why: form actions are reachable directly via POST to `?/actionName` regardless of which page renders the form. An attacker can hit the action endpoint directly even if the UI doesn't display the form.

**Authorization** (not just authentication): verify the user owns or may access the resource. Many SvelteKit auth bugs are "I checked the user is logged in, but didn't check they own this item."

## OAuth / external IdP

- **State parameter** generated, stored in a cookie, verified on callback. CSRF protection for the OAuth flow.
- **PKCE** for public clients.
- **Nonce + state** for OpenID Connect.
- **Callback URL** must be exact match in the provider config; redirect-URI confusion is a common attack class.
- **`sameSite: 'lax'`** on the state cookie (not strict — see above).

The `@auth/sveltekit` (Auth.js) package handles much of this. Audit usage rather than the package internals.

## Common bypass patterns

Things to actively look for:

- **Client-side guard only**: `{#if user}<div>Secret</div>{/if}` with no server-side check. The "secret" is in the HTML payload.
- **Conditional fetch on client**: load fetches data with `if (browser && user)` — server still streams the response, and the server load (if any) doesn't gate it.
- **`event.locals.user` set but never used for authorization**: hooks populate it, route never checks.
- **Role check on string match without normalization**: `if (user.role === 'admin')` when the DB has `'ADMIN'` or vice versa.
- **Session lookup that doesn't check expiry**: returns a row, ignores the `expires_at` column.
- **Auth check in `+page.ts` (universal load)** instead of `+page.server.ts`: client runs the check, server still serves the data.
- **Logout that only clears client state**: cookie still valid on the server, attacker with the cookie still authenticated.
- **No re-issuance of session on privilege change**: user gets promoted to admin, old session keeps old privileges cached.
- **CSRF token validation that compares two empty strings as success**: `if (formToken === cookieToken)` where both are `undefined`.

## Locals.user in returned data

If a load function returns `{ user: locals.user }`, the full user object ships to the client. Strip anything sensitive (password hash, internal flags, ID-token strings):

```ts
return {
  user: {
    id: locals.user.id,
    email: locals.user.email,
    name: locals.user.name,
    role: locals.user.role
    // not: passwordHash, internalNotes, refreshToken
  }
};
```

Returning the whole DB row is a common over-share.
