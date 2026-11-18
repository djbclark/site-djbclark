"""Linux mocked qualification/hash tests. Never execute the real upgrader."""
import copy
import hashlib
import json
import os
from pathlib import Path

import pytest
from test_paseo_local_upgrade import plu, make_app, Fake, touched, expected_managed_plugins
from paseo_upgrade_policy import Hold, bundle_sha256, grant, marker


def policy(target, old, generation=1, operation="activate"):
    return {"schemaVersion": 1, "component": "paseo-desktop", "generation": generation,
            "stateCompatibility": "binary-only", "operations": {operation: {
                "allowed": True, "transactionId": "test-controller", "receiptSha256": "a" * 64,
                "archiveSha256": "b" * 64, "version": "0.16.0-beta.2",
                "bundleSha256": bundle_sha256(target), "previousBundleSha256": bundle_sha256(old),
                "runtimePlugins": expected_managed_plugins()}}}


@pytest.fixture
def qualified(tmp_path):
    old, target = tmp_path / "Paseo.app", tmp_path / "Paseo-local.app"
    make_app(old, updater=True)
    make_app(target)
    (target / "Contents/Resources/managed-release.json").write_text(json.dumps({"schemaVersion": 1, "component": "paseo-desktop"}))
    fake = Fake(tmp_path)
    ctx = plu.Ctx(old, target, tmp_path / "previous.app", tmp_path / "journal", str(tmp_path / "home"), 0, 1, [],
                  runner=fake, sleep=lambda _: None, updater_cache=tmp_path / "cache", shipit_cache=tmp_path / "shipit")
    ctx.native_home = lambda: ctx.home
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
    {"schemaVersion": 1, "state": "held", "generation": 999, "transactionId": "test-controller", "ownerToken": "T" * 43}])
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
    ctx.reservation = {"generation": 1, "transactionId": "test-controller", "ownerToken": "T" * 43}
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
                    "transactionId": "test-controller", "ownerToken": "T" * 43, "recoveryRequired": False}))
            if action == "end":
                assert "T" * 43 not in argv
                assert input_text == "T" * 43 + "\n"
                return plu.Result(0, json.dumps({"schemaVersion": 1, "state": "idle", "generation": 1, "recoveryRequired": False}))
            if action == "verify-offline":
                assert "--home" not in argv
                if not offline:
                    return plu.Result(1, "", "offline status unsupported")
                return plu.Result(0, json.dumps({"schemaVersion": 1, "state": "recovery-required", "generation": 1,
                    "transactionId": "test-controller", "recoveryRequired": True}))
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


@pytest.fixture
def protected_policy(tmp_path, monkeypatch):
    """Virtual protected root: only in-process syscall/account-reader substitution."""
    import types
    import paseo_upgrade_policy as pp
    home = tmp_path / "account"
    folder = home / ".local/state/djbclark-ade/forks"
    folder.mkdir(parents=True)
    for directory in (home, *home.rglob("*")):
        if directory.is_dir():
            directory.chmod(0o700)
    file = folder / "paseo-desktop-policy.json"
    file.write_text('{"schemaVersion":1}')
    file.chmod(0o600)
    original_open = os.open
    def virtual_root(path, flags, *args, **kwargs):
        return original_open(tmp_path if path == "/" else path, flags, *args, **kwargs)
    monkeypatch.setattr(pp.os, "open", virtual_root)
    monkeypatch.setattr(pp.pwd, "getpwuid", lambda uid: types.SimpleNamespace(pw_dir="/account"))
    return pp, file, home


def test_protected_reader_ignores_home_and_accepts_private_stable_file(protected_policy, monkeypatch):
    pp, _, _ = protected_policy
    monkeypatch.setenv("HOME", "/forged/candidate")
    assert pp.read_policy() == {"schemaVersion": 1}


