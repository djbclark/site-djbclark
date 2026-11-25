### Changed
- `bin/fleet-watch`: removed the duplicate `ade-subagent-stalls --notify` invocation ahead of the macOS `com.djbclark.ade-agent-sweep` `launchd` cutover (`djbclark/djbclark-ade#988`), preserving the shared notification ledger (#315)
