# Security Review Report — ADS-B Receiver

**Date:** 2026-06-24
**Scope:** `adsb_receiver/` (PyQt6 desktop application for ADS-B telemetry ingestion, decoding, database persistence, and rebroadcasting)
**Methodology:** STRIDE-aware manual review + automated SAST (Bandit) + secret scan (regex) + dependency audit (pip-audit) + secure code checklist
**Reviewer:** Senior Security Engineer (claude opus 4.6)

---

## 1. Executive Summary

| Category | Count |
|---|---|
| **Critical** | 0 |
| **High** | 2 |
| **Medium** | 4 |
| **Low** | 5 |
| **Informational** | 4 |

**Overall posture:** The application is a **single-user, single-host desktop tool** with no multi-tenant server component. The risk surface is therefore limited to the local machine plus the local network (LAN) it listens on for inbound feeds and exposes an API on. There is no public internet exposure by default, and no auth boundary is present. Within those constraints the code is reasonably defensive: parameterized SQL is used throughout, no `eval`/`exec`/`subprocess`, and no hardcoded secrets in the source tree.

**Top concerns to address:**
1. The FastAPI `GET /api/aircraft` endpoint binds to `0.0.0.0:8000` by default with **no authentication, permissive CORS (`*` with credentials)**, exposing live aircraft telemetry to the LAN/internet.
2. The TCP **server mode** for AVR/SBS/Beast feeds binds to `0.0.0.0` with **no client authentication, no TLS, no rate limit** — an attacker on the LAN can inject forged aircraft positions or flood the decoder.
3. The `.env` file is loaded from the local or parent directory with a **plaintext default password** (`"your_secure_password"`) when env vars are missing.

---

## 2. Scope & Data Flow

### 2.1 Application surface
| Component | File | Role |
|---|---|---|
| Bootstrap | `main.py` | Wires GUI, workers, queues |
| GUI | `gui/main_window.py`, `gui/dialogs.py` | PyQt6 desktop UI |
| Network ingest | `receiver.py` | TCP client/server, UDP server, Serial, Mock |
| Decoder | `decoder.py` | Mode-S/ADS-B parser, in-memory state cache |
| Persistence | `db/postgres_client.py` | TimescaleDB/PostgreSQL |
| Offline buffer | `db/offline_db.py` | SQLite fallback |
| Workers | `workers/*.py` | Receiver, Decoder, Uploader, Sender, WebServer |
| External API | `hexdb.io` | Aircraft metadata enrichment |

### 2.2 Trust boundaries
```
[SDR/HTTP feed]──(plaintext TCP/UDP)──►[Receiver]──►[Decoder]──►[TimescaleDB]
                                                  │
                                                  ├─►[Sender/Forwarder]──(plaintext TCP/UDP)──►[External]
                                                  │
                                                  └─►[WebServer]──(plaintext HTTP)──►[LAN]
```

All three network edges (ingest, forward, serve) are **unauthenticated plaintext** on the local network.

---

## 3. Findings

### H-1 — FastAPI telemetry endpoint has no authentication and permissive CORS
**Severity:** High
**Location:** `workers/web_server_worker.py:29-41`
**STRIDE:** Information Disclosure, Spoofing, Tampering

The `GET /api/aircraft` endpoint exposes a full snapshot of all live aircraft state (ICAO, callsign, position, altitude, velocity, heading, squawk) without any authentication. The CORS middleware is configured with:

```python
allow_origins=["*"],
allow_credentials=True,
allow_methods=["*"],
allow_headers=["*"],
```

Combined with the `WEB_SERVER_HOST` defaulting to `0.0.0.0` (`config.py:32`), the API is reachable from any host on the network. A browser visiting a malicious page from the same machine (or any LAN peer) can read live aircraft data via the API.

**Impact:**
- Live aircraft telemetry (including military, private, or law enforcement flights if `is_military` is set) is exposed to any peer.
- Combined with permissive CORS, a web page can exfiltrate this data cross-origin.
- `allow_credentials=True` with `allow_origins=["*"` is a known dangerous combination per the CORS spec — browsers should reject it, but other CORS-aware clients may honor it.