@pytest.mark.parametrize("kind", ["missing", "symlink", "fifo", "hardlink", "public", "parent-public", "parent-link", "duplicate", "malformed", "oversized"])
def test_protected_reader_rejects_unsafe_file(protected_policy, kind):
    pp, file, home = protected_policy
    if kind in ("missing", "symlink", "fifo"):
        file.unlink()
    if kind == "symlink":
        file.symlink_to(home / "candidate.json")
        (home / "candidate.json").write_text('{}')
    elif kind == "fifo":
        os.mkfifo(file, 0o600)
    elif kind == "hardlink":
        os.link(file, file.with_name("other.json"))
    elif kind == "public":
        file.chmod(0o640)
    elif kind == "parent-public":
        file.parent.chmod(0o777)
    elif kind == "parent-link":
        real = file.parent.with_name("real")
        file.parent.rename(real)
        file.parent.symlink_to(real)
    elif kind == "duplicate":
        file.write_text('{"generation":1,"generation":2}')
    elif kind == "malformed":
        file.write_text('{')
    elif kind == "oversized":
        file.write_bytes(b' ' * (1024 * 1024 + 1))
    with pytest.raises(Hold):
        pp.read_policy()


@pytest.mark.parametrize("kind", ["uid", "changed-content", "replaced-file", "replaced-parent"])
def test_protected_reader_rejects_owner_and_read_races(protected_policy, monkeypatch, kind):
    import types
    pp, file, home = protected_policy
    if kind == "uid":
        original = os.fstat
        def wrong_owner(fd):
            result = original(fd)
            import stat
            if stat.S_ISREG(result.st_mode):
                fields = {name: getattr(result, name) for name in dir(result) if name.startswith("st_")}
                fields["st_uid"] = os.getuid() + 1
                return types.SimpleNamespace(**fields)
            return result
        monkeypatch.setattr(pp.os, "fstat", wrong_owner)
    else:
        original = os.fdopen
        class MutatingRead:
            def __init__(self, fd, mode):
                self.file = original(fd, mode)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return self.file.__exit__(*args)
            def fileno(self):
                return self.file.fileno()
            def read(self, count):
                raw = self.file.read(count)
                if kind == "changed-content":
                    file.write_bytes(b'{}')
                elif kind == "replaced-file":
                    other = file.with_name('replacement')
                    other.write_bytes(raw)
                    other.chmod(0o600)
                    os.replace(other, file)
                else:
                    parent = file.parent
                    parent.rename(parent.with_name('moved'))
                    parent.mkdir()
                return raw
        monkeypatch.setattr(pp.os, "fdopen", MutatingRead)
    with pytest.raises(Hold):
        pp.read_policy()


def test_end_lost_ack_records_uncertain_and_never_rolls_back(qualified):
    ctx, fake, _ = qualified
    native = native_runner(ctx, fake)
    def lost_end(argv, timeout=60, input_text=None):
        if "end" in argv and "maintenance" in argv:
            # Native may already have committed idle tombstone before response loss.
            assert json.loads((ctx.state_dir / "last-run.json").read_text())["phase"] == "release-intent"
            native(argv, timeout, input_text)
            return plu.Result(1, "", "lost acknowledgment")
        return native(argv, timeout, input_text)
    ctx.runner = lost_end
    assert plu.do_apply(ctx, plu.parse(["--apply", "--yes"])) == 4
    assert ctx.swapped and not ctx.swapped_back and ctx.backup.exists()
    assert json.loads((ctx.state_dir / "last-run.json").read_text())["phase"] == "release-uncertain"
    assert sum(c[0] == "open" for c in fake.calls) == 1


def test_noncanonical_home_cannot_use_offline_authority(qualified):
    ctx, fake, _ = qualified
    ctx.native_home = lambda: "/real/account/.paseo"
    plu.authorize(ctx, capture=True)
    with pytest.raises(Hold, match="canonical"):
        plu.maintenance(ctx, "begin")
    assert not touched(fake)


def test_shared_desktop_python_typescript_unicode_parity(tmp_path):
    import subprocess
    import sys
    fixture = Path(__file__).parent / "fixtures/paseo_bundle_hash_v1"
    (tmp_path / "empty").mkdir(mode=0o755)
    (tmp_path / "empty").chmod(0o755)
    for name in ["é.txt", "😀.txt", "\uE000.txt", "manifest.json"]:
        (tmp_path / name).write_text(name, encoding="utf-8")
        (tmp_path / name).chmod(0o644)
    (tmp_path / "link").symlink_to("é.txt")
    reference = subprocess.run([sys.executable, str(fixture / "bundle-hash-v1.py"), str(tmp_path)], capture_output=True, text=True, check=True).stdout.strip()
    code = "import {bundleSha256} from " + json.dumps((fixture / "managed-bundle.ts").resolve().as_uri()) + "; console.log(bundleSha256(process.argv[1]));"
    typescript = subprocess.run(["node", "--experimental-strip-types", "--input-type=module", "-e", code, str(tmp_path)], capture_output=True, text=True, check=True).stdout.strip()
    assert bundle_sha256(tmp_path) == reference == typescript
    original = reference
    (tmp_path / "manifest.json").write_text("changed", encoding="utf-8")
    assert bundle_sha256(tmp_path) != original


