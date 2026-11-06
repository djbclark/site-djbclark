#!/usr/bin/env python3
"""Start bottom in a private tmux server with a config, print what it drew.

    preview.py [--config FILE] [--bin PATH] [--width N] [--height N]
               [--keys KEYS] [--seconds S] [-- EXTRA_BTM_ARGS...]

Defaults: the fork build ~/.local/bin/btm-mt, ~/.config/bottom/bottom.toml,
140x30, process widget expanded (`-e --default_widget_type proc`), 4 s.
--keys is sent after startup (e.g. `t` for tree mode, `P` for name/command);
letters only, no Enter.

It uses its own tmux server (own socket, no user tmux config), so the user's
tmux sessions are never touched, and kills that server when done. The config
must already exist and parse as TOML: bottom writes a default config to any
`-C` path it cannot read, so a mistyped path would create or overwrite a file.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=Path.home() / ".config/bottom/bottom.toml")
    parser.add_argument("--bin", type=Path, default=Path.home() / ".local/bin/btm-mt")
    parser.add_argument("--width", type=int, default=140)
    parser.add_argument("--height", type=int, default=30)
    parser.add_argument("--keys", default="")
    parser.add_argument("--seconds", type=float, default=4.0)
    parser.add_argument("extra", nargs="*")
    args = parser.parse_args()

    if shutil.which("tmux") is None:
        print("tmux not found", file=sys.stderr)
        return 2
    if not args.bin.is_file():
        print(f"binary not found: {args.bin}", file=sys.stderr)
        return 2
    try:
        tomllib.loads(args.config.read_text())
    except (OSError, ValueError) as exc:
        print(f"refusing to start: {args.config} is not a readable TOML file ({exc})", file=sys.stderr)
        return 2

    sock_dir = Path(tempfile.mkdtemp(prefix="btm-preview-"))

    def tmux(*targs: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["tmux", "-S", str(sock_dir / "sock"), "-f", "/dev/null", *targs],
            capture_output=True,
            text=True,
            check=False,
        )

    cmd = [str(args.bin), "-C", str(args.config), "-e", "--default_widget_type", "proc", *args.extra]
    try:
        started = tmux(
            "new-session", "-d", "-s", "preview", "-x", str(args.width), "-y", str(args.height), *cmd
        )
        if started.returncode != 0:
            print(started.stderr.strip(), file=sys.stderr)
            return 2
        time.sleep(args.seconds)
        if args.keys:
            tmux("send-keys", "-t", "preview", *list(args.keys))
            time.sleep(2)
        shot = tmux("capture-pane", "-t", "preview", "-p")
        if shot.returncode != 0:
            print("btm exited before it could be captured (bad config or flag?)", file=sys.stderr)
            return 1
        print(shot.stdout, end="")
    finally:
        tmux("kill-server")
        shutil.rmtree(sock_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
