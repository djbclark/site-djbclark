"""Linux mocked qualification/hash tests. Never execute the real upgrader."""
import copy
import hashlib
import json
import os
from pathlib import Path

import pytest
from test_paseo_local_upgrade import plu, make_app, Fake, touched
from paseo_upgrade_policy import Hold, bundle_sha256, grant, marker


def policy(target, old, generation=1, operation="activate"):
    return {"schemaVersion": 1, "component": "paseo-desktop", "generation": generation,
            "stateCompatibility": "binary-only", "operations": {operation: {
                "allowed": True, "transactionId": "test-controller", "receiptSha256": "a" * 64,
                "archiveSha256": "b" * 64, "version": "0.16.0-beta.2",
                "bundleSha256": bundle_sha256(target), "previousBundleSha256": bundle_sha256(old)}}}


@pytest.fixture
def qualified(tmp_path):
    old, target = tmp_path / "Paseo.app", tmp_path / "Paseo-local.app"
    make_app(old, updater=True)
    make_app(target)
    (target / "Contents/Resources/managed-release.json").write_text(json.dumps({"schemaVersion": 1, "component": "paseo-desktop"}))
    fake = Fake(tmp_path)
    ctx = plu.Ctx(old, target, tmp_path / "previous.app", tmp_path / "journal", str(tmp_path / "home"), 0, 1, [],
                  runner=fake, sleep=lambda _: None, updater_cache=tmp_path / "cache", shipit_cache=tmp_path / "shipit")
    value = policy(target, old)
    ctx.policy_reader = lambda: copy.deepcopy(value)
    return ctx, fake, value


@pytest.mark.parametrize("mutation", [
    lambda p: p.clear(), lambda p: p.update(schemaVersion=True),
    lambda p: p.update(generation=True), lambda p: p.update(generation=0),
    lambda p: p.update(stateCompatibility="migrate"), lambda p: p.update(operations={}),
    lambda p: p["operations"]["activate"].update(allowed=1),
    lambda p: p["operations"]["activate"].update(allowed=False),
    lambda p: p["operations"]["activate"].update(receiptSha256="forged"),
    lambda p: p["operations"]["activate"].update(transactionId=""),
])
def test_malformed_revoked_policy(qualified, mutation):
    ctx, fake, value = qualified
    mutation(value)
    assert plu.do_apply(ctx, plu.parse(["--apply", "--yes", "--want-broken", "--allow-terminals"])) == 4
    assert not touched(fake)


@pytest.mark.parametrize("field", ["bundleSha256", "previousBundleSha256"])
def test_wrong_digest(qualified, field):
    ctx, fake, value = qualified
    value["operations"]["activate"][field] = "0" * 64
    with pytest.raises(Hold):
        plu.authorize(ctx, capture=True)
    assert not touched(fake)


def test_marker_is_selection_not_authority(qualified):
    ctx, fake, value = qualified
    ctx.policy_reader = lambda: {}
    assert plu.do_apply(ctx, plu.parse(["--apply", "--yes"])) == 4
    assert not touched(fake)


def test_missing_marker_with_qualified_bytes(qualified):
    ctx, _, value = qualified
    (ctx.staged / "Contents/Resources/managed-release.json").unlink()
    value["operations"]["activate"]["bundleSha256"] = bundle_sha256(ctx.staged)
    with pytest.raises(Hold, match="marker"):
        plu.authorize(ctx, capture=True)


def test_revocation_after_prompt(qualified, monkeypatch):
    ctx, fake, value = qualified
    monkeypatch.setattr(plu, "confirm", lambda _: value["operations"]["activate"].update(allowed=False))
    assert plu.do_apply(ctx, plu.parse(["--apply", "--yes"])) != 0
    assert not touched(fake)


