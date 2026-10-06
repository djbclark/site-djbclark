# roles/launchd_path

Keeps launchd's per-user `PATH` equal to the operator's login-shell `PATH`, so
launchd jobs and apps launched from the Dock find the same tools a terminal does.

launchd never reads `~/.bashrc`. Jobs get the `PATH` stored with
`launchctl config user path` (in
`/private/var/db/com.apple.xpc.launchd/config/user.plist`, key
`PathEnvironmentVariable`), or `/usr/bin:/bin:/usr/sbin:/sbin` if none is stored.
The old `/etc/launchd.conf` mechanism has been gone since macOS 10.10.

## Pieces

| Piece | What it does |
|---|---|
| `bin/launchd-path-sync` | `desired` prints the PATH a clean `$SHELL -lic` sets, deduplicated; `status` compares it with the stored value (exit 3 = out of sync); `apply` stores it through the applier. |
| `files/launchd-path-apply` | The only privileged step. Root-owned at `/usr/local/libexec/launchd-path-apply`, NOPASSWD via `/etc/sudoers.d/launchd-path`. Validates the PATH (absolute plain directories, no duplicates, must keep `/usr/bin /bin /usr/sbin /sbin`) and runs `launchctl config user path`. |
| `files/launchd-path-setup.sh` | One-time privileged install of the applier and sudoers rule (Touch ID via `sudo-ask`). Re-run after any change to the applier; the role refuses to run while the installed copy differs. |

## Use

```
just launchd-path-setup    # once, and after changing launchd-path-apply
just launchd-path-status   # desired vs stored
just launchd-path-check    # ansible --check
just launchd-path-apply    # store it; also the last step of `just deploy-mac`
```

## Caveats

1. **A change takes effect only after a reboot** (`man launchctl`, `config`).
2. A job whose plist sets its own `EnvironmentVariables.PATH` keeps that one. Most
   site and stayturgid plists set one today.
3. The setting applies to every user domain on this Mac, not just the operator's.
4. It is a copy: after editing `PATH` in `~/.bashrc` or `~/.bash_profile`, run
   `just launchd-path-apply` (or `just deploy-mac`) and reboot.
