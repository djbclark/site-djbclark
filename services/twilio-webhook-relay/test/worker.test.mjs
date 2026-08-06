import test from "node:test";
import assert from "node:assert/strict";
import worker from "../src/worker.mjs";
import { parseTwilioForm, twilioSignature } from "../src/relay.mjs";

const authToken = "worker-auth-token";
const url = "https://relay.example/twilio/callback";

function kvStore() {
  const values = new Map();
  return {
    async get(key) { return values.get(key) ?? null; },
    async put(key, value) { values.set(key, value); },
  };
}

test("worker exposes a health endpoint", async () => {
  const response = await worker.fetch(new Request("https://relay.example/health"), { IDEMPOTENCY: kvStore() });
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { status: "ok" });
});

test("worker forwards a signed callback as JSON", async () => {
  const body = "MessageSid=SM999&MessageStatus=failed&ErrorCode=30007";
  const signature = await twilioSignature(url, parseTwilioForm(body), authToken);
  const originalFetch = globalThis.fetch;
  let forwarded;
  globalThis.fetch = async (_target, options) => {
    forwarded = { target: _target, options };
    return new Response("ok", { status: 202 });
  };
  try {
    const response = await worker.fetch(new Request(url, {
      method: "POST",
      headers: { "X-Twilio-Signature": signature },
      body,
    }), {
      TWILIO_AUTH_TOKEN: authToken,
      FORWARD_URL: "https://forward.example/events",
      IDEMPOTENCY: kvStore(),
    });
    assert.equal(response.status, 202);
    assert.equal(forwarded.target, "https://forward.example/events");
    assert.equal(JSON.parse(forwarded.options.body).error_code, "30007");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
