# Secrets Management Security Rules

Hardcoded secrets in source code is one of the most common — and most damaging — security mistakes. Source code ends up in version history, CI logs, container images, and backups; a secret committed once is leaked forever.

**Rules:**

1. Secrets MUST be loaded from environment variables or a secret manager.
2. Secrets MUST NEVER be committed to version control.
3. `.gitignore` MUST exclude secret files (`.env`, `.env.*`, `*.key`, `*.pem`).
4. Secrets MUST be scoped, rotated, and granted with least privilege.

---

## Hardcoded Secrets and Credentials — Critical

**Bad:**

```ts
// DON'T: secrets in source
const AWS_ACCESS_KEY = 'AKIAIOSFODNN7EXAMPLE';
const AWS_SECRET_KEY = 'wJalrXUtnFEMI/K7MDENG';
const JWT_SECRET     = 'my-super-secret-jwt-key';

const config = {
  apiKey:      'abc123-xyz789-secret-key',
  databaseUrl: 'postgres://user:passw0rd@localhost:5432/db',
};
```

**Good:**

```ts
interface AppConfig {
  awsAccessKey:  string;
  awsSecretKey:  string;
  jwtSecret:     string;
  databaseUrl:   string;
}

function loadConfig(): AppConfig {
  const required = [
    'AWS_ACCESS_KEY_ID',
    'AWS_SECRET_ACCESS_KEY',
    'JWT_SECRET',
    'DATABASE_URL',
  ] as const;

  const missing = required.filter((k) => !process.env[k]);
  if (missing.length > 0) {
    throw new Error(`Missing env vars: ${missing.join(', ')}`);
  }

  return {
    awsAccessKey: process.env.AWS_ACCESS_KEY_ID!,
    awsSecretKey: process.env.AWS_SECRET_ACCESS_KEY!,
    jwtSecret:    process.env.JWT_SECRET!,
    databaseUrl:  process.env.DATABASE_URL!,
  };
}

export const config = loadConfig();
```

Fail fast at startup if a required secret is missing — never silently fall back to a default that ships in source.

---

## Loading `.env` Files

### Node 22+ — built-in `--env-file`

Node 22 ships native `.env` loading. Prefer this over a third-party package.

```bash
node --env-file=.env --import tsx src/server.ts
```

For multiple files, pass the flag repeatedly (later values win):

```bash
node --env-file=.env --env-file=.env.local --import tsx src/server.ts
```

Use `--env-file-if-exists=.env.local` to make a file optional:

```bash
node --env-file=.env --env-file-if-exists=.env.local --import tsx src/server.ts
```

In `package.json`:

```json
{
  "scripts": {
    "dev":   "node --env-file=.env --env-file-if-exists=.env.local --import tsx --watch src/server.ts",
    "start": "node --env-file=.env --import tsx src/server.ts"
  }
}
```

### Older Node — `dotenv`

If stuck on Node 18 or 20, use `dotenv` and load it before anything that reads `process.env`:

```ts
import 'dotenv/config';
// ...rest of the app
```

Or run it as a preload:

```bash
node -r dotenv/config --import tsx src/server.ts
```

`.env` is for local development only. Production MUST use the host's env injection (systemd, Kubernetes Secrets, Docker secrets) or a secret manager.

---

## Hardcoded Database Connection Strings — Critical

**Bad:**

```ts
import { Pool } from 'pg';

// DON'T: password in source
const pool = new Pool({
  connectionString: 'postgres://user:P@ssw0rd!@localhost:5432/mydb',
});
```

**Good:**

```ts
import { Pool } from 'pg';

const connectionString = process.env.DATABASE_URL;
if (!connectionString) throw new Error('DATABASE_URL required');

export const pool = new Pool({
  connectionString,
  ssl: process.env.NODE_ENV === 'production' ? { rejectUnauthorized: true } : false,
});
```

---

## Secret Managers

For anything beyond local dev, use a managed secret store. They give you audit logs, rotation, fine-grained IAM, and remove the secret from your deploy pipeline.

### AWS Secrets Manager

```ts
import {
  SecretsManagerClient,
  GetSecretValueCommand,
} from '@aws-sdk/client-secrets-manager';

const client = new SecretsManagerClient({ region: 'eu-west-1' });

export async function getSecret(name: string): Promise<string> {
  const out = await client.send(new GetSecretValueCommand({ SecretId: name }));
  if (!out.SecretString) throw new Error(`Secret ${name} has no SecretString`);
  return out.SecretString;
}

// Cache values in-process; refresh on a schedule, don't fetch per request.
```

### GCP Secret Manager

