# Site Brew claims — Merged-Brewfile (Phase F4)

Step1 §4.3: each stack declares formulae in vars; the **site** projects one
merged annotated Brewfile for visibility and (later) safe `brew bundle cleanup`.
Concurrent brew mutations are serialized via the site justfile flock wrapper.

## Layout

| Path | Role |
| --- | --- |
| `brew/fragments/*.yml` | **Source of truth** — stack-owned package claims (hand-edited) |
| `generated/Merged-Brewfile` | **Projection** — generated; do not hand-edit |
| `bin/project_merged_brewfile.py` | Generate + diff against live snapshot |
| `bin/brew_flock.py` | Portable `flock`-style exclusive lock (fcntl) |

## Recipes

```bash
just brew-project          # write generated/Merged-Brewfile from fragments
just brew-diff             # project then compare to ~/system-state/Brewfile
just brew-diff --strict    # exit 1 if any claimed package is missing on live
just brew-lock -- <cmd…>   # run a command holding the site brew lock
just goose-apply           # brew-touching; already wraps brew install under lock
```

## Diff semantics

- **claimed-missing**: in Merged-Brewfile, not in the live snapshot (install gap).
- **live-only**: in the live snapshot, not claimed by any fragment (informational;
  includes personal apps and F2 remove-candidates still on the machine).
- Diff is **read-only**. It never runs `brew bundle cleanup` or uninstalls.
  Destructive cleanup requires operator sign-off (see
  `human/F2-BREW-SERVICES-DECISIONS.md`).

Live snapshot path (first existing wins):

1. `$SITE_BREW_SNAPSHOT` (override)
2. `~/system-state/Brewfile` (system-state-backup mirror)
3. `/opt/homebrew/var/system-state/Brewfile` (arm64 canonical)
4. `/usr/local/var/system-state/Brewfile` (Intel)

## Flock lock

Lock file default: `/tmp/site-djbclark-brew.lock`  
Override: `SITE_BREW_LOCK=/path/to/lock just brew-lock -- …`

macOS has no util-linux `flock(1)` by default; `bin/brew_flock.py` uses
`fcntl.flock` (same advisory lock semantics). If an external `flock` binary is
on `PATH`, the wrapper still uses Python for consistent wait messaging.

## Rollback

1. Remove recipes from the root `justfile` (search for `F4` / `brew-project`).
2. Delete `generated/Merged-Brewfile` and optionally `brew/` + the two `bin/*`
   scripts.
3. Drop the `~/ops/site-djbclark/generated/Merged-Brewfile` path claim from
   `registry/paths.yml` if you remove the projection entirely.
4. No brew packages are installed or removed by F4 itself.

## Adding a claim

1. Edit the right fragment under `brew/fragments/` (`site.yml`,
   `stayturgid.yml`, or a new `*.yml` with `stack:` set).
2. `just brew-project && just brew-diff`
3. Commit fragments + regenerated `generated/Merged-Brewfile`.