@pytest.mark.parametrize("when", ["begin", "quit", "swapped", "open"])
def test_revocation_after_reservation_at_each_mutation_boundary(qualified, monkeypatch, when):
    ctx, fake, value = qualified
    native = native_runner(ctx, fake)
    def revoke():
        value["operations"]["activate"]["allowed"] = False
    def runner(argv, timeout=60, input_text=None):
        result = native(argv, timeout, input_text)
        if (when == "begin" and "maintenance" in argv and "begin" in argv) or (when == "quit" and argv[0] == "osascript" and "to quit" in argv[2]) or (when == "open" and argv[0] == "open"):
            revoke()
        return result
    ctx.runner = runner
    save = plu.save_state
    def journal(c, name="last-run.json", **data):
        save(c, name, **data)
        if when == "swapped" and data.get("phase") == "swapped":
            revoke()
    monkeypatch.setattr(plu, "save_state", journal)
    assert plu.do_apply(ctx, plu.parse(["--apply", "--yes"])) == 4
    assert ctx.reservation and not ctx.swapped_back
    if when in ("begin", "quit"):
        assert not ctx.swapped and ctx.staged.exists()
    if when != "open":
        assert not any(c[0] == "open" for c in fake.calls)
    if when == "begin":
        assert not touched(fake)


@pytest.mark.parametrize("failure", ["refused", "lost-response", "interrupt"])
def test_begin_failure_never_mints_fallback_permission(qualified, failure):
    ctx, fake, _ = qualified
    original = fake.__call__
    def runner(argv, timeout=60):
        if "maintenance" in argv and "begin" in argv:
            if failure == "interrupt":
                raise KeyboardInterrupt()
            return plu.Result(1, "", "begin refused") if failure == "refused" else plu.Result(0, "invalid-json")
        return original(argv, timeout)
    ctx.runner = runner
    assert plu.do_apply(ctx, plu.parse(["--apply", "--yes"])) == 4
    assert not touched(fake) and ctx.installed.exists() and ctx.staged.exists()
    assert not ctx.reservation
    assert json.loads((ctx.state_dir / "last-attempt.json").read_text())["phase"] == "recovery-required"


@pytest.mark.parametrize("mutation", [lambda d: d.update(generation=2), lambda d: d.update(transactionId="other"), lambda d: d.update(recoveryRequired=False), lambda d: d.update(state="idle"), lambda d: d.update(schemaVersion=True)])
def test_offline_proof_must_match_exact_native_hold(qualified, mutation):
    ctx, fake, _ = qualified
    plu.authorize(ctx, capture=True)
    ctx.reservation = {"generation": 1, "transactionId": "test-controller", "ownerToken": "T" * 43}
    fake.daemon_up = False
    original = fake.__call__
    def runner(argv, timeout=60):
        if "verify-offline" in argv:
            value = {"schemaVersion": 1, "state": "recovery-required", "generation": 1,
                     "transactionId": "test-controller", "recoveryRequired": True}
            mutation(value)
            return plu.Result(0, json.dumps(value))
        return original(argv, timeout)
    ctx.runner = runner
    with pytest.raises(Hold):
        plu.swap_in(ctx)
    assert not ctx.swapped and ctx.staged.exists() and ctx.installed.exists()


def test_loaded_daemon_version_mismatch_is_not_runtime_verified(qualified):
    ctx, fake, _ = qualified
    native = native_runner(ctx, fake)
    def runner(argv, timeout=60, input_text=None):
        result = native(argv, timeout, input_text)
        if "daemon" in argv and "status" in argv and ctx.swapped:
            data = json.loads(result.out)
            data["daemonVersion"] = "different-loaded-code"
            return plu.Result(0, json.dumps(data))
        return result
    ctx.runner = runner
    assert plu.do_apply(ctx, plu.parse(["--apply", "--yes"])) == 4
    assert ctx.swapped and not ctx.swapped_back and ctx.backup.exists()
    assert json.loads((ctx.state_dir / "last-run.json").read_text())["phase"] == "recovery-required"


