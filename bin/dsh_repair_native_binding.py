#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Repair dsh's node-addon-require-builtin optional platform binding.

pnpm's global link farm sometimes leaves ``node-addon-native-custom-loader``
unable to ``require('node-addon-require-builtin-<platform>')`` even when the
optional package is installed next to ``node-addon-require-builtin``. Every
``dsh`` profile boot then dies with a multi-KB nested ``attempts[]`` dump
(``No usable native binding found for node-addon-require-builtin-…``).

This script:

1. Locates the real ``@deepseek-ai/dsh`` ``bin.js`` behind the pnpm/npm shim.
2. Probes ``getBindingInfo()``. Exit 0 if a binding already loads.
3. Otherwise symlinks the platform optional package into the loader's own
   ``node_modules/`` (the layout a project-style pnpm install creates) and
   re-probes.

Exit codes:
  0  binding already OK, or repaired successfully
  1  dsh / node / binding missing or repair failed
  2  dsh not on PATH (nothing to repair; callers may treat as skip)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _which_dsh() -> Path | None:
    found = shutil.which("dsh")
    return Path(found) if found else None


def _resolve_bin_js(shim: Path) -> Path | None:
    """Follow the pnpm cmd-shim comment or a plain symlink to bin.js.

    Always return the realpath. pnpm's global layout puts a symlink at
    ``…/global/v11/<hash>/node_modules/@deepseek-ai/dsh`` → the store link
    farm; ``createRequire`` from the non-real path cannot see sibling deps
    (``node-addon-require-builtin``, ``cordis-plugin-loader``, …), so the
    probe must start from the resolved store path.
    """
    candidates: list[Path] = []
    try:
        text = shim.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    for line in text.splitlines():
        if line.startswith("# cmd-shim-target="):
            candidates.append(Path(line.split("=", 1)[1].strip()))
            break
    candidates.append(shim)
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_file() and resolved.suffix == ".js":
            return resolved
    return None


def _node_probe_and_repair(bin_js: Path) -> int:
    """Run the Node-side probe/repair against bin_js. Return its exit status."""
    # Keep the JS inline so the helper stays a single file. argv[1] is bin.js.
    script = r"""
const { createRequire } = require("node:module");
const {
  mkdirSync,
  symlinkSync,
  lstatSync,
  unlinkSync,
  existsSync,
  realpathSync,
} = require("node:fs");
const { dirname, join } = require("node:path");

const binjs = process.argv[1];
const req = createRequire(binjs);

function loadInfo() {
  return req("node-addon-require-builtin").getBindingInfo();
}

let builtinMain;
try {
  builtinMain = req.resolve("node-addon-require-builtin");
} catch (err) {
  console.error(
    "[dsh-repair] cannot resolve node-addon-require-builtin from",
    binjs + ":",
    err.message,
  );
  process.exit(1);
}

try {
  const info = loadInfo();
  if (info && info.bindingSource) {
    console.log(
      "[dsh-repair] ok:",
      info.optionalPackageName || info.bindingSource,
      `(${info.bindingSource})`,
    );
    process.exit(0);
  }
} catch (_) {
  // Fall through to repair.
}

const builtinReq = createRequire(builtinMain);
const pkgName = `node-addon-require-builtin-${process.platform}-${process.arch}`;
let platformPkg;
try {
  platformPkg = dirname(builtinReq.resolve(`${pkgName}/package.json`));
} catch (err) {
  console.error(
    `[dsh-repair] optional package ${pkgName} is not installed next to node-addon-require-builtin:`,
    err.message,
  );
  process.exit(1);
}

const loaderMain = builtinReq.resolve("node-addon-native-custom-loader");
// loader main is …/node-addon-native-custom-loader/lib/index.js
const loaderPkg = dirname(dirname(loaderMain));
const destDir = join(loaderPkg, "node_modules");
const dest = join(destDir, pkgName);
mkdirSync(destDir, { recursive: true });

const want = realpathSync(platformPkg);
if (existsSync(dest)) {
  try {
    if (lstatSync(dest).isSymbolicLink() && realpathSync(dest) === want) {
      console.error(
        "[dsh-repair] symlink already points at the platform package but require still fails",
      );
      process.exit(1);
    }
  } catch (_) {
    // Replace a broken/wrong link or directory entry below.
  }
  unlinkSync(dest);
}
symlinkSync(want, dest);

let info;
try {
  // Clear require cache for the builtin entry so the loader runs again.
  delete require.cache[builtinMain];
  info = loadInfo();
} catch (err) {
  console.error("[dsh-repair] still unloadable after relink:", err.message);
  process.exit(1);
}
if (!info || !info.bindingSource) {
  console.error("[dsh-repair] relinked but getBindingInfo() returned nothing");
  process.exit(1);
}
console.log(
  `[dsh-repair] repaired ${pkgName} -> ${info.bindingSource} (${info.abi || "?"})`,
);
"""
    node = shutil.which("node")
    if not node:
        print("[dsh-repair] node not on PATH", file=sys.stderr)
        return 1
    proc = subprocess.run(
        [node, "-e", script, str(bin_js)],
        check=False,
    )
    return int(proc.returncode)


def main() -> int:
    shim = _which_dsh()
    if shim is None:
        print("[dsh-repair] dsh not on PATH; nothing to repair", file=sys.stderr)
        return 2
    bin_js = _resolve_bin_js(shim)
    if bin_js is None:
        print(f"[dsh-repair] could not resolve bin.js from {shim}", file=sys.stderr)
        return 1
    # Ensure the shim's directory (and thus typical agent PATH) wins for node.
    env_path = os.environ.get("PATH", "")
    print(f"[dsh-repair] probing via {bin_js}")
    return _node_probe_and_repair(bin_js)


if __name__ == "__main__":
    sys.exit(main())
