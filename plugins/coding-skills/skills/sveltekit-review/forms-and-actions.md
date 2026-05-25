# Forms, actions, and validation reference

## Contents
- Form actions basics
- Server-side validation patterns
- Zod / Valibot / superforms
- CSRF protection
- `use:enhance` and progressive enhancement
- File uploads
- Multi-step forms
- API endpoints (`+server.ts`) vs form actions
- Common findings

## Form actions basics

Form actions live in `+page.server.ts`. They handle `POST` requests to the page.

```ts
// src/routes/contact/+page.server.ts
import type { Actions } from './$types';
import { fail, redirect } from '@sveltejs/kit';

export const actions: Actions = {
  default: async ({ request, locals }) => {
    const data = await request.formData();
    const email = data.get('email');
    // validate, persist, etc.
    return { success: true };
  }
};
```

Multiple named actions for one page:

```ts
export const actions: Actions = {
  create: async (event) => { /* ... */ },
  update: async (event) => { /* ... */ },
  delete: async (event) => { /* ... */ }
};
```

Form submits via `<form method="POST" action="?/create">`.

**Findings**:
- Form action in `+page.ts` (universal) — not allowed by the framework, but flag any attempt.
- Mutations performed inside `load()` instead of an action — wrong abstraction; mutations belong in actions or `+server.ts` POST handlers.
- Action that does `return new Response(...)` instead of an object or `fail()`/`redirect()` — bypasses the framework's typing and `form` prop population.

## Server-side validation (always required)

Never trust the client. Validate every field server-side. Even if client-side validation exists, the action endpoint is directly POST-able.

Manual:

```ts
import { fail } from '@sveltejs/kit';

export const actions: Actions = {
  default: async ({ request }) => {
    const data = await request.formData();
    const email = data.get('email');
    if (typeof email !== 'string' || !email.includes('@') || email.length > 254) {
      return fail(400, { email, missing: !email, invalid: true });
    }
    // ...
  }
};
```

`fail(status, data)` returns to the page as the `form` prop. The original value (`email`) is included so the user doesn't lose their input. Don't return the password back.

## Zod / Valibot

Zod is the most common choice:

```ts
import { z } from 'zod';
import { fail } from '@sveltejs/kit';

const schema = z.object({
  email: z.string().email().max(254),
  name: z.string().trim().min(1).max(100),
  age: z.coerce.number().int().min(13).max(120)
});

export const actions: Actions = {
  default: async ({ request }) => {
    const formData = await request.formData();
    const raw = Object.fromEntries(formData);
    const result = schema.safeParse(raw);
    if (!result.success) {
      return fail(400, {
        values: raw,
        errors: result.error.flatten().fieldErrors
      });
    }
    // result.data is fully typed
  }
};
```

Findings:

- Schema defined inside the action — flag if it's recreated on every request. Define schemas at module level.
- Schema imported from a non-server file but only used server-side — harmless but messy.
- No `.max()` on string fields — open invite for memory-exhaustion DoS (10MB email anyone?).
- `z.string()` without `.trim()` on user-typed fields — whitespace bugs.
- `z.coerce.number()` on a field that should be a string with digits — coercion loses validation precision.

## sveltekit-superforms

Handles a lot of the boilerplate, supports Zod / Valibot / Yup / Arktype / etc:

```ts
// +page.server.ts
import { superValidate } from 'sveltekit-superforms';
import { zod } from 'sveltekit-superforms/adapters';
import { z } from 'zod';
import { fail } from '@sveltejs/kit';

const schema = z.object({
  email: z.string().email(),
  name: z.string().min(1)
});

export const load = async () => {
  const form = await superValidate(zod(schema));
  return { form };
};

export const actions = {
  default: async ({ request }) => {
    const form = await superValidate(request, zod(schema));
    if (!form.valid) return fail(400, { form });
    // form.data is typed
    return { form };
  }
};
```

```svelte
<!-- +page.svelte -->
<script>
  import { superForm } from 'sveltekit-superforms';
  let { data } = $props();
  const { form, errors, enhance } = superForm(data.form);
</script>

<form method="POST" use:enhance>
  <input name="email" bind:value={$form.email} />
  {#if $errors.email}<span>{$errors.email}</span>{/if}
  <button>Submit</button>
</form>
```

Findings specific to superforms:

- Schema defined inside `load` — superforms caches adapters by reference; in-function definition breaks caching.
- `superForm(data.form)` not called — falls back to no client features.
- `taintedMessage` not configured for long forms — users lose data on accidental nav.
- File inputs not configured for `File` type — superforms needs explicit setup.

## CSRF protection

SvelteKit's built-in `kit.csrf.checkOrigin` checks the `Origin` header on form-content-type POST/PUT/PATCH/DELETE requests against the request URL's origin. It blocks the common cross-site form submission attack.

**What it covers**:
- Cross-origin HTML form submits (`application/x-www-form-urlencoded`, `multipart/form-data`, `text/plain`).

