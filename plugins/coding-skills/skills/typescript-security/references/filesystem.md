# Filesystem Security Rules

Filesystem vulnerabilities can lead to unauthorized file access, data leakage, denial-of-service, and arbitrary file overwrite.

**Rules:**

1. File paths MUST be resolved with `node:path.resolve` and prefix-checked against an allowed root.
2. Symlinks MUST be resolved with `fs.realpath` and re-checked, or refused outright.
3. Zip and tar entries MUST be validated for ZipSlip — every entry path stays under the extraction root.
4. Temporary files MUST be created with `fs.mkdtemp` / `fs.mkdtempSync` — NEVER predictable names in `os.tmpdir()`.
5. File permissions MUST be restrictive: `0o600` for secrets, `0o644` for public-readable, `0o700` for private directories.
6. File uploads MUST enforce size limits, validate content type, and use server-decided filenames.

---

## Path Traversal — High

User-controlled path segments like `../../etc/passwd` escape the intended directory and expose arbitrary files.

**Bad:**

```ts
import { readFile } from "node:fs/promises";
import { join } from "node:path";

app.get("/files/:name", async (req, res) => {
  const full = join("/var/www/public", req.params.name);
  res.send(await readFile(full));
});
```

`join` collapses `..` but does not constrain the result to `/var/www/public`. A request for `..%2F..%2Fetc%2Fpasswd` escapes the root.

**Good:**

```ts
import { readFile, realpath } from "node:fs/promises";
import { resolve, sep } from "node:path";

const ROOT = resolve("/var/www/public");

app.get("/files/:name", async (req, res) => {
  const requested = resolve(ROOT, req.params.name);
  if (requested !== ROOT && !requested.startsWith(ROOT + sep)) {
    return res.status(400).send("invalid path");
  }
  const real = await realpath(requested);
  if (real !== ROOT && !real.startsWith(ROOT + sep)) {
    return res.status(400).send("invalid path");
  }
  res.send(await readFile(real));
});
```

Append `sep` to the prefix check so `/var/www/public-secret` does not pass a check for `/var/www/public`. Resolving with `realpath` catches symlinks that escape the root.

For untrusted single-segment filenames, an additional defense is to reject any input containing `..`, `/`, `\`, or NUL bytes before resolving.

---

## Symlink Escape — High

A symlink inside an allowed directory can point outside it. Prefix-checking the unresolved path is not enough.

**Bad:**

```ts
import { readFile } from "node:fs/promises";
import { resolve, sep } from "node:path";

const ROOT = resolve("/srv/uploads");

export async function read(name: string) {
  const full = resolve(ROOT, name);
  if (!full.startsWith(ROOT + sep)) throw new Error("denied");
  return readFile(full);
}
```

If an attacker (or earlier upload) placed a symlink `link -> /etc/passwd` inside `/srv/uploads`, this check passes but the read escapes.

**Good — resolve and re-check:**

```ts
import { readFile, realpath } from "node:fs/promises";
import { resolve, sep } from "node:path";

const ROOT = resolve("/srv/uploads");

export async function read(name: string) {
  const full = resolve(ROOT, name);
  if (!full.startsWith(ROOT + sep)) throw new Error("denied");
  const real = await realpath(full);
  if (real !== ROOT && !real.startsWith(ROOT + sep)) throw new Error("denied");
  return readFile(real);
}
```

**Good — refuse symlinks entirely:**

```ts
import { lstat, readFile } from "node:fs/promises";

const st = await lstat(full);
if (st.isSymbolicLink()) throw new Error("symlinks not allowed");
return readFile(full);
```

Refusing symlinks is simpler and safer when the directory has no legitimate reason to contain them (uploads, caches, untrusted extractions).

---

## Zip Slip — High

Archive entry names like `../../etc/cron.d/evil` write outside the extraction directory.

**Bad:**

```ts
import { createWriteStream } from "node:fs";
import { join } from "node:path";
import unzipper from "unzipper";

