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

## 5. Threats and controls

| # | Threat | Current control in code | Residual risk |
|---|---|---|---|
| T1 | A PDF contains JavaScript, launch actions, embedded files, XFA, or auto-submit actions | `inspect._reject_active_pdf` scans the raw bytes for `/JavaScript`, `/JS`, `/Launch`, `/EmbeddedFile`, `/RichMedia`, `/XFA`, `/OpenAction`, `/AA`, `/SubmitForm`, `/ImportData`, `/GoToR`, `/Sound`, `/Movie`; encrypted PDFs are rejected outright | A token scan is not a parser. Names can be split across objects, hidden in compressed object streams, hex-encoded, or expressed through a feature not on the list. `pypdf` still parses the file with no sandbox |
| T2 | A PDF or image is a decompression bomb or otherwise exhausts CPU or memory | `inspect.inspect_bytes` caps the file at `max_file_bytes` (25 MiB default), `max_pages` at 200, and images at 40,000,000 pixels, 20,000 px per side, and at least 8 px per side. `extract` truncates each page to `max_page_chars` (200,000) | There is no uncompressed-size limit for PDF streams; `pypdf` may inflate them before any page cap applies. Embedded images extracted from a PDF for OCR are not subject to the 40 M pixel check in `inspect` |
| T3 | An oversized or empty file is imported | `inspect.inspect_bytes` rejects empty files and files above the configured cap; `web/server.py` caps the request body at 20 × `max_file_bytes` + 1 MiB (about 501 MiB by default) and each part is re-checked on import; per-page text is truncated with a warning | A request may carry up to 20 maximum-size files, so the server can be asked to parse hundreds of megabytes. A file below the size cap can still contain 200 pages of dense text and consume parsing time |
| T4 | An upload filename traverses directories or injects headers | `inspect.safe_filename` takes the basename, strips control characters, collapses whitespace, and caps at 200 characters; `parse_multipart` also applies `Path(filename).name`; `BlobStore.path_for` accepts only a 64-character hex hash; the static route uses an explicit allowlist; `Content-Disposition` uses `quote` | A crafted filename can still be confusing in the UI even after sanitisation. The export zip stores the sanitised basename, so two documents with the same basename collide inside one export only if they are the same document |
| T5 | Document text, a filename, a field value, or an error message injects HTML or script into a rendered page | `web/render.esc` escapes values in `pages.py` and `render.py`; `render.highlight` escapes text before wrapping the cited span in `<mark>`; `Handler._send` sets `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and a CSP that forbids inline script and style | Templates are f-strings. Any new interpolation that forgets `esc` is an injection. There is no template engine enforcing escaping. The CSP allows self-hosted script, so a compromised `app.js` would execute |
| T6 | A malicious website performs a state-changing request against the loopback server | Every POST requires a per-process token in the form and in the `homefile_csrf` cookie, compared with `hmac.compare_digest`; the cookie is `HttpOnly; SameSite=Strict`; `_same_origin` checks `Origin` and `Sec-Fetch-Site`; destructive actions require typing `DELETE` | The token is not authentication. Any local process can fetch a page, read the token, and submit. `Origin: null` is accepted for non-browser clients. There is no `Host` header check, so DNS rebinding is mitigated mainly by loopback binding, not by validation |
| T7 | A remote attacker reaches the web UI | `web/server.py:serve` refuses any host other than `127.0.0.1`, `localhost`, or `::1`; the default is `127.0.0.1:8765` | If the user fronts the server with a reverse proxy or an SSH tunnel, the traffic has no TLS and no authentication. Other local accounts and processes can reach the port. Binding `localhost` may resolve to both loopback families depending on the platform |
| T8 | Malware or another local user reads the library | Blobs are AES-256-GCM encrypted; `crypto.load_or_create_key` writes `key.bin` with mode 0600 on POSIX; `store.BlobStore.put` writes a 0600 temporary file and fsyncs before rename | `key.bin` is stored next to the ciphertext. Anyone who can read the whole data directory can decrypt every blob. On Windows `os.chmod` only toggles the read-only bit; protection depends on the profile ACL. The SQLite database is plaintext regardless |
| T9 | The key is lost, stolen, or silently replaced | The key is 32 random bytes and is never logged; a missing key is regenerated only when `load_or_create_key` creates a new file | There is no key rotation, no re-encryption, no KMS, and no passphrase wrap for the library key. Replacing `key.bin` makes existing blobs fail authentication. Copying `key.bin` with the blobs defeats at-rest encryption |
| T10 | An attacker swaps or corrupts a blob | `store.BlobStore.put` and `get` verify SHA-256; `crypto.seal` and `open_sealed` bind the hash as associated data; `verify_integrity` decrypts and re-hashes every blob and reports orphans | An attacker with write access to the data directory can replace both the blob and the database row. Verification proves integrity against the recorded hash, not authenticity of the database |
| T11 | Extracted text, fields, reminders, and the FTS index are read from SQLite | The database uses `foreign_keys=ON`, `journal_mode=WAL`, `synchronous=FULL`, and `trusted_schema=OFF`; access is through bound parameters | These are integrity and correctness settings, not encryption. `pages.text`, the FTS shadow tables, `fields`, and `reminders` are plaintext. WAL and SHM files can contain recent plaintext. There is no SQLCipher, no field-level encryption, and no application-level encryption of the database |
| T12 | A deleted document's text remains searchable | `Library.delete_document` deletes `documents`, `pages`, `fields`, `field_history`, and `reminders` rows, unlinks the blob and matching exports, and relies on the `pages_ad` trigger to remove FTS entries; it then runs count queries and counts the deleted pages' own `pages_fts` rows by `rowid`; `deletion_log` records `removed` and `remaining` | SQLite does not securely erase pages, and WAL frames may retain text until checkpoint or vacuum. Filesystem snapshots, backups, and SSD wear levelling can retain the blob. The FTS check counts rows by page id, not byte-level removal. Failed imports with a null `doc_id` are not removed by document deletion |
| T13 | An export bundle leaks more than intended | `Library.export_document` writes `metadata.json` and `original/<filename>` into a zip under `exports/`; `encrypt=True` wraps the zip in `HFE1` using scrypt (N=2^14, r=8, p=1) and AES-256-GCM; the passphrase is supplied by the caller | The default export is a plaintext zip containing the original document and its metadata. A weak passphrase is not rejected. Exports live inside the data directory, so they are included in backups and are readable by anyone with data-directory access. There is no expiry or automatic cleanup |
| T14 | Document text is sent to a remote provider without intent | `providers.build_provider` returns `FakeProvider` for `provider=fake`; any other provider requires `HOMEFILE_ALLOW_NETWORK=1`; `cloud` also requires a base URL, model, both per-1k prices, non-zero per-run and daily cost caps, and an API key; `ProviderGuard` enforces request, token, and cost caps and writes a ledger row per attempt | `HOMEFILE_OLLAMA_URL` can point at a remote host while still being treated as "local"; the code does not enforce that the URL is loopback. Cloud pricing is operator-supplied, so cost estimates can be wrong. The provider sees up to 6000 characters of extracted text per import and any configured API key. There is no redaction, no field allowlist, and no OS-level egress block |
| T15 | A document contains prompt injection aimed at the model | `Library._model_candidates` sends only `MODEL_TEXT_LIMIT` (6000) characters; `validate_extraction_payload` accepts only an allowed `doc_type` and known field names with non-empty values and quotes; suggestions are added only for field names deterministic parsing did not produce; a quote must be locatable in the cited page; confidence is capped at 0.6; the model's `doc_type` is validated and then ignored | A genuine sentence in the document can still be chosen as a misleading field value, and the quote check only proves the text exists, not that it means what the model claims. A model can be steered by document text within the 6000-character window. There is no semantic cross-check |
| T16 | Search input injects FTS or SQL syntax | `Library._fts_query` keeps at most eight alphanumeric tokens, including Latin-1 letters, and appends `*`; FTS operators are stripped; structured filters use bound parameters and assemble only literal SQL fragments (`d.id IN (SELECT ...)` per filter); amount bounds are converted to floats and deadline bounds are compared as ISO strings | The FTS query is still user-controlled within the token grammar. Very broad prefixes can be expensive. There is no query timeout |
| T17 | Repeated imports or large requests cause denial of service | The web body is capped at 20 × `max_file_bytes` + 1 MiB; an import request accepts at most 20 files; file, page, pixel, and page-character caps apply; SQLite uses a 15-second busy timeout | There is no rate limit, no per-IP limit, and no request queue. A local process or a same-origin page can submit imports repeatedly. Parsing is CPU-bound and runs in request threads |
| T18 | Provider credentials leak into logs or the database | The API key is read from the environment at call time by `providers._CloudProvider`; the ledger schema has no prompt, key, or response columns; error classes are recorded, not raw payloads | The key is visible to any process that can read the environment of the `homefile` process. Python strings are not zeroised. A misconfigured provider URL could send the key to an unintended host |
| T19 | A malicious file exploits a dependency | Dependencies are pinned by lower bounds in `pyproject.toml`; `pypdf`, Pillow, and Tesseract are invoked only on files that passed magic-number and size checks | There is no sandbox, no antivirus, no subprocess isolation, and no capability drop. A parser vulnerability is exploitable as the user running `homefile`. The project does not ship a vulnerability scanner |

## 6. What is not defended

- **No antivirus or content disarm.** A PDF that passes the token scan is
  parsed. There is no ClamAV integration, no re-rendering to a safe format, and
  no macro or script execution sandbox.
- **No authentication or user accounts.** The web UI trusts any client that can
  reach the loopback port and present the CSRF token. The token is a
  request-forgery control, not a login.
- **No TLS.** Loopback traffic is plain HTTP. If the port is proxied, the proxy
  must supply TLS and access control.
- **No encryption of the database.** Extracted text, fields, reminders, and the
  FTS index are readable by anyone who can read `homefile.sqlite3`.
- **No protection from local malware.** Malware running as the same user can
  read `key.bin`, the database, and the environment, or call the service
  directly.
- **No secure deletion.** Deleting a document removes rows and unlinks files;
  it does not overwrite storage, WAL, snapshots, or backups.
- **No key management.** No rotation, escrow, hardware backing, or passphrase
  protection for the library key.
- **No network egress policy.** `HOMEFILE_ALLOW_NETWORK` gates provider
  construction in the application; it does not stop other code on the machine
  from using the network, and it does not verify that an Ollama URL is local.
- **No rate limiting or resource quotas across requests.** Only per-file and
  per-request caps exist.
- **No protection against a malicious operator.** The person running the
  command can export plaintext, disable the network guard, or copy the key.
- **No protection against a compromised dependency or interpreter.** The trust
  boundary ends at the Python process.

## 7. Controls worth preserving

- Provider construction fails closed: an unknown provider name or a missing
  prerequisite raises instead of silently using the fake.
- A zero per-run or daily cost cap refuses every paid call.
- Model output is always a draft. It never becomes a field without a locatable
  quote and a citation range that fits the stored page text.
- Every correction keeps `original_value` and appends `field_history`.
- A reminder is only actionable after `confirm_reminder`; `due_reminders`
  filters to `confirmed`.
- Deletion raises `DeletionError` and records `verified=0` rather than
  reporting success when a row, blob, or FTS probe remains.
- The web server refuses non-loopback bind addresses instead of warning.

## 8. Residual-risk summary

The design assumes a trusted local account. Against that account, at-rest
encryption of blobs and the CSRF token provide little protection. The
meaningful controls are: parser input caps, a byte-token active-content scan,
strict escaping and a restrictive CSP, loopback-only binding, bound SQL
parameters, a citation check on model output, opt-in network access with hard
caps, and verified deletion that reports failure. The largest accepted gaps
are plaintext extracted text in SQLite, the key stored beside the ciphertext,
the absence of a parser sandbox, and the default plaintext export.