**Remediation:**
- Bind the API to `127.0.0.1` by default; require explicit opt-in to listen on `0.0.0.0`.
- Add token-based auth (e.g., a `X-API-Key` header check against an env var, or a short-lived JWT).
- Restrict CORS to specific origins (e.g., `["http://localhost:3000"]`).
- If LAN exposure is required, add a reverse proxy with TLS and basic auth in front (Nginx is already part of the wider stack).
- Drop `allow_credentials=True` unless you actually need cookie-based auth cross-origin.

---

### H-2 — TCP/UDP ingest servers bind to all interfaces with no authentication
**Severity:** High
**Location:** `receiver.py:275-364`, `config.py:32`
**STRIDE:** Spoofing, Tampering, Denial of Service

The receiver supports both **client** (connect to dump1090) and **server** mode (accept inbound feeds). When the user configures a connection with `address` of `0.0.0.0`, `::`, empty, or `localhost`, the code starts a TCP server (`receiver.py:424-430`) on that port. There is no:

- Client allowlist
- IP-based rate limit
- Maximum-connection cap (the listen backlog is `5`, but each connection spawns a daemon reader thread, so this is a soft cap, not a security control)
- TLS — feeds are plaintext AVR/SBS/Beast
- Input validation on parsed bytes (the parser silently drops bad frames, but unbounded data still flows through)

**Impact:**
- An attacker on the LAN can connect to the configured port and **inject forged aircraft positions** (spoofed ICAO, callsign, lat/long) into the local state cache, which is then persisted to TimescaleDB and forwarded to the rebroadcaster.
- The `SenderWorker` will then **rebroadcast the forged data** to all configured downstreams — turning the receiver into an unwitting spoofing relay.
- An attacker can also send a high rate of data to consume decoder/DB/forwarder resources (DoS).
- All decoder/DB/forwarding threads can be saturated even without authentication, by simply opening many TCP connections.

**Remediation:**
- Default `address` in dialogs (`gui/dialogs.py:27`) to `127.0.0.1` rather than `0.0.0.0` and document the implication of `0.0.0.0`.
- Add a per-IP rate limit and a global max-connection cap (e.g., `asyncio.Semaphore` if moved to async, or a `threading.Semaphore` for the threaded model).
- For deployments across untrusted networks, terminate the feed at a VPN or wrap the TCP server with `ssl.SSLContext` and required client certificates.
- Validate ICAO format and bounds on parsed values before they enter the state cache.

---

### M-1 — Default `DATABASE_PASSWORD` is a literal placeholder string
**Severity:** Medium
**Location:** `config.py:23`
**STRIDE:** Information Disclosure (config), Elevation of Privilege (when env not set)

```python
DB_PASSWORD = os.getenv("DATABASE_PASSWORD", "your_secure_password")
```

If `.env` is absent or the var is unset, the app silently falls back to the literal string `"your_secure_password"`. A user running the app without configuring credentials will end up trying (and likely failing) to connect to a database with a well-known password. If a developer or test environment happens to have set that password on their Postgres, the credentials are public-knowledge.

**Remediation:**
- Fail-fast on missing required env vars at startup, e.g.:
  ```python
  DB_PASSWORD = os.environ["DATABASE_PASSWORD"]  # raises KeyError if unset
  ```
- Or use a hard `RuntimeError("DATABASE_PASSWORD not set")` early in `main.py`.

---

### M-2 — Insecure connection-string assembly logs the password on error
**Severity:** Medium
**Location:** `config.py:41`, `db/postgres_client.py:54`
**STRIDE:** Information Disclosure

`get_connection_string()` returns `f"host=... password={DB_PASSWORD}"`. On a failed `psycopg2.connect()`, `psycopg2` typically includes the connection string in its exception message (depending on driver version and settings). The `DatabaseClient.connect` method logs `f"Failed to connect to the database: {e}"` at ERROR level.

**Impact:** A local log file or syslog capture will contain the DB password in plaintext if a connection error occurs.

**Remediation:**
- Use `psycopg2.connect()` keyword arguments (`host=`, `port=`, `dbname=`, `user=`, `password=`) rather than a connection string. The lib will not echo params on error.
- Wrap the connect call to log only the host/port/db/user, not the full error.

