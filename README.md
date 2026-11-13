# Hookline

Hookline is a webhook reliability console for small SaaS teams. It accepts HMAC-signed events, deduplicates retries with idempotency keys, records every delivery attempt, and lets an operator replay recoverable failures into a fictional local sink.

## Features

- Verify raw request bytes with HMAC-SHA256 before accepting an event.
- Enforce idempotency: the same key and body return the original event; key reuse with a different body returns `409`.
- Track event status, attempt count, retry time, and a timestamped attempt log.
- Retry transient failures with bounded exponential backoff; permanent failures enter the dead-letter queue.
- Simulate downstream delivery locally. Hookline does not send payloads to third-party URLs.
- Dashboard with event filters, counts, detail view, and manual retry.
- Async FastAPI and SQLAlchemy, SQLite locally, PostgreSQL with Compose.

All events and delivery destinations are local fictional demo data. The dashboard is a developer demo, not production access control.

## Run locally (Windows PowerShell)

```powershell
cd "C:\Users\Dhruv\Documents\Codex\2026-10-13\ju\work\hookline"
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
uvicorn hookline.main:app --reload
```

Dashboard: <http://127.0.0.1:8000/>  
API docs: <http://127.0.0.1:8000/docs>

Default local signing secret is `local-demo-secret-change-this`. Replace it in `.env` before sharing the app outside your machine.

## Send a signed sample event

The signature is HMAC-SHA256 over the exact request body bytes, passed as a hex digest in `X-Hookline-Signature`.

```powershell
$body = '{"event_id":"evt-1001","event_type":"invoice.paid","source":"demo-billing","payload":{"invoice":"INV-2048","amount":12500}}'
$bytes = [System.Text.Encoding]::UTF8.GetBytes($body)
$key = [System.Text.Encoding]::UTF8.GetBytes("local-demo-secret-change-this")
$hmac = [System.Security.Cryptography.HMACSHA256]::new($key)
$signature = [Convert]::ToHexString($hmac.ComputeHash($bytes)).ToLowerInvariant()
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/events -Headers @{
  "X-Hookline-Signature" = $signature
  "Idempotency-Key" = "demo-invoice-1001"
  "Content-Type" = "application/json"
} -Body $body
```

Use `payload.simulate` set to `transient` for one retryable failure or `permanent` for a dead-letter example. Omit it for successful delivery. These modes only affect the built-in fictional sink.

## Run tests

```powershell
python -m pytest -q
```

## Design notes

- The signature is checked before JSON parsing or persistence.
- A unique database constraint is the final guard against concurrent duplicate inserts.
- Each attempt is committed separately from the status transition, preserving an audit trail if later work fails.
- Retry delay is capped; manual replay is allowed only for retryable or dead-letter events.
- The demo worker/sink is intentionally in-process. A production deployment would move delivery to a durable queue and isolate tenant keys.

## Open-source references

Hookline was written from scratch. These are feature/design references, not source copied into this repository:

- [Standard Webhooks](https://github.com/standard-webhooks/standard-webhooks) — interoperable webhook signing conventions.
- [Svix](https://github.com/svix/svix-webhooks) — webhook delivery and retry concepts.
- [Stripe webhook docs](https://github.com/stripe/stripe-node) — verify signatures over the original raw body.

## License

MIT. See [LICENSE](LICENSE).
