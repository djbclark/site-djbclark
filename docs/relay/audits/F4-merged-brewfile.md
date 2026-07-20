# F4 — Merged-Brewfile projection + flock (2026-07-20)

## What landed

| Piece | Path |
| --- | --- |
| Fragment sources (SoT) | `brew/fragments/{site,stayturgid}.yml` |
| Projection | `generated/Merged-Brewfile` |
| Projector + diff | `bin/project_merged_brewfile.py` |
| Flock wrapper | `bin/brew_flock.py` (`fcntl.flock`; macOS has no util-linux flock by default) |
| Just recipes | `brew-project`, `brew-diff`, `brew-lock`; `goose-apply` holds the lock |
| Docs | `brew/README.md`, root `README.md` § F4 |
| Registry | `registry/paths.yml` claims `brew/**` + `generated/Merged-Brewfile` |

## Verification (m1-air, 2026-07-20)

```text
just brew-project
  → created/unchanged generated/Merged-Brewfile (2 taps, 19 formulae, 2 casks)
just brew-project   # second run
  → unchanged (idempotent)
just brew-diff
  → exit 0; claimed present 23; missing 0; live-only ~160 (informational)
bin/registry_lint.py → OK
```

Flock evidence (`SITE_BREW_LOCK=/tmp/site-djbclark-brew-f4-test.lock`):

| Scenario | Result |
| --- | --- |
| Holder: `brew_flock.py -- sleep 8` | held lock |
| Contender: `--nonblock -- echo` | **exit 75** (EX_TEMPFAIL); did not run |
| Contender: `--timeout 1 -- echo` | **exit 124**; did not run |
| After holder exit: `--nonblock -- echo LOCK_FREE` | **exit 0** |
| `just brew-lock --nonblock -- true` | exit 0 when free |

No `brew install` / `brew uninstall` / `brew bundle cleanup` was run.

## Diff policy

- Claimed-missing → would be install gaps (none on this host after python@N match).
- Live-only → personal/tooling packages + F2 remove-candidates still installed;
  **not** auto-cleaned.
- `python` claim matches live `python@*` keg names.

## Rollback

1. Revert justfile F4 block + goose-apply flock wrapper.
2. Remove `generated/Merged-Brewfile`, `brew/`, `bin/project_merged_brewfile.py`,
   `bin/brew_flock.py`, this audit, path claims.
3. No package state to undo (F4 is project/diff/lock only).

## Residuals (unchanged)

- F2 operator gates: `human/F2-BREW-SERVICES-DECISIONS.md`
- F3 Immich app tree missing; labels disabled
- E5 mini/VPS offline_unprovisioned