```ts
import { SecretManagerServiceClient } from '@google-cloud/secret-manager';

const client = new SecretManagerServiceClient();

export async function getSecret(name: string, version = 'latest'): Promise<string> {
  const [resp] = await client.accessSecretVersion({
    name: `projects/${process.env.GCP_PROJECT}/secrets/${name}/versions/${version}`,
  });
  const payload = resp.payload?.data?.toString();
  if (!payload) throw new Error(`Secret ${name} empty`);
  return payload;
}
```

### HashiCorp Vault

```ts
import vault from 'node-vault';

const client = vault({
  endpoint: process.env.VAULT_ADDR,
  token:    process.env.VAULT_TOKEN,
});

export async function getSecret(path: string): Promise<Record<string, unknown>> {
  const result = await client.read(path);
  return result.data;
}
```

Prefer short-lived Vault tokens via AppRole or Kubernetes auth — never long-lived static tokens.

### 1Password (Connect / CLI / SDK)

For developer-facing secrets and machine identities, 1Password's `op` CLI and SDK keep secrets out of `.env` files entirely:

```bash
# Inject secrets at run time without writing them to disk
op run --env-file=.env.op -- node --import tsx src/server.ts
```

`.env.op` contains references like `DATABASE_URL = "op://vault/db/url"` — the real values never touch the filesystem.

---

## Never Commit Secrets

### `.gitignore`

```gitignore
# Local env files
.env
.env.local
.env.*.local
.env.development
.env.production

# Keys and certificates
*.key
*.pem
*.p12
*.pfx
*.crt

# Credential directories
secrets/
credentials/
.aws/
.gcp/
```

Commit a `.env.example` with **dummy** values to document required variables.

### Pre-commit hooks

Run a secret scanner before every commit so leaks never reach `git push`.

Using [`husky`](https://typicode.github.io/husky/) + [`lint-staged`](https://github.com/lint-staged/lint-staged):

```json
// package.json
{
  "scripts": {
    "prepare": "husky"
  },
  "lint-staged": {
    "*": ["npx secretlint"]
  }
}
```

```sh
# .husky/pre-commit
npx lint-staged
npx trufflehog filesystem --no-update --fail .
```

### Repo-wide scanning

Run a scanner in CI on every PR:

```bash
# trufflehog — entropy + verified-secret rules
npx trufflehog git file://. --since-commit HEAD~50 --fail --no-update

# gitleaks — fast pattern-based scanner
npx gitleaks detect --redact --no-banner

# git-secrets — AWS-focused, simple rules
git secrets --scan
```

### If a secret leaks

1. Rotate the credential immediately at the source (AWS, DB, etc.) — rewriting git history does **not** revoke a key.
2. Invalidate any sessions/tokens minted with the leaked value.
3. Audit access logs for misuse during the exposure window.
4. Only after rotation, scrub history with `git filter-repo` or BFG — and force-push knowing forks may still have it.

---

## Rotation, Scoping, and Least Privilege

- **Rotation**: rotate on a schedule (90 days for most secrets, 24h–7d for highly sensitive ones) and immediately on suspected leak or staff departure. Use the secret manager's built-in rotation where possible.
- **Per-environment secrets**: dev, staging, and production MUST have separate values. A staging breach must not compromise production.
- **Scoping**: grant each secret the minimum permissions it needs. A read-only DB user for a reporting service, not the admin role.
- **Audit logging**: enable access logging on the secret manager. Alert on unusual read patterns (volume spikes, new principals, off-hours access).
- **No long-lived static keys**: prefer workload identity (IAM Roles for Service Accounts, GKE Workload Identity, Vault dynamic credentials) over static API keys.
- **Don't pass secrets via CLI args**: they show up in `ps`, shell history, and process accounting. Use env vars or files with `0o600` permissions.

---

## Anti-Patterns

| Anti-pattern | Why it fails | Fix |
| --- | --- | --- |
| `const SECRET = process.env.X \|\| 'dev-default'` | "Dev default" ships to prod if env var is missing | Throw on missing required vars |
| Reading a secret on every request | Rate-limit hits on the secret manager; slow path | Cache in-process with TTL; refresh on schedule |
| Committing `.env.production` "temporarily" | Git history is permanent; key is now leaked | Use a secret manager; rotate immediately if committed |
| Same JWT secret across envs | One env's breach compromises all | Per-environment values |
| Logging the config object at startup | Secrets land in log aggregation | Log key names only, never values — see [logging.md](./logging.md) |

---

## CWE References

- **CWE-798**: Use of Hard-coded Credentials
- **CWE-312**: Cleartext Storage of Sensitive Information
- **CWE-532**: Insertion of Sensitive Information into Log File
- **CWE-522**: Insufficiently Protected Credentials
- **CWE-359**: Exposure of Private Personal Information
