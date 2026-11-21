"""Contract v1 reference encoder used only by cross-language parity tests."""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

root = Path(sys.argv[1]).resolve(strict=True)
rows = []
observed = []

def stamp(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns, value.st_ctime_ns)

def visit(file, relative):
    before = file.lstat()
    mode = stat.S_IMODE(before.st_mode) & 0o777
    if file.is_symlink():
        file.resolve(strict=True).relative_to(root)
        target = os.readlink(file)
        target.encode("utf-8", errors="strict")
        rows.append((relative, ["l", relative, mode, target]))
    elif stat.S_ISDIR(before.st_mode):
        if relative:
            rows.append((relative, ["d", relative, mode]))
        for child in file.iterdir():
            name = child.name
            name.encode("utf-8", errors="strict")
            visit(child, relative + "/" + name if relative else name)
    elif stat.S_ISREG(before.st_mode):
        data = file.read_bytes()
        if len(data) != before.st_size:
            raise ValueError("unstable file")
        rows.append((relative, ["f", relative, mode, len(data), hashlib.sha256(data).hexdigest()]))
    else:
        raise ValueError("special entry")
    if stamp(file.lstat()) != stamp(before):
        raise ValueError("unstable entry")
    observed.append((file, before))

visit(root, "")
for file, before in observed:
    if stamp(file.lstat()) != stamp(before):
        raise ValueError("unstable snapshot")
encoded = "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for _, row in sorted(rows))
print(hashlib.sha256(encoded.encode("utf-8", errors="strict")).hexdigest())
