# Svelte 5 runes reference

## Contents
- The four core runes
- The `$derived` vs `$effect` rule
- `$state` mutation and the Proxy
- `$state.raw` and when to use it
- `$props` and `$bindable`
- Reactive logic outside components (`.svelte.ts` files)
- Common mistakes
- Legacy syntax checklist

## The four core runes

```svelte
<script>
  // Reactive state
  let count = $state(0);

  // Computed value, automatically tracks dependencies
  let double = $derived(count * 2);

  // Side effect, runs when dependencies change
  $effect(() => {
    document.title = `Count: ${count}`;
  });

  // Component props
  let { initial = 0 }: { initial?: number } = $props();
</script>
```

Two-way bindable:

```svelte
<script>
  let { value = $bindable() }: { value?: string } = $props();
</script>
```

## The rule: `$derived` for values, `$effect` for side effects

**The single most common Svelte 5 bug.** Treat this as the #1 thing to look for in any Svelte 5 review.

```svelte
<!-- ❌ Anti-pattern: using $effect to compute a value -->
<script>
  let count = $state(0);
  let double = $state(0);
  $effect(() => { double = count * 2; });
</script>

<!-- ✅ Correct: $derived computes from state -->
<script>
  let count = $state(0);
  let double = $derived(count * 2);
</script>
```

The wrong version causes:
- An extra render cycle (state changes, effect runs, state changes again).
- Stale values during the render between the two changes.
- Easy infinite loops if the effect's logic touches its own dependency.

**Test**: if a question "am I computing a value or doing something with side effects?" answers "computing a value," it's `$derived`. Syncing two state values is always `$derived`.

`$derived.by(() => {...})` exists for derivations needing a function body (more than a single expression).

## `$state` mutation and the Proxy

`$state` returns a Proxy. Mutations on the proxy trigger reactivity:

```svelte
<script>
  let cart = $state({ items: [], total: 0 });
  function add(item) {
    cart.items.push(item);  // ✅ tracked
    cart.total += item.price;  // ✅ tracked
  }
</script>
```

**Destructuring breaks reactivity**:

```svelte
<script>
  let user = $state({ name: 'Alice', age: 30 });
  let { name } = user;     // ❌ snapshot, not reactive
  // ...
  user.name = 'Bob';        // `name` still 'Alice'
</script>
```

Workarounds:
- Access the property directly: `user.name` everywhere.
- Use a getter function: `const getName = () => user.name`.
- Use `$derived`: `let name = $derived(user.name)`.

**Passing reactive values to other modules** loses reactivity if the receiving code expects a value rather than a function:

```ts
// ❌ Captured at call time, not reactive
trackEvent('user_loaded', { userId: user.id });

// ✅ Pass a getter when the consumer expects it
trackEvent('user_loaded', { userId: () => user.id });
```

This is a common bug when extracting logic into helpers.

## `$state.raw`

For values that are replaced wholesale rather than mutated, skip the Proxy overhead:

```ts
// ✅ When you'll reassign the whole array
let users = $state.raw(await fetchUsers());
users = await fetchUsers();  // reassignment triggers reactivity

// vs
let users = $state(await fetchUsers());  // wraps every nested object in Proxy
users.push(newUser);  // mutation triggers reactivity, but Proxy cost
```

Rule: `$state.raw` if you only ever reassign; `$state` if you mutate nested properties.

Reviewer finding: large API result arrays / objects wrapped in `$state` and only ever replaced — flag as `$state.raw` candidates. Not a bug, but a perf and clarity win.

## `$effect` rules

- Runs after the DOM updates.
- Does **not** run during SSR.
- Auto-tracks dependencies — anything read inside the effect is a dep.
- Cleanup function returned from the effect runs before next run / on unmount.

```svelte
<script>
  $effect(() => {
    const id = setInterval(() => count++, 1000);
    return () => clearInterval(id);  // cleanup
  });
</script>
```

Findings:

- Effect that subscribes / listens / starts a timer with no cleanup — memory leak.
- Effect that does an `await` and uses the result — the await suspends tracking; deps after the await aren't tracked. Use `$effect.pre` carefully or refactor.
- Effect that updates state it also reads — infinite loop. Svelte will throw "Maximum update depth exceeded."
- `$effect(() => { ... })` for non-reactive setup (e.g. mount-only logic) — fine, but `onMount` is also available and clearer for one-time setup.

`$effect.root` for nested effects with manual lifecycle control — advanced; usually overkill.
`$effect.pre` runs before DOM updates — for measuring layout before paint.

## `$props`