**What it does not cover**:
- Same-origin XSS leveraging the user's session (mitigate XSS, not CSRF, for that).
- API consumers expecting JSON — but those typically use tokens / API keys anyway, not session cookies.
- Custom CSRF needs (per-form tokens, double-submit cookie pattern) — implement manually if required.

Configuration:

```js
// svelte.config.js
const config = {
  kit: {
    csrf: {
      checkOrigin: true,
      trustedOrigins: ['https://app.partner.com']
    }
  }
};
```

**Double-submit cookie pattern** (when more is needed):

```ts
// hooks.server.ts — set CSRF token in cookie on first visit
export const handle: Handle = async ({ event, resolve }) => {
  if (!event.cookies.get('csrf')) {
    const token = crypto.randomUUID();
    event.cookies.set('csrf', token, { path: '/', sameSite: 'lax' });
  }
  return resolve(event);
};

// In action
const formToken = (await request.formData()).get('csrf');
const cookieToken = cookies.get('csrf');
if (!formToken || formToken !== cookieToken) {
  return fail(403, { message: 'CSRF mismatch' });
}
```

Findings:

- `checkOrigin: false` without justification.
- Custom CSRF token compared without checking both sides are non-empty.
- Token in URL query string (logged, leaked in Referer headers).
- Same token reused indefinitely (rotate on privilege boundaries).

## `use:enhance` and progressive enhancement

Without `use:enhance`, forms work via standard HTML submission — full page reload. SvelteKit forms are designed to work without JS by default.

With `use:enhance`, the same form gets:
- Client-side submit (no page reload)
- Automatic `form` prop update
- Automatic invalidation of relevant load functions

The default behavior is usually correct. Customize only when needed:

```svelte
<form method="POST" use:enhance={({ formData, cancel }) => {
  // before submit — can mutate formData, cancel
  return async ({ result, update }) => {
    // after submit — result has the action's return value
    await update(); // re-runs load and updates form prop
  };
}}>
```

Findings:

- Form with `onsubmit={handleSubmit}` and `preventDefault()` instead of `use:enhance` — broke progressive enhancement, broke JS-disabled fallback.
- `enhance` callback that does `result = await fetch(...)` manually — defeats the point; should use SvelteKit's `applyAction` if intercepting.
- No `method="POST"` on a form posting data — defaults to GET, data ends up in URL.

## File uploads

```ts
export const actions: Actions = {
  default: async ({ request }) => {
    const data = await request.formData();
    const file = data.get('upload');
    if (!(file instanceof File)) return fail(400, { message: 'No file' });
    if (file.size > 5 * 1024 * 1024) return fail(400, { message: 'Too large' });
    if (!['image/png', 'image/jpeg'].includes(file.type)) {
      return fail(400, { message: 'Wrong type' });
    }
    const buffer = Buffer.from(await file.arrayBuffer());
    // ...
  }
};
```

Findings:

- No size check — denial of service.
- MIME type checked but not verified by file magic bytes — `Content-Type` is client-controlled.
- File extension trusted — strip it; never use user-supplied filenames for storage paths (path traversal).
- Files written to a path constructed from user input — `path.join('uploads', file.name)` lets `../../../etc/passwd` through.
- Image processing on untrusted input without a sandboxed library — historical RCE vectors in image libs.
- Adapter body-size limit not configured — Node adapter default is 512KB; Vercel/Cloudflare differ.

## Multi-form pages

Multiple `<form>` elements with different actions:

```svelte
<form method="POST" action="?/create" use:enhance>...</form>
<form method="POST" action="?/delete" use:enhance>...</form>
```

`page.form` is shared across forms — superforms supports multiple forms via the `id` option, vanilla actions need manual handling.

## `+server.ts` API endpoints

Standalone endpoints accept any HTTP method. The CSRF origin check applies to state-changing methods with form-content-type bodies. For JSON APIs consumed by other origins, design intentionally:

```ts
// src/routes/api/items/+server.ts
import type { RequestHandler } from './$types';
import { json } from '@sveltejs/kit';

export const GET: RequestHandler = async ({ locals }) => {
  if (!locals.user) return new Response('Unauthorized', { status: 401 });
  const items = await db.item.findMany({ where: { userId: locals.user.id } });
  return json(items);
};

export const POST: RequestHandler = async ({ request, locals }) => {
  if (!locals.user) return new Response('Unauthorized', { status: 401 });
  const body = await request.json();
  // validate body, persist
  return json({ ok: true }, { status: 201 });
};
```

Findings:

- POST/PUT/DELETE handler with no auth check — direct attack surface.
- Returning unsanitized errors with stack traces from `+server.ts` — info disclosure.
- No `Content-Type: application/json` on JSON responses (handled by `json()` helper — flag if `new Response(JSON.stringify(...))` is used instead).
- Rate limiting absent on auth endpoints (login, signup, password reset, email change).

## Common findings summary

- Action does not validate input
- Validation only on the client
- `formData.get(...)` value used without `typeof === 'string'` check (it could be `File`)
- No length caps on string inputs
- Mutations in load functions
- `use:enhance` replaced by manual `fetch` losing PE
- CSRF disabled or weakened
- File uploads with no size, type, or filename safety
- Per-action auth check missing despite layout-level check
