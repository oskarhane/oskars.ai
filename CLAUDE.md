Default to using Node.js 22 with tsx for TypeScript execution.

- Use `node --import tsx <file>` instead of `ts-node <file>`
- Use `node --test` for testing (Node's built-in test runner)
- Use `npm install` for package management
- Use `npm run <script>` for scripts
- Use `npx <package>` for one-off package execution
- Use `dotenv` or `--env-file=.env` flag (Node 22+) for env loading

## APIs

- Use `node:http` or `express` for HTTP servers
- Use `better-sqlite3` for SQLite
- Use `ioredis` for Redis
- Use `pg` for Postgres
- Use `ws` for WebSockets
- Use `node:fs` for file operations
- Use `execa` for shell commands

## Testing

Use Node's built-in test runner.

```ts#index.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";

test("hello world", () => {
  assert.strictEqual(1, 1);
});
```

Run with: `npm test` or `node --import tsx --test **/*.test.ts`

## Frontend

Use Vite for frontend development with React, CSS, and Tailwind support.

## Running TypeScript

```sh
# run a file
node --import tsx index.ts

# dev with watch mode
node --watch --import tsx index.ts
```
