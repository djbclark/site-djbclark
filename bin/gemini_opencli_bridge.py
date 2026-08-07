#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Localhost-only Hermes-facing wrapper around the OpenCLI Gemini adapter
(site-djbclark#105).

Provides exactly three Hermes-facing operations against Dan's already
signed-in Gemini web session, shared visibly in Chrome:

    gemini_opencli_bridge.py status         -- login/availability check
    gemini_opencli_bridge.py read           -- read the visible conversation
    gemini_opencli_bridge.py ask "<prompt>" -- send a prompt, return the reply

This wraps the installed `opencli` CLI (external dependency, verified
@jackwener/opencli 1.8.6, Apache-2.0 -- see docs/reference/gemini-opencli-bridge.md
for the install path and manual Chrome setup). It never talks to Chrome, the
daemon, or the network directly; it only invokes `opencli` as a subprocess
with an argument list (no shell interpolation) and interprets its output.

Security boundary: no passwords, MFA codes, API keys, cookies, or
browser-profile data are ever read, stored, or transmitted here -- there is
no configuration path that captures those. Prompt text is never persisted.
By default the only thing written locally is bounded, non-sensitive audit
metadata (see `_write_audit_entry`). Set GEMINI_BRIDGE_CAPTURE_CONTENT=1 to
additionally opt into a local, bounded *response* preview in the audit log
for debugging -- capped at HARD_MAX_CAPTURE_CHARS (4 KiB) regardless of
configuration, since a captured response may itself contain sensitive user
content and this wrapper does not scan it for secrets.
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

DEFAULT_PROFILE = "hermes-gemini"
DEFAULT_OPENCLI_PATHS = (
    "/opt/homebrew/bin/opencli",
    "/usr/local/bin/opencli",
)
DEFAULT_LOCK_TIMEOUT = 10.0
DEFAULT_STATUS_TIMEOUT = 20.0
DEFAULT_READ_TIMEOUT = 20.0
DEFAULT_ASK_TIMEOUT = 60.0
POST_ASK_SETTLE_TIMEOUT = 3.0
POST_ASK_POLL_INTERVAL = 0.1
# Wall-clock margin the wrapper's own subprocess timeout adds on top of the
# opencli-side --timeout budget it passes through for `ask`, so opencli gets
# a fair chance to hit its own timeout and report a clean error first.
ASK_SUBPROCESS_MARGIN = 15.0

# Local response-content capture (audit log only; prompts are never
# captured). Off by default. GEMINI_BRIDGE_CAPTURE_CONTENT_MAX_CHARS lets an
# operator pick a smaller preview, but HARD_MAX_CAPTURE_CHARS is a
# code-level ceiling that cannot be raised by configuration -- captured
# response text may contain sensitive user data, so the cap is not
# operator-extendable.
CAPTURE_CONTENT_ENV = "GEMINI_BRIDGE_CAPTURE_CONTENT"
CAPTURE_CONTENT_MAX_CHARS_ENV = "GEMINI_BRIDGE_CAPTURE_CONTENT_MAX_CHARS"
HARD_MAX_CAPTURE_CHARS = 4096  # 4 KiB hard cap
DEFAULT_CAPTURE_PREVIEW_CHARS = 200


class ErrorType:
    LOGIN_REQUIRED = "login_required"
    QUOTA_OR_CHALLENGE = "quota_or_challenge"
    DAEMON_UNAVAILABLE = "daemon_unavailable"
    STALE_RESPONSE = "stale_response"
    TIMEOUT = "timeout"
    UI_MISMATCH = "ui_mismatch"
    LOCK_BUSY = "lock_busy"


EXIT_CODES = {
    ErrorType.LOGIN_REQUIRED: 10,
    ErrorType.QUOTA_OR_CHALLENGE: 11,
    ErrorType.DAEMON_UNAVAILABLE: 12,
    ErrorType.STALE_RESPONSE: 13,
    ErrorType.TIMEOUT: 14,
    ErrorType.UI_MISMATCH: 15,
    ErrorType.LOCK_BUSY: 16,
}


class BridgeError(Exception):
    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message


class CaptureConfigError(ValueError):
    """Invalid GEMINI_BRIDGE_CAPTURE_CONTENT_MAX_CHARS configuration."""


def _resolve_capture_max_chars() -> int | None:
    """Return the response-preview cap in chars, or None if content capture
    is disabled (the default). Never used for prompt text -- only opt-in
    audit-log capture of the response, and only up to HARD_MAX_CAPTURE_CHARS
    regardless of configuration. Raises CaptureConfigError for a non-integer,
    non-positive, or over-the-hard-cap value; callers must decide how to
    degrade (this wrapper falls back to no-capture-this-call, see
    _write_audit_entry, rather than letting a bad audit setting break a
    real status/read/ask call)."""
    if os.environ.get(CAPTURE_CONTENT_ENV) != "1":
        return None
    raw = os.environ.get(CAPTURE_CONTENT_MAX_CHARS_ENV)
    if raw is None:
        return DEFAULT_CAPTURE_PREVIEW_CHARS
    try:
        value = int(raw)
    except ValueError as exc:
        raise CaptureConfigError(
            f"{CAPTURE_CONTENT_MAX_CHARS_ENV}={raw!r} is not an integer"
        ) from exc
    if value <= 0:
        raise CaptureConfigError(
            f"{CAPTURE_CONTENT_MAX_CHARS_ENV} must be a positive integer, got {value}"
        )
    if value > HARD_MAX_CAPTURE_CHARS:
        raise CaptureConfigError(
            f"{CAPTURE_CONTENT_MAX_CHARS_ENV}={value} exceeds the hard cap of "
            f"{HARD_MAX_CAPTURE_CHARS} chars"
        )
    return value


# Heuristic text classification of opencli failures. opencli's exact wording
# for login/quota/challenge states was not confirmed against a live signed-in
# session for this change (no Chrome extension binding available in this
# environment -- see docs/reference/gemini-opencli-bridge.md "Known gaps").
# Checked first, in this order, so an unavailable daemon/extension is never
# misreported as a login problem.
_DAEMON_PATTERNS = (
    "econnrefused",
    "failed to start opencli daemon",
    "daemon not running",
    "daemon: not running",
    "extension: not connected",
    "extension not connected",
    "could not connect",
    "no such file or directory",
)
_LOGIN_PATTERNS = (
    "not logged in",
    "login required",
    "please sign in",
    "please log in",
    "sign in to continue",
    "logged out",
)
_QUOTA_PATTERNS = (
    "quota",
    "rate limit",
    "too many requests",
    "captcha",
    "unusual traffic",
    "challenge",
)


# Narrow, explicit signal for "there is simply no conversation to read yet"
# -- distinct from the classify_failure() buckets above. Checked ONLY when a
# baseline read in do_ask() fails with error_type UI_MISMATCH (i.e. it did
# NOT match any daemon/login/quota pattern); every other error_type (and any
# UI_MISMATCH that doesn't match one of these specific phrases) is always
# propagated, never swallowed. OpenCLI's exact wording for this state was
# not confirmed against a live session -- tune these phrases after the first
# live "ask on a brand-new/never-opened conversation" run.
_NO_ACTIVE_CONVERSATION_PATTERNS = (
    "no active conversation",
    "no conversation open",
    "no conversation found",
    "no conversation loaded",
    "nothing to read",
)


def _is_no_active_conversation_message(message: str) -> bool:
    lowered = message.lower()
    return any(p in lowered for p in _NO_ACTIVE_CONVERSATION_PATTERNS)


def classify_failure(combined_output: str) -> str:
    lowered = combined_output.lower()
    if any(p in lowered for p in _DAEMON_PATTERNS):
        return ErrorType.DAEMON_UNAVAILABLE
    if any(p in lowered for p in _LOGIN_PATTERNS):
        return ErrorType.LOGIN_REQUIRED
    if any(p in lowered for p in _QUOTA_PATTERNS):
        return ErrorType.QUOTA_OR_CHALLENGE
    return ErrorType.UI_MISMATCH


def resolve_opencli_bin() -> str:
    override = os.environ.get("GEMINI_BRIDGE_OPENCLI_BIN")
    if override:
        return override
    found = shutil.which("opencli")
    if found:
        return found
    for candidate in DEFAULT_OPENCLI_PATHS:
        if os.access(candidate, os.X_OK):
            return candidate
    raise BridgeError(
        ErrorType.DAEMON_UNAVAILABLE,
        "opencli CLI not found on PATH or standard Homebrew locations; install the pinned release first "
        "(docs/reference/gemini-opencli-bridge.md)",
    )


def run_opencli(args: list[str], *, timeout: float) -> subprocess.CompletedProcess:
    """Invoke opencli as an argv list -- never shell=True, never string-joined."""
    opencli_bin = resolve_opencli_bin()
    cmd = [opencli_bin, *args]
    env = os.environ.copy()
    opencli_parent = str(Path(opencli_bin).parent)
    if opencli_bin in DEFAULT_OPENCLI_PATHS:
        current_path = env.get("PATH", "")
        env["PATH"] = opencli_parent + (os.pathsep + current_path if current_path else "")
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise BridgeError(
            ErrorType.TIMEOUT, f"opencli {' '.join(args[:3])} timed out after {timeout}s"
        ) from exc
    except OSError as exc:
        raise BridgeError(ErrorType.DAEMON_UNAVAILABLE, f"failed to invoke opencli: {exc}") from exc


Runner = Callable[..., subprocess.CompletedProcess]


def _build_gemini_args(
    profile: str, subcommand: list[str], *, extra: list[str] | None = None
) -> list[str]:
    # --profile is a global opencli option (must precede the subcommand);
    # --window/--site-session/--keep-tab are "browser common options" that
    # come after it. --window background + persistent session are the
    # "don't steal focus" / "explicit session targeting" requirements from
    # site-djbclark#105.
    args = [
        "--profile",
        profile,
        *subcommand,
        "-f",
        "json",
        "--window",
        "background",
        "--site-session",
        "persistent",
        "--keep-tab",
        "true",
    ]
    if extra:
        args.extend(extra)
    return args


def _raise_if_failed(result: subprocess.CompletedProcess) -> None:
    if result.returncode != 0:
        combined = f"{result.stdout}\n{result.stderr}".strip()
        raise BridgeError(classify_failure(combined), combined[:2000] or "opencli exited non-zero")


def _parse_json_output(stdout: str) -> Any:
    text = stdout.strip()
    if not text:
        raise BridgeError(ErrorType.UI_MISMATCH, "opencli returned empty output")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise BridgeError(
            ErrorType.UI_MISMATCH, f"opencli returned non-JSON output: {exc}"
        ) from exc


def _extract_turns(parsed: Any) -> list[dict]:
    if isinstance(parsed, list):
        turns = parsed
    elif isinstance(parsed, dict) and isinstance(parsed.get("turns"), list):
        turns = parsed["turns"]
    else:
        raise BridgeError(ErrorType.UI_MISMATCH, "unexpected 'gemini read' JSON shape")
    if not all(isinstance(t, dict) for t in turns):
        raise BridgeError(ErrorType.UI_MISMATCH, "unexpected 'gemini read' turn entries")
    return turns


def _fingerprint_turns(turns: list[dict]) -> tuple[int, str | None]:
    count = len(turns)
    if count == 0:
        return count, None
    last = turns[-1]
    text = str(last.get("Text") or last.get("text") or "")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return count, digest


def _extract_ask_response(parsed: Any) -> str:
    if isinstance(parsed, str):
        return parsed
    if isinstance(parsed, dict):
        candidates = [parsed]
    elif isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
        # OpenCLI 1.8.6 returns gemini ask -f json as [{"response": "..."}].
        candidates = [parsed[0]]
    else:
        candidates = []
    for candidate in candidates:
        for key in ("response", "Response", "text", "Text"):
            value = candidate.get(key)
            if isinstance(value, str):
                return value
    raise BridgeError(ErrorType.UI_MISMATCH, "unexpected 'gemini ask' JSON shape")


@dataclass
class BridgeResult:
    ok: bool
    command: str
    data: Any = None
    error_type: str | None = None
    error_message: str | None = None
    latency_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "command": self.command,
            "data": self.data,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "latency_ms": self.latency_ms,
        }