@pytest.mark.parametrize("mutation", [
    lambda op: op.pop("runtimePlugins"), lambda op: op.update(runtimePlugins=None),
    lambda op: op.update(runtimePlugins={}),
    lambda op: op["runtimePlugins"].append(copy.deepcopy(op["runtimePlugins"][0])),
    lambda op: op["runtimePlugins"][0].update(pluginId=""),
    lambda op: op["runtimePlugins"][0].update(snapshotSha256="A" * 64),
    lambda op: op["runtimePlugins"][0].update(serverBundleSha256="bad"),
    lambda op: op["runtimePlugins"][0].update(activationGeneration=True),
    lambda op: op["runtimePlugins"][0].update(activationGeneration=0),
    lambda op: op["runtimePlugins"][0].update(sourcePath="relative/plugin"),
    lambda op: op["runtimePlugins"][0].update(snapshotRoot="/"),
    lambda op: op["runtimePlugins"][0].update(sourcePath="/immutable/ade/../elsewhere"),
    lambda op: op["runtimePlugins"][0].update(sourcePath="/immutable/ade/./ade-yolo"),
    lambda op: op["runtimePlugins"][0].update(sourcePath="/immutable/ade/ade-yolo/"),
    lambda op: op["runtimePlugins"][0].update(sourcePath="//immutable/ade/ade-yolo"),
    lambda op: op["runtimePlugins"][0].update(sourcePath="/outside/ade-yolo"),
    lambda op: op["runtimePlugins"][0].update(snapshotRoot="/immutable/ade\x00"),
    lambda op: op["runtimePlugins"][0].update(snapshotRoot="/immutable/\ud800"),
])
def test_runtime_cohort_grant_schema_holds_before_mutation(qualified, mutation):
    ctx, fake, value = qualified
    mutation(value["operations"]["activate"])
    assert plu.do_apply(ctx, plu.parse(["--apply", "--yes", "--want-broken", "--allow-terminals"])) == 4
    assert not touched(fake)


def altered_plugin_runner(ctx, fake, mutate):
    native = native_runner(ctx, fake)
    def runner(argv, timeout=60, input_text=None):
        result = native(argv, timeout, input_text)
        if "plugin" in argv and "ls" in argv and ctx.swapped:
            entries = json.loads(result.out)
            mutate(entries)
            return plu.Result(0, json.dumps(entries))
        return result
    return runner


@pytest.mark.parametrize("mutation", [
    lambda p: p.pop("loaded"), lambda p: p.update(loaded=[]),
    lambda p: p.update(enabled="true"), lambda p: p.update(status="disabled"),
    lambda p: p.update(path="/mutable/plugin"),
    lambda p: p["loaded"].update(pluginId="other"),
    lambda p: p["loaded"].update(sourcePath="/mutable/plugin"),
    lambda p: p["loaded"].update(snapshotRoot="/other/snapshot"),
    lambda p: p["loaded"].update(snapshotSha256="0" * 64),
    lambda p: p["loaded"].update(serverBundleSha256="0" * 64),
    lambda p: p["loaded"].update(activationGeneration=8),
    lambda p: p["loaded"].update(activationGeneration=True),
    lambda p: p["loaded"].pop("pid"), lambda p: p["loaded"].update(pid=0),
    lambda p: p["loaded"].update(pid=True), lambda p: p["loaded"].update(pid="501"),
    lambda p: p["loaded"].update(processStartToken=""),
    lambda p: p["loaded"].update(processStartToken="has whitespace"),
    lambda p: p["loaded"].update(startedAt="not-a-time"),
    lambda p: p["loaded"].update(startedAt="2026-11-18T12:00:00"),
])
def test_missing_or_mismatched_loaded_receipt_holds_without_end(qualified, mutation):
    ctx, fake, _ = qualified
    ctx.runner = altered_plugin_runner(ctx, fake, lambda rows: mutation(rows[0]))
    assert plu.do_apply(ctx, plu.parse(["--apply", "--yes", "--want-broken"])) == 4
    assert ctx.swapped and not ctx.swapped_back and ctx.backup.exists() and ctx.reservation
    assert json.loads((ctx.state_dir / "last-run.json").read_text())["phase"] == "recovery-required"


