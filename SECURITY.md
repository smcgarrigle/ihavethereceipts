# Security Practices

> For AI agent behavior and coding style, see [GEMINI.md](GEMINI.md).

This document covers **practical security steps** before pushing this project to GitHub,
sharing it publicly, or exposing it over the internet (e.g., via Tailscale Funnel or a VPS).

IHaveTheReceipts is a **single-user, local-first application** — it has no authentication,
no multi-tenancy, and no stored passwords. Its threat model is therefore narrow but real:
leaking your Gemini API key, exposing the app to the public internet without a firewall,
or accidentally committing personal receipt data.

---

## Reporting a Vulnerability

Please report security issues **privately** — don't open a public issue, and don't
post details in a pull request or discussion.

Use GitHub's [Private Vulnerability Reporting](https://github.com/smcgazz/ihavethereceipts/security/advisories/new):
go to the **Security** tab → **Report a vulnerability**. The report is visible only
to the maintainer until a fix is published.

What to expect:

- **Acknowledgement** within about a week. This is a hobby project maintained by one
  person in their spare time, so please don't expect same-day triage.
- **A fix or an explicit "won't fix"** once the report is confirmed. Anything declined
  will come with the reasoning — usually that it falls under
  [What This App Intentionally Does NOT Have](#7-what-this-app-intentionally-does-not-have).
- **Credit** in the release notes, unless you'd rather stay anonymous.

Useful context when reporting: the version or commit SHA, your OCR backend
(`local` or `gemini`), and whether the instance is LAN-only or internet-exposed.

Because this app is single-user and local-first with no authentication, reports that
assume a multi-user threat model (privilege escalation between accounts, session
fixation, and similar) generally don't apply — see section 7.

---

## 1. Before Pushing to GitHub

| Risk | Mitigation |
| :--- | :--- |
| **Gemini API key in code** | Key must live in `.env` only. Confirm `.env` is in `.gitignore` before every push. |
| **Personal receipts / images** | `data/uploads/`, `data/processed/`, `data/GroceryReceiptsPDFs/` are all gitignored. Verify with `git status` before committing. |
| **SQLite database** | `*.db`, `*.db-shm`, `*.db-wal` are gitignored. Never commit `grocery.db` — it contains your full purchase history. |
| **Internal planning docs** | `scratch/`, `PROJECT_REVIEW.md`, `reclassification_analysis.md` etc. are gitignored. Review the Internal Documentation block in `.gitignore` before a public release. |
| **Stack traces in logs** | `uvicorn_log.txt` is gitignored. Never commit log files. |

**Quick pre-push audit:**
```bash
git status          # confirm no untracked sensitive files
git diff --cached   # review staged content before committing
grep -r "AIza" .    # spot-check for accidentally hardcoded API keys
```

---

## 2. API Key Management

- **Never hardcode** `GEMINI_API_KEY` or any other secret in source files or templates.
- Store all secrets in `.env` (root or `backend/.env` — both are gitignored).
- If you suspect a key was committed, **revoke it immediately** in [Google AI Studio](https://aistudio.google.com) before attempting to clean git history.
- Rotate your key periodically. Gemini free-tier keys are rate-limited but not scoped — a leaked key can exhaust your quota.

---

## 3. Network Exposure

By default, the app binds to `0.0.0.0:8000`, meaning it is reachable by any device on your LAN.

### LAN-only (default — acceptable)
No additional hardening required for home use. Ensure your router does not expose port 8000 to the internet.

### Public internet exposure (Tailscale Funnel, VPS, or port-forwarding)
If you expose the app publicly, you **must** add authentication. The app currently has none.
Options in order of simplicity:

1. **HTTP Basic Auth via a reverse proxy** (nginx, Caddy) — one username/password guards the entire app. Caddy example:
   ```
   basicauth /* {
       yourusername <bcrypt-hash>
   }
   ```
2. **Tailscale ACLs** — restrict funnel access to specific Tailscale users only.
3. **`TRUSTED_IPS` allowlist** — add middleware to reject requests from outside a known CIDR range.

> ⚠️ **Do not rely on "security through obscurity"** (e.g., a non-standard port). The app has no CSRF protection on several state-changing endpoints and no rate limiting on the OCR upload endpoint.

---

## 4. File Upload Security

The OCR receipt upload endpoint (`POST /receipts/upload`) accepts images and PDFs.

- **MIME type validation** is done server-side via `python-magic`. Do not disable it.
- **File size** is currently uncapped — on a public deployment, add an `upload_max_size` limit in the FastAPI endpoint or via a reverse proxy (`client_max_body_size` in nginx).
- Uploaded files are stored in `data/uploads/` which is **not served statically** — they are read by the OCR service and not directly accessible via URL.
- `pdf2image` shells out to `poppler` — ensure poppler is kept up to date (`sudo apt upgrade poppler-utils`).

---

## 5. Dependency Security

- Run `uv pip list --outdated` periodically to identify stale packages.
- Two runtime dependencies carry **GPL-2.0** licenses (`fuzzywuzzy`, `python-levenshtein`). These are slated for removal — `rapidfuzz` (MIT) is already the preferred replacement in all new code. See [SBOM.md](SBOM.md).
- The `psycopg2-binary` and `asyncpg` PostgreSQL drivers are declared in `pyproject.toml` as legacy artifacts — the app uses SQLite exclusively. They are safe to prune in a future cleanup.

---

## 6. Content Security Policy

`SecurityHeadersMiddleware` (in `app/main.py`) sets the following headers on every response:

| Header | Value / Notes |
| :--- | :--- |
| `Content-Security-Policy` | Configured in middleware — review if adding new external resources |
| `X-Frame-Options` | `DENY` — prevents clickjacking |
| `X-Content-Type-Options` | `nosniff` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |

All frontend JS, CSS, and fonts are **vendored locally** (`backend/static/js/vendor/`, `backend/static/fonts/`). No CDN requests are made at runtime, which simplifies the CSP.

---

## 7. What This App Intentionally Does NOT Have

These are absent by design for a single-user local tool — do not add them unless exposing the app publicly:

- Authentication / login
- Session management
- CSRF tokens (no multi-user state to protect)
- Account lockout
- Password hashing
- OAuth / SSO

If you choose to add authentication, use an established library (`authlib`, `fastapi-users`) rather than rolling your own.

---

*Last reviewed: August 2026*