def do_status(profile: str, timeout: float, runner: Runner = run_opencli) -> BridgeResult:
    args = _build_gemini_args(profile, ["gemini", "status"])
    result = runner(args, timeout=timeout)
    _raise_if_failed(result)
    parsed = _parse_json_output(result.stdout)
    if isinstance(parsed, dict):
        login_value = parsed.get("Login", parsed.get("login"))
        if login_value is False or (
            isinstance(login_value, str)
            and login_value.strip().lower() in ("false", "no", "not logged in", "logged out")
        ):
            raise BridgeError(ErrorType.LOGIN_REQUIRED, "gemini status reports not logged in")
    return BridgeResult(ok=True, command="status", data=parsed)


def _invoke_read(profile: str, timeout: float, runner: Runner) -> list[dict]:
    args = _build_gemini_args(profile, ["gemini", "read"])
    result = runner(args, timeout=timeout)
    _raise_if_failed(result)
    parsed = _parse_json_output(result.stdout)
    return _extract_turns(parsed)


def do_read(profile: str, timeout: float, runner: Runner = run_opencli) -> BridgeResult:
    turns = _invoke_read(profile, timeout, runner)
    return BridgeResult(ok=True, command="read", data={"turns": turns, "turn_count": len(turns)})


def _latest_assistant_text(turns: list[dict]) -> str:
    for turn in reversed(turns):
        role = str(turn.get("Role") or turn.get("role") or "").lower()
        if role in ("model", "assistant", "gemini"):
            value = turn.get("Text", turn.get("text", ""))
            return value if isinstance(value, str) else ""
    return ""


