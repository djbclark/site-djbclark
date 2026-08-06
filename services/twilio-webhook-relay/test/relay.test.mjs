import test from "node:test";
import assert from "node:assert/strict";
import {
  MemoryIdempotencyStore,
  handleTwilioCallback,
  normalizeTwilioEvent,
  parseTwilioForm,
  twilioSignature,
} from "../src/relay.mjs";

const authToken = "test-auth-token";
const callbackUrl = "https://relay.example/twilio/callback";
const body = "MessageSid=SM123&MessageStatus=delivered&AccountSid=AC123&From=%2B15550001&To=%2B15550002";

async function requestWithSignature(bodyText = body, url = callbackUrl) {
  const params = parseTwilioForm(bodyText);
  const signature = await twilioSignature(url, params, authToken);
  return new Request(url, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded", "X-Twilio-Signature": signature },
    body: bodyText,
  });
}

test("normalizes a message delivery callback", () => {
  const event = normalizeTwilioEvent(parseTwilioForm(body), "2026-08-06T00:00:00.000Z");
  assert.deepEqual(event, {
    provider: "twilio",
    event_type: "message.status",
    id: "SM123",
    status: "delivered",
    account_sid: "AC123",
    from: "+15550001",
    to: "+15550002",
    error_code: null,
    error_message: null,
    received_at: "2026-08-06T00:00:00.000Z",
    data: {
      MessageSid: "SM123",
      MessageStatus: "delivered",
      AccountSid: "AC123",
      From: "+15550001",
      To: "+15550002",
    },
  });
});

test("accepts a valid Twilio signature and forwards the normalized event", async () => {
  const store = new MemoryIdempotencyStore();
  const forwarded = [];
  const response = await handleTwilioCallback({
    request: await requestWithSignature(),
    authToken,
    idempotencyStore: store,
    forward: async (event) => forwarded.push(event),
    now: () => "2026-08-06T00:00:00.000Z",
  });
  assert.equal(response.status, 202);
  assert.equal(forwarded.length, 1);
  assert.equal(forwarded[0].status, "delivered");
});

test("rejects an invalid signature without forwarding", async () => {
  const store = new MemoryIdempotencyStore();
  let forwarded = false;
  const request = new Request(callbackUrl, {
    method: "POST",
    headers: { "X-Twilio-Signature": "invalid" },
    body,
  });
  const response = await handleTwilioCallback({
    request,
    authToken,
    idempotencyStore: store,
    forward: async () => { forwarded = true; },
  });
  assert.equal(response.status, 403);
  assert.equal(forwarded, false);
});

test("does not forward the same message status twice", async () => {
  const store = new MemoryIdempotencyStore();
  let count = 0;
  const request = await requestWithSignature();
  const options = {
    authToken,
    idempotencyStore: store,
    forward: async () => { count += 1; },
  };
  assert.equal((await handleTwilioCallback({ request: request.clone(), ...options })).status, 202);
  assert.equal((await handleTwilioCallback({ request: request.clone(), ...options })).status, 200);
  assert.equal(count, 1);
});

test("allows later status transitions for the same message", async () => {
  const store = new MemoryIdempotencyStore();
  let count = 0;
  const queuedBody = body.replace("delivered", "queued");
  const delivered = await requestWithSignature(body);
  const queued = await requestWithSignature(queuedBody);
  const options = { authToken, idempotencyStore: store, forward: async () => { count += 1; } };
  await handleTwilioCallback({ request: queued, ...options });
  await handleTwilioCallback({ request: delivered, ...options });
  assert.equal(count, 2);
});

test("returns 405 for non-POST requests", async () => {
  const response = await handleTwilioCallback({
    request: new Request(callbackUrl),
    authToken,
    idempotencyStore: new MemoryIdempotencyStore(),
    forward: async () => {},
  });
  assert.equal(response.status, 405);
});