```svelte
<script lang="ts">
  let { name, age = 30, onClick }: {
    name: string;
    age?: number;
    onClick?: (e: MouseEvent) => void;
  } = $props();
</script>
```

Or with `interface`:

```svelte
<script lang="ts">
  interface Props {
    name: string;
    age?: number;
    onClick?: (e: MouseEvent) => void;
  }
  let { name, age = 30, onClick }: Props = $props();
</script>
```

Rest props:

```svelte
<script>
  let { id, ...rest } = $props();
</script>
<input {id} {...rest} />
```

Findings:

- Untyped `$props()` — `data: any`, no IntelliSense, no compile-time checks.
- `$props()` then mutating a prop — props are immutable from the child's perspective; use `$bindable` if mutation is needed.
- Mixing `export let` and `$props()` — pick one (use `$props()` in new code).

## `$bindable`

For two-way binding:

```svelte
<!-- Child -->
<script lang="ts">
  let { value = $bindable() }: { value?: string } = $props();
</script>
<input bind:value />

<!-- Parent -->
<Child bind:value={name} />
```

Use `$bindable` sparingly — most components benefit from a one-way data flow + callback prop pattern (`value={x} onChange={(v) => x = v}`). Reach for `$bindable` mainly for form-control wrappers.

## Reactive logic outside components

`.svelte.ts` and `.svelte.js` files support runes:

```ts
// src/lib/state/counter.svelte.ts
export function createCounter(initial = 0) {
  let count = $state(initial);
  return {
    get value() { return count; },
    increment() { count++; },
    reset() { count = initial; }
  };
}
```

```svelte
<script>
  import { createCounter } from '$lib/state/counter.svelte';
  const counter = createCounter();
</script>
<button onclick={counter.increment}>{counter.value}</button>
```

This is the modern replacement for Svelte stores in most cases. The class-based variant:

```ts
// src/lib/state/cart.svelte.ts
export class Cart {
  items = $state<Item[]>([]);
  total = $derived(this.items.reduce((s, i) => s + i.price, 0));
  add(item: Item) { this.items.push(item); }
}
```

Findings:

- Runes used in a plain `.ts` file (not `.svelte.ts`) — Svelte won't compile the runes; they'll be runtime functions or undefined.
- Class-style state with public mutable arrays — fine in Svelte 5, but consider whether mutation should be encapsulated.
- Stores (`writable`, `readable`) wrapping rune-based state — pick one paradigm.
- Stores used in SSR contexts — module-level stores leak between requests (classic Svelte issue, predates runes; still applies if legacy stores are used).

## SvelteKit-specific changes

SvelteKit 2 introduced runes-compatible state for built-ins:

```ts
// ❌ Legacy
import { page, navigating, updated } from '$app/stores';
$: console.log($page.url);

// ✅ Modern
import { page, navigating, updated } from '$app/state';
console.log(page.url);  // reactive automatically inside components
```

`$app/stores` still works for backward compatibility but is legacy. `$app/state` exposes rune-based equivalents that don't need the `$` prefix.

Findings:

- Mix of `$app/stores` and `$app/state` in the same project — pick one for consistency.
- `$page.data` accessed in places where `page.data` would be cleaner.

## Legacy syntax checklist

In Svelte 5 codebases, flag any of these in new code:

| Legacy | Modern |
|---|---|
| `export let foo` | `let { foo } = $props()` |
| `$: bar = foo * 2` | `let bar = $derived(foo * 2)` |
| `$: { sideEffect() }` | `$effect(() => { sideEffect() })` |
| `on:click={handler}` | `onclick={handler}` |
| `<slot/>` | `{@render children?.()}` + `children: Snippet` in props |
| `<slot name="header"/>` | Named snippet prop |
| `createEventDispatcher` | Callback props (`onClick`) |
| `writable(x)` for component state | `$state(x)` |
| `derived([a, b], ...)` | `$derived(...)` |
| `$app/stores` | `$app/state` |

Svelte 4 codebases (no runes anywhere): don't flag these as bugs — they're correct for Svelte 4. Flag only if migration is in progress and patterns are mixed.

## Common mistakes summary

1. `$effect` for computing values — use `$derived`.
2. Destructuring `$state` — breaks reactivity.
3. `$effect` without cleanup for subscriptions/timers.
4. `$state` on data that's only replaced — use `$state.raw`.
5. Runes in `.ts` files (must be `.svelte.ts`).
6. `$:` in Svelte 5 — silently works in legacy mode but mixes paradigms.
7. `$props()` without types.
8. `$bindable` overuse where callback prop would be cleaner.
9. `{#each items as item}` without `(item.id)` key — DOM recycling bugs.
10. `$inspect` left in committed code (it's a debug tool).