def do_ask(
    profile: str,
    prompt: str,
    *,
    ask_timeout: float,
    read_timeout: float,
    runner: Runner = run_opencli,
) -> BridgeResult:
    # Response-ownership check (site-djbclark#105): fingerprint the
    # conversation before and after the ask, and only accept the reply if a
    # genuinely new assistant turn appeared -- otherwise a stale/prior
    # response could be misattributed to this request. A brand-new
    # conversation with zero turns is usually a normal *successful* read
    # (empty JSON list) and needs no special-casing. The only baseline-read
    # failure ever tolerated is a narrowly identified "no active
    # conversation" condition (see _is_no_active_conversation_message);
    # every other failure -- login_required, quota_or_challenge,
    # daemon_unavailable, timeout, or any other ui_mismatch -- is always
    # propagated, never swallowed into an assumed-empty baseline.
    try:
        baseline_turns = _invoke_read(profile, read_timeout, runner)
    except BridgeError as exc:
        if exc.error_type == ErrorType.UI_MISMATCH and _is_no_active_conversation_message(exc.message):
            baseline_turns = []
        else:
            raise
    baseline_count, baseline_hash = _fingerprint_turns(baseline_turns)

    ask_args = _build_gemini_args(
        profile, ["gemini", "ask", prompt], extra=["--timeout", str(int(ask_timeout))]
    )
    result = runner(ask_args, timeout=ask_timeout + ASK_SUBPROCESS_MARGIN)
    _raise_if_failed(result)
    ask_parsed = _parse_json_output(result.stdout)
    response_text = _extract_ask_response(ask_parsed)

    after_turns = _invoke_read(profile, read_timeout, runner)
    settle_deadline = time.monotonic() + POST_ASK_SETTLE_TIMEOUT
    after_count, after_hash = _fingerprint_turns(after_turns)
    while (
        (after_count <= baseline_count or after_hash is None or after_hash == baseline_hash)
        and time.monotonic() < settle_deadline
    ):
        time.sleep(POST_ASK_POLL_INTERVAL)
        after_turns = _invoke_read(profile, read_timeout, runner)
        after_count, after_hash = _fingerprint_turns(after_turns)

    if after_count <= baseline_count or after_hash is None or after_hash == baseline_hash:
        # OpenCLI 1.8.6 returns the ask response but does not append the turn
        # to the visible read snapshot. Accept only a nonempty response that
        # is not an exact echo of the current last assistant turn; repeated
        # stale responses continue to fail closed.
        if (
            not response_text.strip()
            or response_text.strip() == _latest_assistant_text(baseline_turns).strip()
        ):
            raise BridgeError(
                ErrorType.STALE_RESPONSE,
                "gemini read after ask did not show a new turn; response may be stale",
            )
        return BridgeResult(
            ok=True,
            command="ask",
            data={"response": response_text, "turn_count": after_count, "ownership": "ask_response_delta"},
        )
    last_role = str(after_turns[-1].get("Role") or after_turns[-1].get("role") or "").lower()
    if last_role and last_role not in ("model", "assistant", "gemini"):
        raise BridgeError(
            ErrorType.STALE_RESPONSE, f"latest turn role {last_role!r} is not an assistant response"
        )

    return BridgeResult(
        ok=True,
        command="ask",
        data={"response": response_text, "turn_count": after_count},
    )


