# Cryptography Security Rules

Cryptography vulnerabilities threaten confidentiality and integrity of sensitive data.

**Rules:**

1. TLS MUST use 1.2+.
2. NEVER use DES, RC4, MD5, or SHA1 for security purposes.
3. Passwords MUST be hashed with Argon2id (preferred) or bcrypt — never `crypto.createHash('sha256')`.
4. Security-critical randomness MUST use `node:crypto` (`randomBytes`, `randomUUID`, `randomInt`).
5. Secret comparison MUST use `crypto.timingSafeEqual` on equal-length `Buffer`s.

---

## Algorithm Selection Guide

Choose the right algorithm for the job — using the wrong primitive (e.g. SHA-256 for passwords) is as dangerous as using a broken one:

| Use Case | Recommended | Avoid | Why |
| --- | --- | --- | --- |
| Symmetric encryption | AES-256-GCM, ChaCha20-Poly1305 | DES, 3DES, AES-ECB, RC4 | ECB reveals patterns; DES/RC4 are broken |
| Password hashing | Argon2id (`argon2`), bcrypt (`bcrypt`), scrypt | MD5, SHA-1, plain SHA-256 | Fast hashes enable brute-force; memory-hard functions resist GPU attacks |
| Message authentication | HMAC-SHA256, Poly1305 | HMAC-MD5, HMAC-SHA1 | MD5/SHA-1 have known collision weaknesses |
| Digital signatures | Ed25519, ECDSA P-256 | RSA-PKCS1v1.5 | PKCS1v1.5 has padding oracle vulnerabilities |
| Key exchange | X25519, ECDH P-256 | Static RSA key transport | Forward secrecy requires ephemeral keys |
| Random generation | `node:crypto` (`randomBytes`, `randomUUID`) | `Math.random` | `Math.random` is a non-cryptographic PRNG |
| TLS | TLS 1.2+ (prefer 1.3) | TLS 1.0, 1.1, SSL | Known attacks (BEAST, POODLE) on older versions |

### Key Size Requirements

| Algorithm | Minimum Key Size         | Recommended      |
| --------- | ------------------------ | ---------------- |
| RSA       | 2048 bits                | 4096 bits        |
| AES       | 128 bits                 | 256 bits         |
| ECDSA     | P-256 (128-bit security) | P-256 or Ed25519 |

---

## Authenticated Encryption — AES-256-GCM

Use AES-256-GCM (or ChaCha20-Poly1305) for symmetric encryption. GCM combines confidentiality and integrity in a single primitive — the auth tag detects tampering. The nonce (IV) MUST be unique per key; with a random 96-bit nonce, ~2^32 messages per key is safe before rotating.

**Bad — unauthenticated CBC, attacker can flip bits undetected:**

```ts
import { createCipheriv, randomBytes } from "node:crypto";

const iv = randomBytes(16);
const cipher = createCipheriv("aes-256-cbc", key, iv);
const ct = Buffer.concat([cipher.update(plaintext), cipher.final()]);
```

**Good — AES-256-GCM with random nonce and auth tag:**

```ts
import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";

export function encrypt(key: Buffer, plaintext: Buffer): Buffer {
    const nonce = randomBytes(12);
    const cipher = createCipheriv("aes-256-gcm", key, nonce);
    const ct = Buffer.concat([cipher.update(plaintext), cipher.final()]);
    const tag = cipher.getAuthTag();
    return Buffer.concat([nonce, tag, ct]);
}

export function decrypt(key: Buffer, payload: Buffer): Buffer {
    const nonce = payload.subarray(0, 12);
    const tag = payload.subarray(12, 28);
    const ct = payload.subarray(28);
    const decipher = createDecipheriv("aes-256-gcm", key, nonce);
    decipher.setAuthTag(tag);
    return Buffer.concat([decipher.update(ct), decipher.final()]);
}
```

### Nonce reuse — Critical

Reusing a nonce with the same key in AES-GCM destroys both confidentiality and authentication. Always generate the nonce fresh with `randomBytes(12)` per encryption.

**Bad:**

```ts
const FIXED_NONCE = Buffer.alloc(12);
const cipher = createCipheriv("aes-256-gcm", key, FIXED_NONCE);
```

**Good:**

```ts
const nonce = randomBytes(12);
const cipher = createCipheriv("aes-256-gcm", key, nonce);
```

### AES-ECB reveals patterns — High

Avoid the `aes-256-ecb` mode entirely. ECB encrypts each block independently, so identical plaintext blocks produce identical ciphertext blocks, revealing structure.

**Bad:**

```ts
const cipher = createCipheriv("aes-256-ecb", key, null);
```

**Good:**

```ts
const nonce = randomBytes(12);
const cipher = createCipheriv("aes-256-gcm", key, nonce);
```

---

## Secure Randomness — High

`Math.random` is a non-cryptographic PRNG — its output is predictable from a small sequence of observations. Use `node:crypto` for any value that must be unguessable: tokens, IDs, salts, nonces.

**Bad:**

```ts
const token = Math.random().toString(36).slice(2);
const id = `${Date.now()}-${Math.random()}`;
```