def test_unsupported_reservation_never_quits(qualified):
    ctx, fake, _ = qualified
    original = fake.__call__
    ctx.runner = lambda argv, timeout: plu.Result(1, "", "unsupported") if "maintenance" in argv else original(argv, timeout)
    assert plu.do_apply(ctx, plu.parse(["--apply", "--yes"])) == 4
    assert not touched(fake)
    assert ctx.installed.exists() and ctx.staged.exists() and not ctx.backup.exists()


@pytest.mark.parametrize("response", [{}, {"schemaVersion": 1, "state": "busy"},
    {"schemaVersion": 1, "state": "held", "generation": 999, "transactionId": "test-controller", "ownerToken": "secret"}])
def test_failed_busy_mismatched_maintenance(qualified, response):
    ctx, fake, _ = qualified
    plu.authorize(ctx, capture=True)
    ctx.runner = lambda *args: plu.Result(0, json.dumps(response))
    with pytest.raises(Hold):
        plu.maintenance(ctx, "begin")
    assert not touched(fake)


def test_revoked_before_swap_retains_artifacts(qualified):
    ctx, _, value = qualified
    plu.authorize(ctx, capture=True)
    ctx.reservation = {"generation": 1, "transactionId": "test-controller", "ownerToken": "secret"}
    value["generation"] = 2
    with pytest.raises(Hold):
        plu.swap_in(ctx)
    assert ctx.installed.exists() and ctx.staged.exists() and not ctx.backup.exists()


def test_recovery_revoked_never_relaunches(qualified):
    ctx, fake, _ = qualified
    assert plu.rollback_core(ctx, "runtime failure", True) == 4
    assert not touched(fake)
    assert json.loads((ctx.state_dir / "last-run.json").read_text())["phase"] == "recovery-required"


def test_same_generation_recovery_denied(qualified):
    ctx, _, value = qualified
    plu.authorize(ctx, capture=True)
    value["operations"]["recover"] = copy.deepcopy(value["operations"]["activate"])
    with pytest.raises(Hold, match="new generation"):
        plu.authorize(ctx, "recover", capture=True)


def test_cache_same_version_still_holds(qualified):
    ctx, _, _ = qualified
    ctx.updater_cache.mkdir()
    (ctx.updater_cache / "Paseo-0.16.0-beta.2-arm64.zip").write_bytes(b"forged archive")
    assert any("cache identity" in e for e in plu.update_errors(ctx))


def test_tree_jsonl_unicode_order_and_link(tmp_path):
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "é").write_bytes(b"x")
    (root / "a").mkdir()
    (root / "a/link").symlink_to("../é")
    records = [["d", "a", (root / "a").lstat().st_mode & 0o777],
               ["l", "a/link", (root / "a/link").lstat().st_mode & 0o777, "../é"],
               ["f", "é", (root / "é").stat().st_mode & 0o777, 1, hashlib.sha256(b"x").hexdigest()]]
    expected = hashlib.sha256("".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in records).encode()).hexdigest()
    assert bundle_sha256(root) == expected
    (root / "empty").mkdir()
    assert bundle_sha256(root) != expected


def test_tree_external_links_and_specials_rejected(tmp_path):
    (tmp_path / "outside").symlink_to("/etc/passwd")
    with pytest.raises(Hold):
        bundle_sha256(tmp_path)
    (tmp_path / "outside").unlink()
    os.mkfifo(tmp_path / "fifo")
    with pytest.raises(Hold):
        bundle_sha256(tmp_path)


def test_tree_invalid_unicode_rejected(tmp_path):
    os.close(os.open(os.fsencode(tmp_path) + b"/bad-\xff", os.O_CREAT | os.O_WRONLY, 0o600))
    with pytest.raises(Hold):
        bundle_sha256(tmp_path)


def test_tree_unstable_read_rejected(tmp_path, monkeypatch):
    p = tmp_path / "file"
    p.write_bytes(b"before")
    original = os.fstat
    def mutate(fd):
        s = original(fd)
        p.write_bytes(b"changing")
        return s
    monkeypatch.setattr(os, "fstat", mutate)
    with pytest.raises(Hold):
        bundle_sha256(tmp_path)