for await (const entry of zip) {
  const out = join(dest, entry.path);
  entry.pipe(createWriteStream(out));
}
```

**Good:**

```ts
import { createWriteStream } from "node:fs";
import { mkdir } from "node:fs/promises";
import { dirname, resolve, sep } from "node:path";
import unzipper from "unzipper";

const root = resolve(dest);

for await (const entry of zip) {
  const target = resolve(root, entry.path);
  if (target !== root && !target.startsWith(root + sep)) {
    entry.autodrain();
    throw new Error(`zip slip blocked: ${entry.path}`);
  }
  if (entry.type === "Directory") {
    await mkdir(target, { recursive: true, mode: 0o700 });
    continue;
  }
  await mkdir(dirname(target), { recursive: true, mode: 0o700 });
  entry.pipe(createWriteStream(target, { mode: 0o600 }));
}
```

Reject absolute paths, leading `..`, and symlink entries. The same rules apply to tar via `tar` package — set `strict: true` and validate every entry.

Also enforce a maximum total decompressed size to defend against decompression bombs:

```ts
const MAX_BYTES = 100 * 1024 * 1024;
let written = 0;
entry.on("data", (chunk: Buffer) => {
  written += chunk.length;
  if (written > MAX_BYTES) entry.destroy(new Error("archive too large"));
});
```

---

## Insecure Temporary Files — Medium

Predictable paths in `/tmp` allow attackers (or other processes on shared hosts) to pre-create files, race the open, or leak data through `0o644` defaults.

**Bad:**

```ts
import { writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const file = join(tmpdir(), `upload-${Date.now()}.bin`);
await writeFile(file, data);
```

`Date.now()` is predictable. The file lands with default umask permissions, often world-readable.

**Good — `mkdtemp` for a private directory:**

```ts
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const dir = await mkdtemp(join(tmpdir(), "upload-"));
try {
  const file = join(dir, "data.bin");
  await writeFile(file, data, { mode: 0o600 });
  // use file
} finally {
  await rm(dir, { recursive: true, force: true });
}
```

`mkdtemp` returns a uniquely-named directory created with `0o700`. Writing inside it with explicit `0o600` keeps the contents private even if the umask is loose.

For one-off file creation without a wrapping directory, use `fs.open` with `O_CREAT | O_EXCL` to refuse to clobber an existing path:

```ts
import { open } from "node:fs/promises";
import { randomBytes } from "node:crypto";

const name = `app-${randomBytes(16).toString("hex")}`;
const fh = await open(join(tmpdir(), name), "wx", 0o600);
```

---

## Insecure File Permissions — Medium

Files written with `0o644`/`0o666` defaults expose secrets to every local user.

**Bad:**

```ts
import { writeFile } from "node:fs/promises";

await writeFile("/etc/myapp/credentials.json", JSON.stringify(secrets));
```

World-readable. Anyone on the box can `cat` it.

**Good:**

```ts
import { writeFile, chmod } from "node:fs/promises";

await writeFile("/etc/myapp/credentials.json", JSON.stringify(secrets), { mode: 0o600 });
// or after the fact:
await chmod("/etc/myapp/credentials.json", 0o600);
```

Guidelines:

- `0o600` — secrets, private keys, session stores, anything that must stay owner-only.
- `0o644` — files served publicly or read by other users on purpose (static assets).
- `0o640` — append-only logs readable by a log-shipper group.
- `0o700` — private directories (sessions, key material, user-scoped caches).
- `0o755` — public directories (static asset roots, public document trees).

Avoid `0o666`, `0o777` — there is almost no legitimate use case.

---

## Insecure Directory Creation — Low

Directories created with `0o777` allow any local process to plant files in them.

**Bad:**

```ts
import { mkdir } from "node:fs/promises";

await mkdir("/var/myapp/cache", { recursive: true, mode: 0o777 });
```

**Good:**

```ts
await mkdir("/var/myapp/cache", { recursive: true, mode: 0o750 });
```

Note: `mkdir`'s `mode` is masked by the process umask. Either set the umask explicitly at startup or `chmod` the directory after creation when the exact mode matters.

---

## File Uploads — High

Unchecked uploads enable arbitrary file overwrite, content-sniffing XSS, decompression bombs, and disk-full DoS.

**Bad:**

```ts
import express from "node:http";
import multer from "multer";

const upload = multer({ dest: "/uploads" });

app.post("/upload", upload.single("file"), (req, res) => {
  // file ends up at /uploads/<random>, but no size limit, no type check,
  // and the original filename may be echoed back to other users
  res.json({ name: req.file?.originalname });
});
```

**Good:**

```ts
import multer from "multer";
import { randomBytes } from "node:crypto";
import { extname } from "node:path";

const ALLOWED_MIME = new Set(["image/png", "image/jpeg", "image/webp"]);
const ALLOWED_EXT = new Set([".png", ".jpg", ".jpeg", ".webp"]);

const upload = multer({
  storage: multer.diskStorage({
    destination: "/var/app/uploads",
    filename: (_req, file, cb) => {
      const ext = extname(file.originalname).toLowerCase();
      if (!ALLOWED_EXT.has(ext)) return cb(new Error("bad extension"), "");
      cb(null, `${randomBytes(16).toString("hex")}${ext}`);
    },
  }),
  limits: {
    fileSize: 5 * 1024 * 1024,
    files: 1,
    fields: 10,
    fieldSize: 1024,
  },
  fileFilter: (_req, file, cb) => {
    if (!ALLOWED_MIME.has(file.mimetype)) return cb(new Error("bad type"));
    cb(null, true);
  },
});
```

Additional defenses:

- Verify the file's actual content type by sniffing magic bytes (`file-type` package) — clients can lie about `Content-Type`.
- Strip metadata for images that will be re-served (`sharp`).
- Store uploads outside the web root and serve via a handler that re-checks ownership.
- Set `Content-Disposition: attachment` and `X-Content-Type-Options: nosniff` on download responses.
- Never echo the user-supplied filename into HTML without escaping.

---

## Tainted File Read — High

Reading files based on unvalidated input without any allowlist.

**Bad:**

```ts
import { readFile } from "node:fs/promises";

export function read(name: string) {
  return readFile(name);
}
```

**Good:**

```ts
import { readFile, realpath } from "node:fs/promises";
import { resolve, sep } from "node:path";

const ROOT = resolve("/var/www/public");

export async function read(name: string) {
  if (name.includes("\0")) throw new Error("invalid name");
  const full = resolve(ROOT, name);
  if (full !== ROOT && !full.startsWith(ROOT + sep)) throw new Error("denied");
  const real = await realpath(full);
  if (real !== ROOT && !real.startsWith(ROOT + sep)) throw new Error("denied");
  return readFile(real);
}
```

Reject NUL bytes — some legacy code paths interpret them as string terminators and bypass extension checks.

---

## File Descriptor Leaks — Low

Forgetting to close file handles leaks descriptors and eventually causes `EMFILE`.

**Bad:**

```ts
import { open } from "node:fs/promises";

const fh = await open("/var/app/data.bin", "r");
const buf = Buffer.alloc(1024);
await fh.read(buf, 0, 1024, 0);
// missing fh.close()
```

**Good:**

```ts
import { open } from "node:fs/promises";

const fh = await open("/var/app/data.bin", "r");
try {
  const buf = Buffer.alloc(1024);
  await fh.read(buf, 0, 1024, 0);
} finally {
  await fh.close();
}
```

Prefer the high-level helpers (`readFile`, `writeFile`, `createReadStream`) which manage descriptors for you. For streams, listen for `error` and `close` events — a stream that errors after partial read still needs cleanup.

---

## CWE References

- **CWE-22**: Path Traversal (Directory Traversal)
- **CWE-59**: Improper Link Resolution Before File Access (Symlink Following)
- **CWE-409**: Improper Handling of Highly Compressed Data (Decompression Bomb)
- **CWE-379**: Creation of Temporary File in Directory with Insecure Permissions
- **CWE-378**: Creation of Temporary File With Insecure Permissions
- **CWE-732**: Incorrect Permission Assignment for Critical Resource
- **CWE-434**: Unrestricted Upload of File with Dangerous Type
- **CWE-775**: Missing Release of File Descriptor or Handle after Effective Lifetime
