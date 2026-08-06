# Twilio webhook relay

Reusable Cloudflare Worker adapter for Twilio callbacks. The relay is intentionally
provider-neutral: it validates Twilio at the edge, normalizes the event, suppresses
replayed status callbacks with a seven-day KV key, and forwards JSON to a configured
HTTPS target.

## Endpoints

- `GET /health` — returns `{"status":"ok"}`.
- `POST /twilio/callback` — accepts Twilio's `application/x-www-form-urlencoded`
  callback payload and `X-Twilio-Signature` header.

The public callback URL must be the exact URL configured in Twilio. Twilio signs the
full URL plus sorted form parameters, so changing the hostname, path, or query string
breaks validation.

## Local tests

```bash
npm test
```

The test suite covers message-status normalization, valid and invalid signatures,
status-transition idempotency, and method rejection.

## Deployment shape

1. Create a Cloudflare Worker and KV namespace for `IDEMPOTENCY`.
2. Copy `wrangler.toml.example` to `wrangler.toml` and replace the placeholder
   namespace IDs and forwarding URL. Do not commit the real file if it contains
   site-specific values.
3. Store deployment secrets through the approved secrets workflow, not in files:

   ```bash
   # The exact secret injection command depends on the deployment environment.
   # Values must originate from secretspec and must not be pasted into shell history.
   secretspec get TWILIO_AUTH_TOKEN --reason "deploy daycare-phone webhook relay" \
     | wrangler secret put TWILIO_AUTH_TOKEN
   secretspec get TWILIO_FORWARD_TOKEN --reason "deploy daycare-phone webhook relay" \
     | wrangler secret put FORWARD_TOKEN
   ```

   `TWILIO_FORWARD_TOKEN` is a future declaration if the forwarding target needs
   bearer authentication; declare it with `secretspec add` before using it.
4. Deploy with Wrangler from this directory:

   ```bash
   npx wrangler deploy
   ```
5. Give Twilio the resulting HTTPS URL ending in `/twilio/callback`.
6. Verify with a signed test callback before enabling production traffic.

## Forwarding contract

The relay posts JSON like this to `FORWARD_URL`:

```json
{
  "provider": "twilio",
  "event_type": "message.status",
  "id": "SM…",
  "status": "delivered",
  "account_sid": "AC…",
  "from": "+1…",
  "to": "+1…",
  "error_code": null,
  "error_message": null,
  "received_at": "2026-08-06T00:00:00.000Z",
  "data": {}
}
```

`FORWARD_TOKEN`, when configured, is sent as an `Authorization: Bearer` header.
The target adapter still needs to be selected and documented: either an HTTPS
Hermes webhook endpoint or a small notification service that forwards selected events
to Telegram. The worker deliberately does not assume Hermes' internal HMAC/header
contract until that endpoint is confirmed.

## Security and operations

- `TWILIO_AUTH_TOKEN` is a Cloudflare Worker secret and is never committed.
- Invalid Twilio signatures receive HTTP 403 and are not forwarded.
- Forwarding failures receive HTTP 502 so Twilio can retry the callback.
- Successful callbacks receive HTTP 202.
- Duplicate `(event_type, SID, status)` callbacks receive HTTP 200 and are not
  forwarded again.
- KV entries expire after seven days; this bounds storage and replay suppression.
- Add monitoring for 4xx/5xx rates and forwarding latency before production use.

This package does not expose the Mac, require Docker, or depend on the local Hermes
process being reachable from the Internet.