---

### M-3 — FastAPI CORS: `allow_credentials=True` with `allow_origins=["*"]`
**Severity:** Medium
**Location:** `workers/web_server_worker.py:30-36`

The combination `allow_credentials=True` + `allow_origins=["*"]` violates the CORS specification. Modern browsers reject credentialed cross-origin requests when origin is `*`, so the current code is effectively only protected by browser enforcement, not server policy. Non-browser CORS clients (Python, curl with header, custom clients) will not be subject to the same protection.

**Remediation:** Either set `allow_credentials=False` (most likely correct for a read-only API) or specify a concrete `allow_origins` list. See H-1 for the full set of fixes.

---

### M-4 — `_fetch_aircraft_metadata` has no input validation
**Severity:** Medium
**Location:** `db/postgres_client.py:12-27`
**STRIDE:** Information Disclosure (limited)

`icao` is used to build the URL path with `f"https://hexdb.io/api/v1/aircraft/{icao_clean}"`. The `icao_clean = icao.lower().strip()` is the only sanitization. If an attacker can influence the value (e.g., a malicious source feeding crafted `icao` strings into the DB), they could attempt:
- Path traversal in the URL (`../../`) — harmless because `https.get` won't follow.
- URL injection (`?` or `#`) — `requests.get` will accept it and could leak other hexdb.io resources or, with a man-in-the-middle TLS termination, expose data.

The current call site is `decoder.py` which receives `icao` from pyModeS-decoded binary data, so attacker influence is limited. Still, defensive validation is cheap.

**Remediation:**
- Validate `icao` is exactly 6 hex characters before using it in the URL:
  ```python
  if not re.fullmatch(r"[0-9a-fA-F]{6}", icao_clean):
      return None
  ```

---

### L-1 — `try / except: pass` in 4 locations
**Severity:** Low
**Location:** `main.py:115-116`, `receiver.py:88-92`, `receiver.py:99-103`, `workers/sender_worker.py:189-192`
**STRIDE:** Repudiation (logging gaps)

Bandit flagged 4 `try_except_pass` instances. They all occur in socket shutdown paths or stat counters where silencing the exception is intentional. The risk is operational, not security: failures during shutdown go unlogged, making it harder to debug connection leaks.

**Remediation:** Add at least a `logger.debug("...")` inside the except blocks, e.g.:
```python
try:
    conn.close()
except Exception as exc:
    logger.debug("TCP connection close failed: %s", exc)
```

---

### L-2 — `MockReceiver` log file read uses `open()` without `encoding=`
**Severity:** Low
**Location:** `receiver.py:494`
**STRIDE:** Information Disclosure (limited)

```python
with open(self.log_file_path, "r") as f:
```

On Windows, the default encoding is the system codepage (often cp1252), which can throw `UnicodeDecodeError` on non-ASCII bytes. The path is also not validated for symlink traversal, though the user picks it via a dialog, so risk is minimal.

**Remediation:**
- Use `open(..., "r", encoding="utf-8", errors="replace")` for consistency with the other text parsers in the file.

---

### L-3 — Database password echoed in PyQt dialog UI state
**Severity:** Low
**Location:** `gui/main_window.py:300, 454`
**STRIDE:** Information Disclosure (process memory)

`self.db_pass_input` uses `QLineEdit.EchoMode.Password` (good), but the password is then assigned back to `self.config.DB_PASSWORD` (plaintext Python attribute) and used to build a `psycopg2.connect()` string. The password lives in process memory and in the `main_window.db_pass_input.text()` string until the window closes. This is normal for desktop apps, but worth noting that on a shared workstation, process memory inspection (or a crash dump) can expose the credential.

**Remediation:**
- Consider passing the password directly to the connect call without persisting on the config module; clear `db_pass_input` after use; or use Qt's `QLineEdit.EchoMode.PasswordEchoOnEdit` for transient visibility.

---

### L-4 — Logger emits connection data length and row contents at INFO
**Severity:** Low
**Location:** `db/postgres_client.py:339, 375, 461, 495`
**STRIDE:** Information Disclosure (logs)

