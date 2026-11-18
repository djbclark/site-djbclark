# Shared bundle hash contract fixture

Snapshots from Paseo desktop worker source at fork/qualified-desktop-updates,
commit 82a8e05dde4c068d96e7eeaeee40562da404ee91, on 2026-11-18:
`packages/desktop/src/features/managed-bundle.ts` and
`packages/desktop/src/features/test-utils/bundle-hash-v1.py`.
Upstream repository: https://github.com/djbclark/paseo (Apache-2.0).
These are test-only snapshots, not installed helpers. The test builds the same
Unicode, empty-directory and symlink tree used by the desktop Vitest parity test,
and compares installer Python, desktop Python reference, and actual TypeScript.
Refresh alongside contract changes; do not silently replace with a Python mirror.
