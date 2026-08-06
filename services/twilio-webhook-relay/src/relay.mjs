const encoder = new TextEncoder();

export function parseTwilioForm(body) {
  const params = new URLSearchParams(body);
  const values = {};
  for (const [key, value] of params) {
    if (Object.prototype.hasOwnProperty.call(values, key)) {
      values[key] = Array.isArray(values[key]) ? [...values[key], value] : [values[key], value];
    } else {
      values[key] = value;
    }
  }
  return values;
}

export async function hmacSha1Base64(secret, value) {
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-1" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(value));
  return btoa(String.fromCharCode(...new Uint8Array(signature)));
}

export async function twilioSignature(url, params, authToken) {
  const canonical = Object.keys(params)
    .sort()
    .map((key) => `${key}${Array.isArray(params[key]) ? params[key].join("") : params[key]}`)
    .join("");
  return hmacSha1Base64(authToken, `${url}${canonical}`);
}

function constantTimeEqual(left, right) {
  const a = encoder.encode(left);
  const b = encoder.encode(right);
  let difference = a.length ^ b.length;
  const length = Math.max(a.length, b.length);
  for (let index = 0; index < length; index += 1) {
    difference |= (a[index] ?? 0) ^ (b[index] ?? 0);
  }
  return difference === 0;
}

export async function isValidTwilioSignature({ url, params, signature, authToken }) {
  if (!signature || !authToken) return false;
  const expected = await twilioSignature(url, params, authToken);
  return constantTimeEqual(expected, signature);
}

export function normalizeTwilioEvent(params, receivedAt = new Date().toISOString()) {
  const sid = params.MessageSid || params.CallSid || params.SmsSid || null;
  const eventType = params.MessageStatus
    ? "message.status"
    : params.CallStatus
      ? "call.status"
      : params.EventType || "twilio.webhook";
  return {
    provider: "twilio",
    event_type: eventType,
    id: sid,
    status: params.MessageStatus || params.CallStatus || null,
    account_sid: params.AccountSid || null,
    from: params.From || null,
    to: params.To || null,
    error_code: params.ErrorCode || null,
    error_message: params.ErrorMessage || null,
    received_at: receivedAt,
    data: params,
  };
}

export class MemoryIdempotencyStore {
  constructor() {
    this.values = new Set();
  }

  async has(key) {
    return this.values.has(key);
  }

  async add(key) {
    this.values.add(key);
  }
}

export async function handleTwilioCallback({
  request,
  authToken,
  idempotencyStore,
  forward,
  now = () => new Date().toISOString(),
}) {
  if (request.method !== "POST") {
    return new Response("method not allowed", { status: 405, headers: { Allow: "POST" } });
  }

  const body = await request.text();
  const params = parseTwilioForm(body);
  const valid = await isValidTwilioSignature({
    url: request.url,
    params,
    signature: request.headers.get("X-Twilio-Signature"),
    authToken,
  });
  if (!valid) return new Response("invalid Twilio signature", { status: 403 });

  const event = normalizeTwilioEvent(params, now());
  const idempotencyKey = event.id ? `${event.event_type}:${event.id}:${event.status ?? ""}` : null;
  if (idempotencyKey && await idempotencyStore.has(idempotencyKey)) {
    return Response.json({ accepted: true, duplicate: true });
  }

  await forward(event);
  if (idempotencyKey) await idempotencyStore.add(idempotencyKey);
  return Response.json({ accepted: true }, { status: 202 });
}
