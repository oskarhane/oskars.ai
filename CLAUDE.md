Default to using Node.js 22 with tsx for TypeScript execution.

- Use `node --import tsx <file>` instead of `ts-node <file>`
- Use `node --test` for testing (Node's built-in test runner)
- Use `npm install` for package management
- Use `npm run <script>` for scripts
- Use `npx <package>` for one-off package execution
- Use `dotenv` or `--env-file=.env` flag (Node 22+) for env loading