Statements like `logger.info(f"DB: get_active_connections returned {len(rows)} rows. Description: {[desc[0] for desc in self.cursor.description]}")` log the column names of queries at INFO. This is benign in isolation, but combined with verbose logging (the default in this app is INFO) the log file becomes a roadmap of the DB schema.

**Remediation:** Demote these to DEBUG, or log only the row count without the column description.

---

### L-5 — `int(os.getenv(...))` and `float(os.getenv(...))` will raise uncaught `ValueError`
**Severity:** Low
**Location:** `config.py:20, 27, 30, 33, 36-38`
**STRIDE:** Denial of Service (limited)

If the user sets `BATCH_INTERVAL_SEC=foo`, the application fails with a `ValueError` at import time, before any UI renders. This is fail-fast (good), but the error message is just a Python traceback to the user.

**Remediation:** Wrap env parsing in a helper that raises a clear message, e.g.:
```python
def _int(name, default):
    raw = os.getenv(name)
    if raw is None: return default
    try: return int(raw)
    except ValueError:
        raise RuntimeError(f"Env {name} must be an integer (got {raw!r})")
```

---

### I-1 — No HTTPS/TLS for the upload API or hexdb.io callsites
**Severity:** Informational
**Location:** `config.py:31`, `db/postgres_client.py:15`

Both outbound endpoints already use HTTPS (`https://bytenusa.cloud/...` and `https://hexdb.io/...`), so this is **good** — but `requests.get(url, timeout=3.0)` does not pin certificates. If a CA is compromised, the connection is still encrypted but not authenticated against the true origin.

**Remediation:** Optional — if you want stronger pinning, use `requests.get(url, timeout=3.0, verify=True)` (the default) and bundle a custom CA bundle via the `REQUESTS_CA_BUNDLE` env var or `certifi` package.

---

### I-2 — Database connection has no `sslmode` enforcement
**Severity:** Informational
**Location:** `config.py:41`, `db/postgres_client.py:46-47`

The connection string is `host=... port=... dbname=... user=... password=...` with no `sslmode=require`. If the application is run against a remote PostgreSQL, the password and all data flow in plaintext over the network.

**Remediation:** Add `sslmode=require` (or `verify-full` for production) to the connection string when `DB_HOST != "127.0.0.1"` and `DB_HOST != "localhost"`.

---

### I-3 — Forwarder writes to arbitrary TCP/UDP destinations with no validation
**Severity:** Informational
**Location:** `workers/sender_worker.py:62-218`, `db/postgres_client.py:519-565`

The `senders` table allows configuring a TCP or UDP destination. The host is taken from user input with no allowlist. An authenticated user (or attacker who can write to the DB) can configure the app to send data to arbitrary hosts on any port.

**Impact:** Limited. The data being sent is the same telemetry the user already receives, so this is a *relay* capability rather than data exfiltration of a new asset.

**Remediation:** Document the implication; consider an admin confirmation dialog when adding a new sender; restrict destination ports to known feed-aggregator ports (e.g., 30002-30005) in a future release.

---

### I-4 — The "UPLOAD_API_URL" config is defined but not used
**Severity:** Informational
**Location:** `config.py:31`

`UPLOAD_API_URL` is loaded from env but is never referenced elsewhere in the codebase (the uploader worker writes to the local TimescaleDB, not to a remote HTTP endpoint). Dead config — not a security issue, just clutter.

**Remediation:** Remove the unused setting, or wire it up to a real remote sync endpoint (in which case add auth headers, timeout, and retry-with-backoff).

---

## 4. Threat Model Summary (STRIDE per element)

| Element | S | T | R | I | D | E | Notes |
|---|---|---|---|---|---|---|---|
| ADS-B feed (inbound) | X (server mode H-2) | X (H-2) | — | — | X (H-2) | — | No auth/TLS on TCP/UDP server mode |
| ReceiverWorker / SDRReceiver | — | — | — | — | X (L-1) | — | Threads silently die on stop error |
| DecoderWorker | — | X (H-2 indirect) | — | — | — | — | Accepts any decoded message into cache |
| WebServer (FastAPI) | X (H-1) | — | — | X (H-1) | — | — | No auth, permissive CORS |
| SenderWorker | X (relay) | X (relay) | — | X (I-3) | — | — | Forwards all data to configured destinations |
| TimescaleDB | — | — | — | X (M-2, I-2) | — | — | Plaintext password, no TLS |
| hexdb.io call | — | — | — | X (M-4) | — | — | Unvalidated ICAO in URL path |
| Config / .env | — | — | — | X (M-1) | — | — | Placeholder default password |
| Mock log file | — | X (L-2) | — | — | — | — | Encoding unspecified |

