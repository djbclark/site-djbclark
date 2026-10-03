#!/usr/bin/env python3
"""Watchdog for the basic-memory-mcp launchd service (port 18796).

Runs periodically (via launchd StartInterval). Each run:
  1. Health-checks the MCP endpoint with a real POST (not a bare GET -- the
     streamable-http transport only replies to a session-initiated POST).
  2. On failure: restarts the launchd job (`launchctl kickstart -k`).
  3. Tracks failure state in a small JSON file so that a restart only
     happens if the state actually changed from healthy, and a repeated
     string of failures (crash-loop) past a threshold stops auto-restarting
     and instead escalates once via Telegram, backing off further checks.

This gives three Telegram outcomes, not an endless stream:
  - "went down, restarting" (first failure after being healthy)
  - "restart worked" (recovered after a failure)
  - "still down after N attempts, giving up -- needs manual look" (escalation,
    sent once, then watchdog goes quiet on this incident until it recovers
    or state file is cleared)
"""
import json
import subprocess
import sys
import time
import urllib.request
import urllib.error

STATE_FILE = "/Users/djbclark/.hermes/cache/basic_memory_watchdog_state.json"
LOG_FILE = "/Users/djbclark/Library/Logs/basic-memory-mcp/watchdog.log"
LABEL = "com.djbclark.basic-memory-mcp"
URL = "http://127.0.0.1:18796/mcp"
HERMES_BIN = "/Users/djbclark/.local/bin/hermes"
NOTIFY_TARGET = "telegram:838808636:22158"  # Inbox topic (per hermes-messaging skill)

MAX_RESTART_ATTEMPTS = 3   # consecutive failed-then-restarted cycles before giving up
ESCALATION_COOLDOWN_S = 3600 * 6  # don't re-escalate more than once per 6h while still down


def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line)
    except Exception:
        pass
    print(line, end="")


def load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {"status": "healthy", "consecutive_failures": 0, "last_escalation": 0, "attempts_since_healthy": 0}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def health_check():
    """Real MCP initialize handshake, not a bare GET."""
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "watchdog", "version": "1.0"}},
    }).encode()
    req = urllib.request.Request(
        URL, data=payload, method="POST",
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as e:
        # Some MCP servers return 4xx for a handshake without a session but
        # still prove the ASGI stack is alive and responsive.
        return e.code < 500
    except Exception as e:
        log(f"health_check failed: {e!r}")
        return False


def notify(text):
    try:
        subprocess.run([HERMES_BIN, "send", "--to", NOTIFY_TARGET, text],
                        timeout=30, check=False,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log(f"notify failed: {e!r}")


def restart_service():
    subprocess.run(["launchctl", "kickstart", "-k",
                     f"gui/{__import__('os').getuid()}/{LABEL}"],
                    check=False)


def main():
    state = load_state()
    healthy = health_check()
    now = time.time()

    if healthy:
        if state["status"] != "healthy":
            log("recovered")
            notify("✅ Basic Memory MCP recovered and is responding again.")
        state["status"] = "healthy"
        state["consecutive_failures"] = 0
        state["attempts_since_healthy"] = 0
        save_state(state)
        return

    # unhealthy
    state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
    log(f"unhealthy (consecutive_failures={state['consecutive_failures']})")

    if state.get("status") == "escalated":
        # already gave up this incident; only re-notify on a cooldown, no restarts
        if now - state.get("last_escalation", 0) > ESCALATION_COOLDOWN_S:
            notify("⚠️ Basic Memory MCP is still down. Watchdog has stopped auto-restarting "
                   "this incident (hit the retry limit) -- needs a manual look.")
            state["last_escalation"] = now
        save_state(state)
        return

    attempts = state.get("attempts_since_healthy", 0)
    if attempts >= MAX_RESTART_ATTEMPTS:
        log("giving up -- escalating, will not auto-restart further")
        notify(f"🛑 Basic Memory MCP failed to come back after {attempts} restart attempts. "
               "Giving up auto-restart to avoid a crash loop -- needs manual investigation. "
               f"(label: {LABEL}, port 18796)")
        state["status"] = "escalated"
        state["last_escalation"] = now
        save_state(state)
        return

    if state["status"] == "healthy":
        notify("🔻 Basic Memory MCP went down (health check failed). Restarting it now...")

    log(f"restarting (attempt {attempts + 1}/{MAX_RESTART_ATTEMPTS})")
    restart_service()
    state["status"] = "down"
    state["attempts_since_healthy"] = attempts + 1
    save_state(state)


if __name__ == "__main__":
    sys.exit(main())
