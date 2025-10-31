# Threat model

This is an implementation-level threat model for the code in `src/homefile/`.
It describes what the code does today, not what a future version might do. It
is not a formal audit and it does not assign CVSS scores.

## 1. Scope and method

In scope: the CLI, the loopback web UI, the import and extraction pipeline,
SQLite and the encrypted blob store, the provider boundary, export, and
deletion.

Out of scope: the security of the operating system, the Python interpreter,
`cryptography`, `pypdf`, Pillow, Tesseract, and the user's browser. The model
assumes a single-user machine where the account running `homefile` is trusted
and other local accounts are not necessarily trusted.

Method: for each asset and adversary, list the threat, the control that exists
in code (file and function), and what remains. A control is only listed if it
is actually implemented; intent in comments is not a control.

## 2. Assets

| Asset | Where it lives | Why it matters |
|---|---|---|
| Original documents | `blobs/<sha256>.hbf`, AES-256-GCM sealed | Receipts, contracts, and images can contain names, addresses, account numbers, and signatures |
| Extracted text | `pages.text` in `homefile.sqlite3`, plaintext | Same sensitive content as the originals, plus searchable form |
| Structured fields | `fields`, `field_history` in SQLite | Vendor, amount, serial, dates, account labels |
| Reminders | `reminders` in SQLite | Reveals deadlines and therefore life events |
| Library key | `key.bin` in the data directory | Decrypts every blob |
| Export bundles | `exports/` inside the data directory | Copies of metadata and originals, encrypted only if the caller asks |
| Provider credentials | environment variable named by `Settings.cloud_api_key_env` | Billable access to a cloud endpoint |
| Deletion evidence | `deletion_log` | Shows what was removed and whether verification passed |
| Import ledger | `imports`, `ledger` | History of what was imported and which provider calls happened |

The SQLite database and the blobs are separate files in one directory. The
database is not encrypted. This is the largest at-rest gap and is revisited in
T11.

## 3. Adversaries

- **Local malware or another local account.** Can read the data directory if
  filesystem permissions allow, can read process environment variables, can
  call the CLI, and can connect to the loopback port.
- **Network attacker.** Can reach the machine only if the server is bound to a
  non-loopback address or proxied. Can also attempt DNS rebinding against a
  browser on the same machine.
- **Malicious imported file.** A PDF, PNG, or JPEG crafted to exploit a parser,
  exhaust memory, inject instructions into extracted text, or smuggle active
  content.
- **Malicious website.** Runs in the user's browser and attempts cross-site
  requests to `127.0.0.1:8765`.
- **Curious or compromised cloud provider.** Sees any prompt sent when the
  operator enables the cloud provider.
- **Careless operator.** Enables network access, sets a zero or huge cost cap,
  exports plaintext bundles, or copies the data directory without the key.

## 4. Trust boundaries

1. Browser to `ThreadingHTTPServer`: every header, cookie, query string, and
   multipart part is untrusted.
2. Uploaded bytes to `inspect`, `pypdf`, Pillow, and Tesseract: the file is
   untrusted even after the magic-number check.
3. `Library` to the provider: document text leaves the process only here.
4. `Library` to SQLite and the filesystem: field values and filenames are
   untrusted data even though they came from a local import.
5. `Library` to the rendered page: stored text is untrusted when it reaches
   HTML.
6. Data directory to the outside world: exports and backups are copies that
   the application no longer controls.

