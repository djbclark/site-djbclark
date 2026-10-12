# SIPB LLMs — API notes

Reverse-engineered from the Open WebUI OpenAPI spec at
<https://llms-dev-1.mit.edu/openapi.json> (Open WebUI 0.6.30, "LLMS-DEV-1").

Re-verified 2026-10-12: `/api/version` is still 0.6.30; the live `openapi.json` has the same 310 paths
as the copy here (only four `operationId`s on `/openai/{path}` differ, refreshed). The Ollama behind it is
0.32.13 (from the `/ollama/api/version` passthrough).

## Instance facts (from `/api/config`)

```json
{
  "status": true,
  "name": "LLMS-DEV-1 (Open WebUI)",
  "version": "0.6.30",
  "oauth": { "providers": { "oidc": "Touchstone" } },
  "features": {
    "auth": true,
    "enable_api_key": true,
    "enable_signup": false,
    "enable_login_form": true
  }
}
```

- Auth: HTTP Bearer (Open WebUI `sk-` API key; see "API key format" below) or
  Touchstone OIDC (browser SSO for the web UI).
- Public (no auth): `/api/version`, `/api/config`, `/`, `/openapi.json`, `/docs`.

## OpenAI-compatible endpoints

The API key is a **Bearer** token. Base URL: `https://llms-dev-1.mit.edu/api`.

| Purpose | Endpoint |
| --- | --- |
| Chat completions | `POST /api/chat/completions` (also `/api/v1/chat/completions`) |
| List models | `GET /api/models` (also `/api/v1/models`, `/openai/models`) |
| Legacy OpenAI path | `POST /openai/chat/completions`, `GET /openai/models` |
| Ollama passthrough | `POST /ollama/v1/chat/completions`, `GET /ollama/v1/models` |

Example (curl):

```bash
curl https://llms-dev-1.mit.edu/api/chat/completions \
  -H "Authorization: Bearer $MIT_SIPB_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-r1:32b","messages":[{"role":"user","content":"hi"}]}'
```

## API key format

Open WebUI API keys (Settings → Account → API Keys) are `sk-`-prefixed: `sk-`
followed by 32 hex characters (35 chars total), e.g. `sk-e491...`. They are
sent as `Authorization: Bearer <key>`.

**Gotcha:** store the key verbatim with no trailing newline. A trailing `\n`
in the stored value corrupts `POST` requests (it ends the HTTP header block
early, so the `Content-Type`/body get mangled and the server returns a bogus
`422 {"detail":[{"type":"missing","loc":["body"],"msg":"Field required"}]}`).
`GET` endpoints happen to survive because the stray newline just terminates the
header list. Fix by re-`set`ting the key without the newline.

## Behaviour that is not in the spec (observed 2026-10-12; details in [REPORT.md](REPORT.md))

1. A streamed response that contains tool calls ends with `finish_reason: "stop"` instead of
   `"tool_calls"`; clients that continue on `tool_calls` stop after the first call. Fixed locally by
   `tools/sipb-llms-proxy` (site-djbclark).
2. A prompt over the ~32768-token context returns HTTP 200 with the body `null`.
3. A request queued behind another model or user can return no data for 2+ minutes.
4. Tool calling does not work for `gpt-oss:20b` (empty arguments, aborted stream) or `devstral:24b`
   (tool call emitted as text). It works for the qwen3.5/3.6, qwen3-coder and gemma4 models tried.
5. The model list had 48 entries on 2026-10-12 (39 chat models and 9 embedding models); `aya:35b` and `aya:8b` are F16.