---

## 5. OWASP Top 10 Mapping

| OWASP 2021 | Findings |
|---|---|
| A01 Broken Access Control | H-1 (no auth on API), H-2 (no auth on feeds) |
| A02 Cryptographic Failures | I-2 (no DB TLS), I-1 (no cert pinning) |
| A03 Injection | None — all SQL is parameterized (`%s`, `?`) |
| A04 Insecure Design | H-1, H-2 (no auth by design) |
| A05 Security Misconfiguration | M-1 (default password), M-3 (CORS) |
| A06 Vulnerable & Outdated Components | None — `pip-audit` clean |
| A07 Identification & Auth Failures | H-1, H-2 |
| A08 Software & Data Integrity | H-2 (data source not authenticated) |
| A09 Security Logging & Monitoring | L-1, L-4 (suppressed errors, schema logs) |
| A10 SSRF | M-4 (limited) |

---

## 6. Dependency Audit

`pip-audit -r requirements.txt` against the live OS advisory feed returned **No known vulnerabilities found** for the pinned packages:

| Package | Pin |
|---|---|
| pymodes | >=3.3.0 |
| psycopg2-binary | >=2.9.0 |
| python-dotenv | >=1.0.0 |
| PyQt6 | >=6.4.0 |
| pyserial | >=3.5 |
| requests | >=2.31.0 |
| fastapi | >=0.100.0 |
| uvicorn | >=0.22.0 |

**Recommendation:** Consider pinning to exact versions rather than `>=` for reproducible security baselines. A `pip-audit` step in CI is recommended.

---

## 7. Recommendations Summary (priority order)

| # | Action | Severity | Owner |
|---|---|---|---|
| 1 | Add token-based auth + restrict CORS on FastAPI endpoint; default to `127.0.0.1` | H-1 | Backend |
| 2 | Default ingest `address` to `127.0.0.1`; add per-IP rate limit + max-conn cap on TCP server | H-2 | Backend |
| 3 | Fail-fast on missing `DATABASE_PASSWORD`; remove the `"your_secure_password"` default | M-1 | Backend |
| 4 | Use `psycopg2.connect()` keyword args; don't log full connection errors | M-2 | Backend |
| 5 | Drop `allow_credentials=True` from CORS, or set explicit origins | M-3 | Backend |
| 6 | Validate ICAO is 6 hex chars before calling hexdb.io | M-4 | Backend |
| 7 | Add `logger.debug` in `try_except_pass` blocks | L-1 | Backend |
| 8 | Use `encoding="utf-8"` in `MockReceiver` `open()` | L-2 | Backend |
| 9 | Demote DB schema description logs to DEBUG | L-4 | Backend |
| 10 | Add `sslmode=require` to remote DB connections | I-2 | DevOps |
| 11 | Remove unused `UPLOAD_API_URL` or wire to a real endpoint with auth | I-4 | Backend |
| 12 | Add `pip-audit` to CI | — | DevOps |

---

## 8. Validation Checklist

- [x] Automated secret scan completed (regex) — 0 findings
- [x] Bandit SAST completed — 6 findings (2 medium, 4 low) all reviewed
- [x] `pip-audit` completed — 0 known CVEs
- [x] All DFD elements analyzed via STRIDE
- [x] Authentication, authorization, input validation, crypto reviewed
- [x] Findings classified by severity with file:line references
- [x] Remediation guidance provided for each finding

---

*This review covers the `adsb_receiver/` Python project at the commit checked out at review time. The wider NestJS monorepo in `hidrometeo-be/` is out of scope for this engagement but uses JWT/passport and should be reviewed separately.*