def _state_dir() -> Path:
    if env := os.environ.get("GEMINI_BRIDGE_STATE_DIR"):
        return Path(env).expanduser()
    xdg_state = os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state"))
    return Path(xdg_state) / "site-djbclark" / "gemini-bridge"


def _lock_path(profile: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in profile) or "default"
    return _state_dir() / f"{safe}.lock"


class SessionLock:
    """Per-profile exclusive advisory lock with a bounded acquisition timeout.

    Same fcntl.flock pattern as bin/brew_flock.py / bin/ops_release_lock.py
    (macOS has no util-linux flock(1)); scoped per Gemini session/profile
    rather than site-wide so unrelated profiles never contend.
    """

    def __init__(self, profile: str, timeout: float) -> None:
        self.path = _lock_path(profile)
        self.timeout = timeout
        self._fd: int | None = None

    def __enter__(self) -> "SessionLock":
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(self.path, flags, 0o600)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    os.close(fd)
                    raise
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise BridgeError(
                        ErrorType.LOCK_BUSY,
                        f"gemini session {self.path.stem!r} busy after {self.timeout}s",
                    ) from exc
                time.sleep(0.05)
        try:
            os.ftruncate(fd, 0)
            os.write(fd, f"pid={os.getpid()}\n".encode())
        except OSError:
            pass
        self._fd = fd
        return self

    def __exit__(self, *exc_info: object) -> bool:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
            self._fd = None
        return False


