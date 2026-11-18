"""Managed Paseo policy and deterministic bundle identity; no CLI authority overrides."""
import hashlib
import json
import os
import pwd
import re
import stat
from pathlib import Path


class Hold(Exception):
    """Authorization or identity uncertain; retain artifacts and reservation."""


def fingerprint(s):
    return (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def bundle_sha256(root):
    """Shared bundle JSONL v1. Two complete observations reject unstable closure."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise Hold("bundle root must be a directory")
    base = root.resolve()

    def observe():
        records, metadata = [], {}
        def walk(directory):
            before = directory.lstat()
            metadata[str(directory)] = fingerprint(before)
            for p in sorted(directory.iterdir(), key=lambda p: p.name):
                rel = p.relative_to(root).as_posix()
                rel.encode("utf-8", errors="strict")
                s = p.lstat()
                metadata[str(p)] = fingerprint(s)
                mode = stat.S_IMODE(s.st_mode) & 0o777
                if stat.S_ISLNK(s.st_mode):
                    target = os.readlink(p)
                    target.encode("utf-8", errors="strict")
                    if not p.resolve().is_relative_to(base):
                        raise Hold("bundle link escapes closure")
                    records.append(["l", rel, mode, target])
                elif stat.S_ISDIR(s.st_mode):
                    records.append(["d", rel, mode])
                    walk(p)
                elif stat.S_ISREG(s.st_mode):
                    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                    with os.fdopen(fd, "rb") as f:
                        if fingerprint(os.fstat(f.fileno())) != fingerprint(s):
                            raise Hold("bundle changed before read")
                        h, size = hashlib.sha256(), 0
                        for chunk in iter(lambda: f.read(1024 * 1024), b""):
                            size += len(chunk)
                            h.update(chunk)
                        if size != s.st_size or fingerprint(os.fstat(f.fileno())) != fingerprint(s):
                            raise Hold("bundle changed during read")
                    records.append(["f", rel, mode, size, h.hexdigest()])
                else:
                    raise Hold("bundle contains special file")
                if fingerprint(p.lstat()) != fingerprint(s):
                    raise Hold("bundle changed during traversal")
            if fingerprint(directory.lstat()) != fingerprint(before):
                raise Hold("bundle directory changed")
        walk(root)
        records.sort(key=lambda entry: entry[1])
        return records, metadata
    try:
        first, metadata = observe()
        second, current = observe()
        if first != second or metadata != current:
            raise Hold("bundle closure changed")
        return hashlib.sha256(b"".join((json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8") for r in first)).hexdigest()
    except (OSError, ValueError, UnicodeError, RuntimeError) as exc:
        raise Hold("cannot establish stable bundle closure") from exc


def read_policy():
    """Fixed real-account path, verified parents and regular owned private file."""
    path = Path(pwd.getpwuid(os.getuid()).pw_dir) / ".local/state/djbclark-ade/forks/paseo-desktop-policy.json"
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
            s = os.fstat(fd)
            if s.st_uid not in (0, os.getuid()) or s.st_mode & 0o022:
                raise Hold("unprotected policy parent")
        leaf = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(leaf, "rb") as f:
            s = os.fstat(f.fileno())
            if not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid() or s.st_mode & 0o077:
                raise Hold("unprotected policy file")
            raw = f.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024 or fingerprint(s) != fingerprint(os.fstat(f.fileno())):
                raise Hold("unstable policy file")
        return json.loads(raw)
    except (OSError, ValueError) as exc:
        raise Hold("protected controller policy unavailable") from exc
    finally:
        os.close(fd)


def grant(policy, operation):
    if not isinstance(policy, dict) or type(policy.get("schemaVersion")) is not int or policy["schemaVersion"] != 1 or policy.get("component") != "paseo-desktop":
        raise Hold("invalid policy schema")
    if type(policy.get("generation")) is not int or policy["generation"] <= 0 or policy.get("stateCompatibility") != "binary-only":
        raise Hold("policy generation/state compatibility denied")
    operations = policy.get("operations")
    op = operations.get(operation) if isinstance(operations, dict) else None
    if not isinstance(op, dict) or op.get("allowed") is not True:
        raise Hold("operation not authorized")
    for key in ("transactionId", "version"):
        if not isinstance(op.get(key), str) or not op[key].strip():
            raise Hold("invalid policy operation")
    for key in ("receiptSha256", "bundleSha256", "previousBundleSha256") + (("archiveSha256",) if operation == "activate" else ()):
        if not isinstance(op.get(key), str) or not re.fullmatch("[0-9a-f]{64}", op[key]):
            raise Hold("invalid policy digest")
    return op


def marker(bundle):
    try:
        value = json.loads((bundle / "Contents/Resources/managed-release.json").read_text())
    except (OSError, ValueError) as exc:
        raise Hold("managed candidate marker missing") from exc
    if value != {"schemaVersion": 1, "component": "paseo-desktop"} or type(value.get("schemaVersion")) is not int:
        raise Hold("invalid managed candidate marker")
