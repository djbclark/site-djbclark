"""Contract tests for context_size_nudge.py's threshold/debounce logic."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HOOKS_DIR))

import context_size_nudge as nudge  # noqa: E402


def _write_transcript(tmp_path, cache_read_tokens):
    path = tmp_path / "transcript.jsonl"
    path.write_text(json.dumps({"message": {"usage": {"cache_read_input_tokens": cache_read_tokens}}}) + "\n")
    return path


def _run_hook(monkeypatch, tmp_path, session_id, transcript_path, capsys):
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(nudge, "STATE_PATH", state_path)
    sent = []
    monkeypatch.setattr(
        subprocess, "Popen",
        lambda cmd, **kwargs: sent.append(cmd),
    )
    monkeypatch.setattr(
        sys, "stdin",
        type("FakeStdin", (), {"read": staticmethod(lambda: json.dumps({
            "session_id": session_id,
            "transcript_path": str(transcript_path),
        }))})(),
    )
    nudge.main()
    out = capsys.readouterr().out
    return out, sent, state_path


def test_below_threshold_stays_silent(monkeypatch, tmp_path, capsys):
    transcript = _write_transcript(tmp_path, 50_000)
    out, sent, _ = _run_hook(monkeypatch, tmp_path, "s-low", transcript, capsys)
    assert out == ""
    assert sent == []


def test_soft_threshold_prints_but_does_not_page(monkeypatch, tmp_path, capsys):
    transcript = _write_transcript(tmp_path, nudge.SOFT_THRESHOLD + 1)
    out, sent, state_path = _run_hook(monkeypatch, tmp_path, "s-soft", transcript, capsys)
    assert "getting large" in out
    assert sent == []
    state = json.loads(state_path.read_text())
    assert state["s-soft"] == {"soft": True}


def test_hard_threshold_prints_and_pages(monkeypatch, tmp_path, capsys):
    transcript = _write_transcript(tmp_path, nudge.HARD_THRESHOLD + 1)
    out, sent, state_path = _run_hook(monkeypatch, tmp_path, "s-hard", transcript, capsys)
    assert "very large" in out
    assert len(sent) == 1
    assert sent[0][:3] == ["hermes", "send", "-t"]
    state = json.loads(state_path.read_text())
    assert state["s-hard"] == {"soft": True, "hard": True}


def test_debounce_suppresses_repeat_nudge_for_same_session(monkeypatch, tmp_path, capsys):
    transcript = _write_transcript(tmp_path, nudge.HARD_THRESHOLD + 1)
    _run_hook(monkeypatch, tmp_path, "s-repeat", transcript, capsys)
    out2, sent2, _ = _run_hook(monkeypatch, tmp_path, "s-repeat", transcript, capsys)
    assert out2 == ""
    assert sent2 == []


def test_missing_transcript_path_is_silent_and_safe(monkeypatch, tmp_path, capsys):
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(nudge, "STATE_PATH", state_path)
    monkeypatch.setattr(
        sys, "stdin",
        type("FakeStdin", (), {"read": staticmethod(lambda: json.dumps({"session_id": "s-none"}))})(),
    )
    nudge.main()
    assert capsys.readouterr().out == ""


def test_malformed_stdin_never_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(nudge, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(sys, "stdin", type("FakeStdin", (), {"read": staticmethod(lambda: "not json")})())
    nudge.main()  # must not raise


def test_reads_large_transcript_from_tail_only(monkeypatch, tmp_path, capsys):
    """Real transcripts run tens of MB; confirm the tail-read still finds the
    most recent usage block without needing to scan the whole file."""
    transcript = tmp_path / "big.jsonl"
    with transcript.open("w") as f:
        for _ in range(5000):
            f.write(json.dumps({"message": {"usage": {"cache_read_input_tokens": 1_000}}}) + "\n")
        f.write(json.dumps({"message": {"usage": {"cache_read_input_tokens": nudge.HARD_THRESHOLD + 1}}}) + "\n")
    out, sent, _ = _run_hook(monkeypatch, tmp_path, "s-big", transcript, capsys)
    assert "very large" in out
    assert len(sent) == 1


def test_usage_block_beyond_small_tail_window_is_still_found(monkeypatch, tmp_path, capsys):
    """The first (small) tail window has no usage block; the wider one must."""
    transcript = tmp_path / "wide.jsonl"
    with transcript.open("w") as f:
        f.write(json.dumps({"message": {"usage": {"cache_read_input_tokens": nudge.HARD_THRESHOLD + 1}}}) + "\n")
        filler = json.dumps({"type": "tool_result", "content": "x" * 4000}) + "\n"
        for _ in range(100):  # ~400 KB of lines with no usage block
            f.write(filler)
    assert transcript.stat().st_size > nudge._TAIL_WINDOWS[0]
    out, sent, _ = _run_hook(monkeypatch, tmp_path, "s-wide", transcript, capsys)
    assert "very large" in out


def test_newest_usage_block_wins(tmp_path):
    transcript = tmp_path / "t.jsonl"
    with transcript.open("w") as f:
        for v in (900_000, 10_000):
            f.write(json.dumps({"message": {"usage": {"cache_read_input_tokens": v}}}) + "\n")
    assert nudge._last_cache_read_tokens(str(transcript)) == 10_000


def test_deadline_exits_zero_silently(tmp_path):
    """A hook that stalls (stdin never closes) is killed by its own alarm: exit 0, no output."""
    import time
    script = HOOKS_DIR / "context_size_nudge.py"
    src = script.read_text().replace("DEADLINE_SECONDS = 2", "DEADLINE_SECONDS = 1")
    patched = tmp_path / "nudge.py"
    patched.write_text(src)
    proc = subprocess.Popen([sys.executable, str(patched)], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    t0 = time.time()
    try:
        proc.wait(timeout=5)
    finally:
        out = proc.stdout.read()
        proc.stdin.close()
    assert proc.returncode == 0
    assert out == b""
    assert time.time() - t0 < 4