**Good:**

```ts
import { randomBytes, randomUUID, randomInt } from "node:crypto";

const token = randomBytes(32).toString("base64url");
const id = randomUUID();
const dice = randomInt(1, 7);
```

`randomUUID` produces a v4 UUID using the OS CSPRNG and is the right choice when a UUID is what you actually want; otherwise `randomBytes` with `base64url` encoding gives a shorter, denser token.

---

## Timing-Safe Comparison — Medium

Comparing a secret with `===` or `Buffer.compare` short-circuits on the first differing byte, leaking how many leading bytes matched. Use `crypto.timingSafeEqual` on **equal-length** `Buffer`s. Different lengths must be handled separately — `timingSafeEqual` throws on mismatched lengths.

**Bad:**

```ts
if (providedToken === expectedToken) {
    // authenticated
}
```

**Good:**

```ts
import { timingSafeEqual } from "node:crypto";

function safeEqual(a: string, b: string): boolean {
    const ab = Buffer.from(a, "utf8");
    const bb = Buffer.from(b, "utf8");
    if (ab.length !== bb.length) return false;
    return timingSafeEqual(ab, bb);
}
```

For HMAC verification, recompute the HMAC then compare with `timingSafeEqual`:

```ts
import { createHmac, timingSafeEqual } from "node:crypto";

function verifySig(body: Buffer, secret: string, given: string): boolean {
    const expected = createHmac("sha256", secret).update(body).digest();
    const givenBuf = Buffer.from(given, "hex");
    if (givenBuf.length !== expected.length) return false;
    return timingSafeEqual(expected, givenBuf);
}
```

---

## Password Hashing — High

Passwords MUST be hashed with a memory-hard or otherwise expensive function. Generic hashes like SHA-256 are designed to be fast — GPUs run them billions of times per second, making brute-force trivial. Use Argon2id (preferred) or bcrypt.

**Bad:**

```ts
import { createHash } from "node:crypto";

const hash = createHash("sha256").update(password).digest("hex");
const md5 = createHash("md5").update(password).digest("hex");
```

**Good — Argon2id (preferred):**

```ts
import argon2 from "argon2";

const hash = await argon2.hash(password, {
    type: argon2.argon2id,
    memoryCost: 64 * 1024,
    timeCost: 3,
    parallelism: 4,
});

const ok = await argon2.verify(hash, providedPassword);
```

**Good — bcrypt (simpler API, widely supported):**

```ts
import bcrypt from "bcrypt";

const hash = await bcrypt.hash(password, 12);
const ok = await bcrypt.compare(providedPassword, hash);
```

Both `argon2.verify` and `bcrypt.compare` perform timing-safe comparison internally — do not extract the digest and compare manually.

### Pepper

A server-side pepper (a secret added to every password before hashing, stored separately from the database) raises the cost of an offline attack after a DB-only breach. Combine the password with the pepper via HMAC, then feed the result into Argon2id.

---

## Key Derivation — High

Derive encryption keys from passwords or low-entropy inputs with `scrypt` or `pbkdf2`. Don't use these to **store** passwords (use Argon2id / bcrypt) — KDFs are for deriving keys used elsewhere.

**Bad:**

```ts
import { createHash } from "node:crypto";
const key = createHash("sha256").update(password).digest();
```

**Good — scrypt (recommended for new code):**

```ts
import { scrypt, randomBytes } from "node:crypto";
import { promisify } from "node:util";

const scryptAsync = promisify(scrypt) as (
    password: string | Buffer,
    salt: string | Buffer,
    keylen: number,
) => Promise<Buffer>;

const salt = randomBytes(16);
const key = await scryptAsync(password, salt, 32);
```

**Good — pbkdf2 (when FIPS compliance is required):**

```ts
import { pbkdf2, randomBytes } from "node:crypto";
import { promisify } from "node:util";

const pbkdf2Async = promisify(pbkdf2);
const salt = randomBytes(16);
const key = await pbkdf2Async(password, salt, 600_000, 32, "sha512");
```

OWASP currently recommends ≥600,000 iterations for PBKDF2-HMAC-SHA256 (≥210,000 for PBKDF2-HMAC-SHA512). Store the salt and iteration count alongside the derived key so the parameters can be raised in future without breaking existing keys.

---

## TLS Configuration — High

`https.createServer` and `tls.createSecureContext` accept a `SecureContextOptions` object. Always set `minVersion: 'TLSv1.2'` (TLS 1.0 and 1.1 are deprecated and have known attacks) and prefer modern cipher suites.

**Bad:**

```ts
import https from "node:https";

const server = https.createServer({
    key,
    cert,
    minVersion: "TLSv1",
});
```

**Good:**

```ts
import https from "node:https";

const server = https.createServer({
    key,
    cert,
    minVersion: "TLSv1.2",
    ciphers: [
        "TLS_AES_128_GCM_SHA256",
        "TLS_AES_256_GCM_SHA384",
        "TLS_CHACHA20_POLY1305_SHA256",
        "ECDHE-ECDSA-AES128-GCM-SHA256",
        "ECDHE-RSA-AES128-GCM-SHA256",
        "ECDHE-ECDSA-AES256-GCM-SHA384",
        "ECDHE-RSA-AES256-GCM-SHA384",
    ].join(":"),
    honorCipherOrder: true,
});
```

