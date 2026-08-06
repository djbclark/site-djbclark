import { handleTwilioCallback } from "./relay.mjs";

function idempotencyStore(env) {
  return {
    async has(key) {
      return Boolean(await env.IDEMPOTENCY.get(key));
    },
    async add(key) {
      await env.IDEMPOTENCY.put(key, "1", { expirationTtl: 60 * 60 * 24 * 7 });
    },
  };
}

async function forwardToHermes(event, env) {
  if (!env.FORWARD_URL) throw new Error("FORWARD_URL is not configured");
  const response = await fetch(env.FORWARD_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(env.FORWARD_TOKEN ? { Authorization: `Bearer ${env.FORWARD_TOKEN}` } : {}),
    },
    body: JSON.stringify(event),
  });
  if (!response.ok) throw new Error(`forward target returned HTTP ${response.status}`);
}

export default {
  async fetch(request, env) {
    if (new URL(request.url).pathname === "/health") {
      return Response.json({ status: "ok" });
    }
    if (new URL(request.url).pathname !== "/twilio/callback") {
      return new Response("not found", { status: 404 });
    }

    try {
      return await handleTwilioCallback({
        request,
        authToken: env.TWILIO_AUTH_TOKEN,
        idempotencyStore: idempotencyStore(env),
        forward: (event) => forwardToHermes(event, env),
      });
    } catch (error) {
      console.error("Twilio callback processing failed", error);
      return new Response("callback processing failed", { status: 502 });
    }
  },
};
