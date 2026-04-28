---
name: secure-code
description: >
  Security rules for ocpiconnector. Load for ANY task touching credentials,
  auth tokens, OCPI handshake, payments, webhooks, Celery tasks, or secrets
  management. Covers token handling, secret storage, input validation, Django
  security settings, and OCPI-specific attack surfaces.
---

# Secure Code — ocpiconnector

## Secrets — never in code or config files

All secrets are sourced from GCP Secret Manager via the CSI driver. Never:
- Hardcode credentials, tokens, or keys anywhere in Python or YAML
- Put secrets in `configmap.yaml` — configmaps are for non-sensitive vars only
- Commit `.env` files with real values
- Log secret values, even at DEBUG level

Secrets in production:
- `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`
- `HUBJECT_CLIENT_CERTIFICATE`, `HUBJECT_PRIVATE_KEY`, `HUBJECT_CA_CERTIFICATE`
- `SENTRY_DSN`, `ALLOWED_HOSTS`

---

## OCPI auth tokens

OCPI tokens (`Credentials.token`, `CredentialsRole`) are the primary auth mechanism between OCPI parties.

**Rules:**
- Never log raw token values — log only the last 4 chars or a hash for debugging
- Never return a token in a list/search API response — only in the credentials exchange endpoint
- Tokens must be validated on every incoming OCPI request via the authentication middleware
- Never store tokens in Redis unencrypted with an unbounded TTL
- When rotating tokens, invalidate the old token atomically with creating the new one

---

## OCPI credentials handshake

The credentials exchange endpoint (`POST /ocpi/2.2/credentials`) receives a new token from the counterparty and returns our token. Vulnerabilities to avoid:

- **SSRF**: The VERSION_URL from the counterparty is fetched server-side. Always validate it is a legitimate HTTPS URL before fetching. Never fetch URLs from untrusted input without validation.
- **Token reuse**: Each credential exchange must generate a fresh token. Never reuse a previous token even if the same party reconnects.
- **Unvalidated role assumptions**: Always verify the counterparty's role (CPO/EMSP) matches what was agreed — do not trust the role field from the incoming request blindly.

---

## Celery task security

Celery task arguments are serialized to Redis and logged. **Never pass sensitive data as task arguments:**

```python
# ❌ Bad — token visible in Redis and Celery logs
send_ocpi_request.delay(url=url, token="real-token-value", ...)

# ✅ Good — look up credentials inside the task
send_ocpi_request.delay(credentials_id=credentials.id, ...)
```

Tasks that handle credentials should fetch them inside the task body using the ID, not accept raw credential values as arguments.

---

## Django security settings

Required settings (verify in `ocpiconnector/settings/`):
- `SECRET_KEY` — must come from environment, never hardcoded
- `DEBUG = False` in production — never `True` in staging/production settings
- `ALLOWED_HOSTS` — explicit list, never `["*"]` in production
- `CSRF_TRUSTED_ORIGINS` — explicit list of trusted origins
- `SECURE_PROXY_SSL_HEADER` — must be set when behind a load balancer
- `SESSION_COOKIE_SECURE = True` and `CSRF_COOKIE_SECURE = True` in production

---

## Webhook secrets

Webhooks (`webhooks/models.py`) have secrets used to sign payloads. Rules:
- Never expose the webhook secret in API responses after initial creation
- Signature validation must use `hmac.compare_digest` (constant-time) — never `==`
- Rotate webhook secrets without downtime by supporting a grace period with both old and new secrets

---

## Input validation — API boundaries

All incoming data must be validated at the API boundary before touching business logic:

- **OCPI endpoints (DRF)**: Use DRF serializers — never access `request.data` directly in views
- **Ninja endpoints**: Use Pydantic schemas — never access raw request body directly
- **MQTT messages**: Use Pydantic models (`MeterValues`, `EvseStatusUpdate`, etc.) — validate before processing
- **Integer/enum fields**: Always validate against allowed values — never pass raw strings to model fields

For OCPI string fields that map to internal model fields, always sanitize/validate length and charset before saving to DB.

---

## Hubject certificate handling

Hubject mTLS certificates are loaded from GCP Secret Manager (not filesystem). Rules:
- Never write certificate content to disk in production
- Load them into memory only (via `get_cert_from_env`)
- Never log certificate or private key content
- Certificate rotation must be done in GCP Secret Manager — not by modifying code

---

## Payment / DirectPayment security

- Never log card details, terminal IDs, or financial transaction amounts at DEBUG level in production
- `FinancialAdviceConfirmation` amounts must be validated server-side — never trust the client-submitted amount
- All payment endpoints must require authentication — no anonymous payment initiation

---

## Redis security

Redis is used for Celery broker and result backend. Rules:
- Never store session tokens or credentials in Redis with long/unbounded TTL
- Never cache sensitive user data (auth tokens, payment info) in Redis without encryption
- Redis keys for sensitive data should include expiry

---

## SQL injection

Always use Django ORM. Never use raw SQL with string interpolation:

```python
# ❌ Bad
Session.objects.raw(f"SELECT * FROM sessions WHERE uid = '{uid}'")

# ✅ Good
Session.objects.filter(uid=uid)

# ✅ If raw SQL is unavoidable
Session.objects.raw("SELECT * FROM sessions WHERE uid = %s", [uid])
```

---

## Common vulnerabilities to check before merging

- [ ] No secrets hardcoded or logged
- [ ] OCPI tokens never returned in bulk API responses
- [ ] Celery task args contain no sensitive values — IDs only
- [ ] SSRF: any URL fetched from external input is validated
- [ ] HMAC comparison uses `hmac.compare_digest`, not `==`
- [ ] No `DEBUG = True` in staging/production settings
- [ ] New API endpoints require authentication — no accidental anonymous access
- [ ] New model fields storing sensitive data have appropriate access controls
