#!/usr/bin/env python3
"""Store an OVH credential from the clipboard, with shape validation.

Reads the value on stdin (pipe `pbpaste` into this), validates that it looks like
the named OVH credential, and only then stores it via sudo-secretspec. One process
does the classify and the forward, so the clipboard race in
sudo-secretspec/SKILL.md cannot store whatever arrived second.

Usage:  pbpaste | python3 ovh-store.py NAME
Prints only a length and a boolean shape verdict - never the value.
"""
import re
import subprocess
import sys

# OVH AK/AS/CK are alphanumeric; the docs' examples are 16 and 32 characters.
SHAPES = {
    "OVH_APPLICATION_KEY": (re.compile(r"^[A-Za-z0-9]{16}$"), "16 alphanumeric"),
    "OVH_APPLICATION_SECRET": (re.compile(r"^[A-Za-z0-9]{32}$"), "32 alphanumeric"),
    "OVH_CONSUMER_KEY": (re.compile(r"^[A-Za-z0-9]{32}$"), "32 alphanumeric"),
    "OVH_ENDPOINT": (re.compile(r"^ovh-(us|eu|ca)$"), "ovh-us|ovh-eu|ovh-ca"),
}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in SHAPES:
        print(f"usage: pbpaste | {sys.argv[0]} NAME", file=sys.stderr)
        print(f"known names: {', '.join(sorted(SHAPES))}", file=sys.stderr)
        return 2

    name = sys.argv[1]
    pattern, described = SHAPES[name]
    value = sys.stdin.read().strip()

    if not value:
        print(f"REFUSED {name}: nothing on stdin (is the clipboard empty?)", file=sys.stderr)
        return 1
    if not pattern.match(value):
        # Do not try to salvage it: a masked UI rendering looks like a key and is not one.
        print(
            f"REFUSED {name}: value is not the expected shape ({described}). "
            f"len={len(value)} longest-alnum-run={max((len(m) for m in re.findall(r'[A-Za-z0-9]+', value)), default=0)}. "
            "Re-copy from OVH and try again.",
            file=sys.stderr,
        )
        return 1

    proc = subprocess.run(
        ["sudo-secretspec", "set", name, "--reason", "store the OVH API credential for the VPS instance"],
        input=value,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        print(f"FAILED {name}: {proc.stderr.strip()}", file=sys.stderr)
        return proc.returncode

    # Length only, never the value.
    print(f"OK {name}: stored, len={len(value)}, shape={described}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