### Outbound TLS — never disable verification

Disabling certificate verification on the client is equivalent to having no TLS at all — anyone on the path can impersonate the server.

**Bad:**

```ts
process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0";

const agent = new https.Agent({ rejectUnauthorized: false });
```

**Good:**

```ts
const agent = new https.Agent({
    rejectUnauthorized: true,
    minVersion: "TLSv1.2",
});
```

If you genuinely need to trust a private CA, load it explicitly with `ca: fs.readFileSync('private-ca.pem')` instead of disabling verification.

---

## Weak Algorithms

### MD5 — High

MD5 is collision-prone and unsuitable for any security context.

**Bad:**

```ts
import { createHash } from "node:crypto";
const digest = createHash("md5").update(data).digest("hex");
```

**Good:**

```ts
import { createHash } from "node:crypto";
const digest = createHash("sha256").update(data).digest("hex");
```

### SHA-1 — Medium

SHA-1 is broken for collision resistance and should not be used for new signatures or HMACs.

**Bad:**

```ts
import { createHash } from "node:crypto";
const digest = createHash("sha1").update(data).digest("hex");
```

**Good:**

```ts
const digest = createHash("sha256").update(data).digest("hex");
```

### Weak HMAC — Medium

**Bad:**

```ts
import { createHmac } from "node:crypto";
const mac = createHmac("md5", key).update(data).digest();
```

**Good:**

```ts
const mac = createHmac("sha256", key).update(data).digest();
```

### DES / 3DES / RC4 — High

These are cryptographically broken; Node's OpenSSL build may still expose them. Never instantiate them.

**Bad:**

```ts
const cipher = createCipheriv("des-cbc", key, iv);
const cipher2 = createCipheriv("rc4", key, null);
```

**Good:**

```ts
const cipher = createCipheriv("aes-256-gcm", key, randomBytes(12));
```

---

## RSA Key Size — Medium

RSA keys smaller than 2048 bits are insufficient against modern factoring.

**Bad:**

```ts
import { generateKeyPair } from "node:crypto";
import { promisify } from "node:util";

const generateKeyPairAsync = promisify(generateKeyPair);
const { publicKey, privateKey } = await generateKeyPairAsync("rsa", {
    modulusLength: 1024,
});
```

**Good:**

```ts
const { publicKey, privateKey } = await generateKeyPairAsync("rsa", {
    modulusLength: 4096,
});
```

For new code, prefer Ed25519 — shorter keys, faster operations, no padding-oracle footguns:

```ts
const { publicKey, privateKey } = await generateKeyPairAsync("ed25519");
```

---

## Key Storage and Rotation

Keys live outside the source tree — load them from a secret manager (AWS KMS, GCP KMS, HashiCorp Vault) or from environment variables populated by one. Rotate keys periodically; envelope encryption lets you rotate the Key Encryption Key (KEK) without re-encrypting every record.

```ts
import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";

function aesGcmEncrypt(key: Buffer, plaintext: Buffer): Buffer {
    const nonce = randomBytes(12);
    const cipher = createCipheriv("aes-256-gcm", key, nonce);
    const ct = Buffer.concat([cipher.update(plaintext), cipher.final()]);
    return Buffer.concat([nonce, cipher.getAuthTag(), ct]);
}

function aesGcmDecrypt(key: Buffer, payload: Buffer): Buffer {
    const nonce = payload.subarray(0, 12);
    const tag = payload.subarray(12, 28);
    const ct = payload.subarray(28);
    const decipher = createDecipheriv("aes-256-gcm", key, nonce);
    decipher.setAuthTag(tag);
    return Buffer.concat([decipher.update(ct), decipher.final()]);
}

export function envelopeEncrypt(kek: Buffer, plaintext: Buffer) {
    const dek = randomBytes(32);
    const ciphertext = aesGcmEncrypt(dek, plaintext);
    const wrappedDek = aesGcmEncrypt(kek, dek);
    return { wrappedDek, ciphertext };
}

export function envelopeDecrypt(
    kek: Buffer,
    wrappedDek: Buffer,
    ciphertext: Buffer,
): Buffer {
    const dek = aesGcmDecrypt(kek, wrappedDek);
    return aesGcmDecrypt(dek, ciphertext);
}
```

Rotating the KEK then only requires re-encrypting the small wrapped DEKs, not the (potentially large) ciphertext.

---

## CWE References

- **CWE-327**: Use of a Broken or Risky Cryptographic Algorithm
- **CWE-331**: Insufficient Entropy
- **CWE-326**: Inadequate Encryption Strength
- **CWE-295**: Improper Certificate Validation
- **CWE-330**: Use of Insufficiently Random Values
- **CWE-916**: Use of Password Hash With Insufficient Computational Effort
- **CWE-208**: Observable Timing Discrepancy