@pytest.mark.parametrize("kind", ["unrelated-substitute", "duplicate-entry"])
def test_unrelated_or_duplicate_entries_cannot_fulfill_enrolled_cohort(qualified, kind):
    ctx, fake, _ = qualified
    def mutate(entries):
        if kind == "unrelated-substitute":
            entries[0]["id"] = "unmanaged-other"
        else:
            entries.append(copy.deepcopy(entries[0]))
    ctx.runner = altered_plugin_runner(ctx, fake, mutate)
    assert plu.do_apply(ctx, plu.parse(["--apply", "--yes"])) == 4
    assert ctx.reservation and not ctx.swapped_back


def test_explicit_empty_enrolled_cohort_is_a_controller_decision(qualified):
    ctx, fake, value = qualified
    value["operations"]["activate"]["runtimePlugins"] = []
    ctx.runner = native_runner(ctx, fake)
    assert plu.do_apply(ctx, plu.parse(["--apply", "--yes"])) == 0


def test_unmanaged_plugins_do_not_need_managed_receipts(qualified):
    ctx, fake, _ = qualified
    ctx.runner = altered_plugin_runner(ctx, fake, lambda rows: rows.append({"id": "unmanaged", "enabled": True, "status": "running", "path": "/unmanaged"}))
    assert plu.do_apply(ctx, plu.parse(["--apply", "--yes"])) == 0


def test_new_process_observations_are_checked_but_not_precomputed(qualified):
    ctx, fake, _ = qualified
    def mutate(entries):
        entries[0]["loaded"].update(pid=9001, processStartToken="fresh-process", startedAt="2026-11-18T13:00:00Z")
    ctx.runner = altered_plugin_runner(ctx, fake, mutate)
    assert plu.do_apply(ctx, plu.parse(["--apply", "--yes"])) == 0
    record = json.loads((ctx.state_dir / "last-run.json").read_text())
    observed = record["runtimePluginObservations"]
    assert observed[0]["pid"] == 9001 and observed[0]["processStartTokenSha256"] == hashlib.sha256(b"fresh-process").hexdigest()
    assert "fresh-process" not in json.dumps(record)


def test_runtime_receipts_checked_again_before_end(qualified):
    ctx, fake, _ = qualified
    native = native_runner(ctx, fake)
    count, actions = {"plugins": 0}, []
    def runner(argv, timeout=60, input_text=None):
        if "maintenance" in argv:
            actions.append(argv[argv.index("maintenance") + 1])
        result = native(argv, timeout, input_text)
        if "plugin" in argv and "ls" in argv:
            count["plugins"] += 1
            if count["plugins"] == 4:
                rows = json.loads(result.out)
                rows[0].pop("loaded")
                return plu.Result(0, json.dumps(rows))
        return result
    ctx.runner = runner
    assert plu.do_apply(ctx, plu.parse(["--apply", "--yes"])) == 4
    assert "end" not in actions and ctx.reservation and not ctx.swapped_back
    assert json.loads((ctx.state_dir / "last-run.json").read_text())["phase"] == "recovery-required"


def test_recovery_receipt_mismatch_cannot_claim_success(qualified):
    ctx, fake, value = qualified
    native = native_runner(ctx, fake, fail_runtime=True, recover=True, value=value)
    def runner(argv, timeout=60, input_text=None):
        result = native(argv, timeout, input_text)
        if "plugin" in argv and "ls" in argv and ctx.swapped_back:
            rows = json.loads(result.out)
            rows[0]["loaded"]["activationGeneration"] = 6
            return plu.Result(0, json.dumps(rows))
        return result
    ctx.runner = runner
    assert plu.do_apply(ctx, plu.parse(["--apply", "--yes"])) == 4
    assert ctx.swapped_back and ctx.reservation and ctx.staged.exists()
    assert json.loads((ctx.state_dir / "last-attempt.json").read_text())["phase"] == "recovery-required"
