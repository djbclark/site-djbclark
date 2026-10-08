"""Contract tests for context_size_nudge.py's tier/escalation logic."""
import json
import subprocess
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HOOKS_DIR))

import context_size_nudge as nudge

BASE = 25_000


def _line(total, **extra):
    """One assistant record whose usage adds up to `total` context tokens."""
    usage = {"input_tokens": 2, "cache_creation_input_tokens": 1_000,
             "cache_read_input_tokens": total - 1_002}
    return json.dumps({"message": {"usage": usage}, **extra}) + "\n"


def _write_transcript(path, *totals):
    path.write_text("".join(_line(t) for t in totals))
    return path


def _run_hook(monkeypatch, tmp_path, session_id, transcript_path, capsys):
    monkeypatch.setattr(nudge, "STATE_PATH", tmp_path / "state.json")
    sent = []
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kwargs: sent.append(cmd))
    payload = json.dumps({"session_id": session_id, "cwd": str(tmp_path),
                          "transcript_path": str(transcript_path)})
    monkeypatch.setattr(sys, "stdin", type("FakeStdin", (), {"read": staticmethod(lambda: payload)})())
    nudge.main()
    return capsys.readouterr().out, sent


def _state(tmp_path, session_id):
    return json.loads((tmp_path / "state.json").read_text())[session_id]


def test_small_growth_stays_silent(monkeypatch, tmp_path, capsys):
    t = _write_transcript(tmp_path / "t.jsonl", BASE, BASE + nudge.EARLY_GROWTH - 1)
    out, sent = _run_hook(monkeypatch, tmp_path, "s", t, capsys)
    assert out == "" and sent == []


def test_big_baseline_alone_does_not_fire(monkeypatch, tmp_path, capsys):
    """A session started in ~ begins near 90k; that is not growth."""
    t = _write_transcript(tmp_path / "t.jsonl", 90_000, 100_000)
    out, _ = _run_hook(monkeypatch, tmp_path, "s", t, capsys)
    assert out == ""


def test_early_tier_recommends_options_and_bigteam(monkeypatch, tmp_path, capsys):
    t = _write_transcript(tmp_path / "t.jsonl", BASE, BASE + nudge.EARLY_GROWTH)
    out, sent = _run_hook(monkeypatch, tmp_path, "s", t, capsys)
    assert "/bigteam" in out and "/compact" in out and "/handoff then /new" in out
    assert "AskUserQuestion" not in out
    assert sent == []
    assert _state(tmp_path, "s")["level"] == 1


def test_ask_tier_by_growth(monkeypatch, tmp_path, capsys):
    t = _write_transcript(tmp_path / "t.jsonl", BASE, BASE + nudge.ASK_GROWTH)
    out, _ = _run_hook(monkeypatch, tmp_path, "s", t, capsys)
    assert "AskUserQuestion" in out and out.startswith("Context is large")


def test_ask_tier_by_absolute_total(monkeypatch, tmp_path, capsys):
    t = _write_transcript(tmp_path / "t.jsonl", 100_000, nudge.ASK_TOTAL)
    out, _ = _run_hook(monkeypatch, tmp_path, "s", t, capsys)
    assert "AskUserQuestion" in out


def test_each_tier_fires_once_then_repeats_on_growth(monkeypatch, tmp_path, capsys):
    path = tmp_path / "t.jsonl"
    _write_transcript(path, BASE, BASE + nudge.ASK_GROWTH)
    out1, _ = _run_hook(monkeypatch, tmp_path, "s", path, capsys)
    out2, _ = _run_hook(monkeypatch, tmp_path, "s", path, capsys)
    assert out1 and out2 == ""
    _write_transcript(path, BASE, BASE + nudge.ASK_GROWTH + nudge.REPEAT_EVERY)
    out3, _ = _run_hook(monkeypatch, tmp_path, "s", path, capsys)
    assert out3.startswith("Context is still growing")


def test_compaction_rearms_tiers(monkeypatch, tmp_path, capsys):
    path = tmp_path / "t.jsonl"
    _write_transcript(path, BASE, BASE + nudge.ASK_GROWTH)
    _run_hook(monkeypatch, tmp_path, "s", path, capsys)
    _write_transcript(path, BASE, BASE + nudge.ASK_GROWTH, BASE + 10_000)
    assert _run_hook(monkeypatch, tmp_path, "s", path, capsys)[0] == ""
    _write_transcript(path, BASE, BASE + nudge.EARLY_GROWTH)
    out, _ = _run_hook(monkeypatch, tmp_path, "s", path, capsys)
    assert out.startswith("Context check")


def test_page_fires_once_via_hermes_ping(monkeypatch, tmp_path, capsys):
    path = _write_transcript(tmp_path / "t.jsonl", BASE, BASE + nudge.PAGE_GROWTH)
    _, sent = _run_hook(monkeypatch, tmp_path, "s", path, capsys)
    assert len(sent) == 1 and sent[0][0].endswith("hermes-ping")
    assert sent[0][1].startswith(tmp_path.name + ":")
    _, sent2 = _run_hook(monkeypatch, tmp_path, "s", path, capsys)
    assert sent2 == []


def test_sidechain_and_cache_miss_records(tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text(_line(50_000) + _line(900_000, isSidechain=True))
    assert nudge._last_context_tokens(str(t)) == 50_000
    miss = {"message": {"usage": {"input_tokens": 3, "cache_creation_input_tokens": 80_000,
                                  "cache_read_input_tokens": 0}}}
    t.write_text(json.dumps(miss) + "\n")
    assert nudge._last_context_tokens(str(t)) == 80_003


def test_missing_transcript_path_is_silent_and_safe(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(nudge, "STATE_PATH", tmp_path / "state.json")
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


def test_reads_large_transcript_from_tail_only(tmp_path):
    transcript = tmp_path / "big.jsonl"
    with transcript.open("w") as f:
        for _ in range(5000):
            f.write(_line(30_000))
        f.write(_line(400_000))
    assert nudge._last_context_tokens(str(transcript)) == 400_000
    assert nudge._first_context_tokens(str(transcript)) == 30_000


def test_usage_block_beyond_small_tail_window_is_still_found(tmp_path):
    transcript = tmp_path / "wide.jsonl"
    with transcript.open("w") as f:
        f.write(_line(400_000))
        filler = json.dumps({"type": "tool_result", "content": "x" * 4000}) + "\n"
        for _ in range(100):  # ~400 KB of lines with no usage block
            f.write(filler)
    assert transcript.stat().st_size > nudge._TAIL_WINDOWS[0]
    assert nudge._last_context_tokens(str(transcript)) == 400_000


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