def _write_audit_entry(profile: str, result: BridgeResult) -> None:
    """Bounded, non-sensitive-by-default audit log written only to the local
    audit state directory (never transmitted). Prompt text is never written,
    period. Response text is never written unless
    GEMINI_BRIDGE_CAPTURE_CONTENT=1 is explicitly set, and even then only up
    to HARD_MAX_CAPTURE_CHARS. A captured response preview may contain
    sensitive user data (whatever Dan or Hermes discussed with Gemini) --
    treat audit.jsonl as operator-protected once capture has ever been
    enabled, the same as any other local secret-adjacent file (0600/0700
    permissions here are enforced, but this is not a substitute for keeping
    the state directory itself access-controlled). This wrapper makes no
    claim to detect or redact secrets that may appear inside a captured
    response."""
    try:
        audit_path = _state_dir() / "audit.jsonl"
        audit_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        entry: dict[str, Any] = {
            "ts": time.time(),
            "profile": profile,
            "command": result.command,
            "ok": result.ok,
            "error_type": result.error_type,
            "latency_ms": result.latency_ms,
        }
        data = result.data
        if isinstance(data, dict) and isinstance(data.get("response"), str):
            response = data["response"]
            entry["response_size"] = len(response)
            entry["response_sha256"] = hashlib.sha256(response.encode("utf-8")).hexdigest()
            try:
                capture_max = _resolve_capture_max_chars()
            except CaptureConfigError as exc:
                capture_max = None
                print(
                    f"gemini_opencli_bridge: {exc}; response content capture "
                    "disabled for this call",
                    file=sys.stderr,
                )
            if capture_max is not None:
                entry["response_preview"] = response[:capture_max]
        with open(audit_path, "a", encoding="utf-8") as fh:
            os.fchmod(fh.fileno(), 0o600)
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def _run_command(args: argparse.Namespace) -> BridgeResult:
    if args.command == "status":
        return do_status(args.profile, DEFAULT_STATUS_TIMEOUT)
    if args.command == "read":
        return do_read(args.profile, DEFAULT_READ_TIMEOUT)
    return do_ask(
        args.profile, args.prompt, ask_timeout=args.timeout, read_timeout=DEFAULT_READ_TIMEOUT
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--profile",
            default=os.environ.get("GEMINI_BRIDGE_PROFILE", DEFAULT_PROFILE),
            help="Chrome profile/context alias bound to a dedicated Gemini tab (default: %(default)s)",
        )
        p.add_argument(
            "--lock-timeout",
            type=float,
            default=DEFAULT_LOCK_TIMEOUT,
            help="seconds to wait for the per-profile session lock (default: %(default)s)",
        )

    p_status = sub.add_parser("status", help="check Gemini login/availability")
    add_common(p_status)

    p_read = sub.add_parser("read", help="read the visible Gemini conversation")
    add_common(p_read)

    p_ask = sub.add_parser("ask", help="send a prompt, return only the new assistant response")
    p_ask.add_argument("prompt", help="prompt text (passed to opencli as a single argv element)")
    p_ask.add_argument("--timeout", type=float, default=DEFAULT_ASK_TIMEOUT)
    add_common(p_ask)

    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    start = time.monotonic()
    try:
        with SessionLock(args.profile, args.lock_timeout):
            result = _run_command(args)
    except BridgeError as exc:
        result = BridgeResult(
            ok=False, command=args.command, error_type=exc.error_type, error_message=exc.message
        )
    result.latency_ms = int((time.monotonic() - start) * 1000)
    _write_audit_entry(args.profile, result)
    print(json.dumps(result.to_dict(), indent=2))
    if result.ok:
        return 0
    return EXIT_CODES.get(result.error_type or "", 1)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