def test_journal_excludes_token_and_preserves_state(qualified):
    ctx, _, _ = qualified
    plu.authorize(ctx, capture=True)
    ctx.reservation = {"ownerToken": "NEVER-PERSIST"}
    state = Path(ctx.home)
    state.mkdir()
    (state / "sessions").write_bytes(b"unchanged")
    plu.save_state(ctx, phase="recovery-required")
    raw = (ctx.state_dir / "last-run.json").read_text()
    assert "NEVER-PERSIST" not in raw and "test-controller" in raw
    assert (state / "sessions").read_bytes() == b"unchanged"


def native_runner(ctx, fake, *, offline=True, fail_runtime=False, recover=False, value=None):
    """In-process test adapter, not a claim that the native API exists."""
    def runner(argv, timeout=60, input_text=None):
        if "maintenance" in argv:
            action = argv[argv.index("maintenance") + 1]
            if action == "begin":
                return plu.Result(0, json.dumps({"schemaVersion": 1, "state": "held", "generation": 1,
                    "transactionId": "test-controller", "ownerToken": "PRIVATE-TOKEN", "recoveryRequired": False}))
            if action == "end":
                assert "PRIVATE-TOKEN" not in argv
                assert input_text == "PRIVATE-TOKEN\n"
                return plu.Result(0, json.dumps({"schemaVersion": 1, "state": "idle", "generation": 1, "recoveryRequired": False}))
            if not offline and not fake.daemon_up:
                return plu.Result(1, "", "offline status unsupported")
            return plu.Result(0, json.dumps({"schemaVersion": 1, "state": "held", "generation": 1,
                "transactionId": "test-controller", "recoveryRequired": False}))
        if fail_runtime and argv[0] == "open" and ctx.swapped and not ctx.swapped_back:
            if recover:
                value.clear()
                value.update(policy(ctx.backup, ctx.installed, generation=2, operation="recover"))
            return plu.Result(1, "", "failed candidate launch")
        return fake(argv, timeout)
    return runner


def test_authorized_replacement_retains_previous_and_releases_after_verification(qualified):
    ctx, fake, _ = qualified
    old = bundle_sha256(ctx.installed)
    ctx.runner = native_runner(ctx, fake)
    assert plu.do_apply(ctx, plu.parse(["--apply", "--yes"])) == 0
    assert bundle_sha256(ctx.backup) == old
    assert json.loads((ctx.state_dir / "last-run.json").read_text())["phase"] == "done"
    assert not ctx.reservation


def test_offline_status_missing_holds_without_swap_or_relaunch(qualified):
    ctx, fake, _ = qualified
    ctx.runner = native_runner(ctx, fake, offline=False)
    assert plu.do_apply(ctx, plu.parse(["--apply", "--yes"])) == 4
    assert not ctx.swapped and ctx.installed.exists() and ctx.staged.exists()
    assert not any(c[0] == "open" for c in fake.calls)
    assert ctx.reservation


def test_failed_runtime_requires_separate_authorized_recovery(qualified):
    ctx, fake, value = qualified
    old = bundle_sha256(ctx.installed)
    ctx.runner = native_runner(ctx, fake, fail_runtime=True, recover=True, value=value)
    assert plu.do_apply(ctx, plu.parse(["--apply", "--yes"])) == 1
    assert bundle_sha256(ctx.installed) == old and ctx.staged.exists()
    record = json.loads((ctx.state_dir / "last-run.json").read_text())
    assert record["phase"] == "rolled-back" and record["qualification"]["generation"] == 2


def test_failed_runtime_without_recovery_grant_stays_uncertain(qualified):
    ctx, fake, _ = qualified
    ctx.runner = native_runner(ctx, fake, fail_runtime=True)
    assert plu.do_apply(ctx, plu.parse(["--apply", "--yes"])) == 4
    assert ctx.swapped and not ctx.swapped_back and ctx.backup.exists()
    assert json.loads((ctx.state_dir / "last-run.json").read_text())["phase"] == "recovery-required"
