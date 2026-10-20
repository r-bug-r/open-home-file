# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| 0.1.x | Yes |
| Earlier | No earlier release exists |

This is a pre-release, single-user local application. Fixes land on the default branch and in the next 0.1.x release; there are no backports to older 0.1.x releases unless a maintainer says otherwise in the advisory.

## Reporting a vulnerability

Report privately through GitHub security advisories:

1. Open the repository's **Security** tab.
2. Choose **Advisories** and then **Report a vulnerability**.
3. Describe the issue in the advisory form.

Do not open a public issue, discussion, or pull request for a suspected vulnerability. Do not attach a real document; use a generated fixture or a minimal synthetic reproduction.

If GitHub advisories are unavailable to you, open a public issue that says only that you have a security report and asks for a private channel. Do not include details in that issue.

## What to include

- The version (`python -c "import homefile; print(homefile.__version__)"`) and the commit if you built from source.
- Operating system, Python version, and whether OCR was installed.
- The configuration that matters: `HOMEFILE_PROVIDER`, `HOMEFILE_ALLOW_NETWORK`, and any non-default limits. Never include the API key itself.
- A minimal reproduction: commands, a synthetic input file, and the observed result.
- The impact you believe is possible, and what an attacker would need (for example, a malicious PDF, a malicious web page open in the same browser, or write access to the data directory).
- Whether any document content, key material, or export bundle may have been exposed.
- Relevant log output with paths and document text redacted.

## Response targets

These are goals, not contractual promises. This is a volunteer project with a single maintainer.

- Acknowledge a report within 3 business days.
- Give an initial assessment within 10 business days.
- For a confirmed high-severity issue, aim to publish a fix or a documented mitigation within 30 days.
- Credit reporters in the advisory unless they ask not to be named.

If a report is out of scope, the response will explain why and, where possible, point to the component that owns the issue.

## Scope

In scope:

- The local application: the CLI, the loopback HTTP server, and the service layer.
- File upload and import handling, including multipart parsing, filename handling, media-type detection, and the PDF and image inspection limits.
- CSRF protection, same-origin checks, cookie handling, content security policy, and static file serving in the web UI.
- Cryptography: blob sealing and opening, the export container, key generation and storage, and passphrase handling.
- Export behavior, including the fact that exports are plaintext unless a passphrase is supplied.
- Deletion and integrity verification, including whether derived records or blobs survive deletion.
- Path handling under the data directory, and any way to make the application read or write outside it.
- Injection into SQLite queries or into generated HTML.

## Non-goals

The following are not treated as vulnerabilities in this project:

- An attacker who already has read access to your operating system account or your data directory. The master key sits next to the encrypted blobs by design; this protects against casual disk inspection and lost backups, not against a compromised account.
- Physical access to an unlocked machine, or malware running as your user.
- The absence of antivirus or general malware scanning. Inspection rejects active PDF features and enforces size and page limits, but it is not a scanner.
- Denial of service through inputs that exceed documented limits, or through a local process consuming its own CPU and disk. The limits are the mitigation.
- Vulnerabilities in third-party services you explicitly configure (Ollama, an OpenAI-compatible endpoint) or in Tesseract. Report those upstream; this project can still document a workaround.
- Vulnerabilities in dependencies that have no reachable path in this code. Dependabot and `pip-audit` track them.
- Missing features such as multi-user authentication, remote access, or encryption of the SQLite database. These are documented limitations, not defects.
- Social engineering, and reports generated solely by an automated scanner without a demonstrated impact.

## Threat model

The threat model, including assets, trust boundaries, and the controls that are intentionally absent, lives in [docs/threat-model.md](docs/threat-model.md). Read it before reporting so the report can say which boundary was crossed.
