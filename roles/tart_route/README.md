# roles/tart_route

Local Orchard (controller + worker `bigmac`, launchd agent `com.djbclark.orchard-dev`) running tart
Linux VMs with working network, with no root for the VMs themselves and one
exact-argv NOPASSWD sudoers rule for the route repair. Sibling of
[`roles/container_route`](../container_route/README.md), which does the same for Apple
`container`'s 192.168.64.0/24.

## Why

1. **Softnet needs root; shared NAT does not.** `orchard create vm --net-softnet` makes the
   worker run `tart run --net-softnet`, which fails as the user agent with "root privileges
   are required to run and passwordless sudo was not available". The VMs are created
   without it, so tart uses its default shared NAT (vmnet, `192.168.65.0/24`, gateway
   `192.168.65.1` on `bridge100`). No sudo for softnet: Homebrew's `softnet` is
   user-owned, so a NOPASSWD rule on it would be root for any process of this user.
2. **Tailscale breaks the NAT route.** With an exit node and "Allow local network access"
   on, Tailscale replaces the connected `192.168.65.0/24 -> bridge100` route with
   `192.168.65 via 192.168.68.1 (en0)` shortly after a VM boots
   ([tailscale#22119](https://github.com/tailscale/tailscale/issues/22119)). The worker's
   dial to `192.168.65.x:22` then times out (`orchard ssh vm` hangs) and the VM has no
   internet. The same happens to **`192.168.64.0/24`** (`192.168.64 via 192.168.68.1 (en0)`)
   when no Apple `container` network is up and tart's bridge100 takes that subnet
   (gateway `192.168.64.1`). That case is repaired with the two argvs of the
   `container-route` rule ([`roles/container_route`](../container_route/README.md)), so it
   needs that rule installed (`just container-route-setup`); `tart-route` is not widened.
3. **`orchard dev` is unsafe and noisy.** It listens on `*:6120` with authentication
   disabled (remote code execution as the operator through hostDir mounts; adversary
   review 2026-11-13), and logs at DEBUG: ~15 MB/day of sync-loop lines. The launcher
   below runs a loopback-only, authenticated controller plus a worker instead, and
   filters the routine poll lines.

## Pieces

| Piece | Installed at | What it does |
|---|---|---|
| `files/tart-route-setup.sh` | `/etc/sudoers.d/tart-route` | One-time privileged install (Touch ID via `sudo-ask`), same mechanism as `container-route-setup.sh`: rule text in the dialog, root writes a dotted temp, `visudo -c`, `root:wheel 0440`, rename. `--print` shows the rule without installing. |
| `files/fix-vmnet-route.sh` | `~/.orchard/fix-vmnet-route.sh` | Unprivileged caller. Handles two subnets. `192.168.65.0/24`: finds the bridge holding `192.168.65.1` (bridge100, or bridge101 when a container network came up first) and, only when `netstat` shows the en0 variant, runs the `tart-route` argvs with `sudo -n`. `192.168.64.0/24`: only when bridge100 holds `192.168.64.1` and the en0 route is via `192.168.68.1`, runs the two `container-route` argvs (bridge101 holding `.64.1`, another gateway or a wider Tailscale route: hand fix, exit 1). Exit 0 ok/nothing to do, 1 a case the rules do not cover (printed with the hand fix), 3 a rule missing (the message names `tart-route` or `container-route`). Test hooks: `FIX_VMNET_ROUTE_FIXTURE_DIR` (files `netstat`, `ifconfig`) and `FIX_VMNET_ROUTE_DRYRUN=1` (print the sudo argv); see `tests/test_fix_vmnet_route.py`. |
| `files/orchard-launch.py` | `~/.orchard/orchard-launch.py` | The supervisor. Runs `orchard controller run --listen 127.0.0.1:6120` with TLS (Orchard's self-signed certificate in `~/.orchard/controller/controller.crt`) and a fresh random 32-character admin token in `ORCHARD_BOOTSTRAP_ADMIN_TOKEN` at every start (controller stdout, where Orchard prints account details, is discarded, so the token never reaches the launchd log), rewrites `~/.orchard/orchard.yml` (0600) with one context holding that token and the pinned certificate so the `orchard` CLI works, then runs `orchard worker run --name bigmac --bootstrap-token-stdin https://127.0.0.1:6120` (the bootstrap token from `orchard get bootstrap-token bootstrap-admin` carries the certificate, so the worker pins it too). Also runs the route caller every 15 s (logs to `~/.orchard/route-watch.log` only when its output changes; backs off 5 min when the rule is missing) and filters DEBUG and the routine 5 s loopback poll lines out of stderr. Either child exiting ends the launcher, so launchd restarts the set: a dead controller kills the worker at once, and shutdown stops the worker before the controller. |
| `files/orchard-run-dev.sh` | `~/.orchard/run-dev.sh` | Two-line shim the launchd plist runs (kept under its old name so the plist and label do not change): `exec python3 -I ~/.orchard/orchard-launch.py`. |

The rule (exact argv, no wildcards; `/sbin/route` is root-owned and SIP-protected):

```
/sbin/route -n delete -net 192.168.65.0/24 192.168.68.1
/sbin/route -n add -net 192.168.65.0/24 -interface bridge100
/sbin/route -n add -net 192.168.65.0/24 -interface bridge101
```

The 192.168.64.0/24 repair uses `/etc/sudoers.d/container-route` instead (not installed by
this role):

```
/sbin/route -n delete -net 192.168.64.0/24 192.168.68.1
/sbin/route -n add -net 192.168.64.0/24 -interface bridge100
```

## Use

```
just tart-route-setup                      # once (Touch ID)
install -m 0755 roles/tart_route/files/fix-vmnet-route.sh ~/.orchard/.fix-vmnet-route.sh.new && mv -f ~/.orchard/.fix-vmnet-route.sh.new ~/.orchard/fix-vmnet-route.sh
install -m 0755 roles/tart_route/files/orchard-launch.py ~/.orchard/.orchard-launch.py.new && mv -f ~/.orchard/.orchard-launch.py.new ~/.orchard/orchard-launch.py
install -m 0755 roles/tart_route/files/orchard-run-dev.sh ~/.orchard/.run-dev.sh.new && mv -f ~/.orchard/.run-dev.sh.new ~/.orchard/run-dev.sh
launchctl kickstart -k gui/$(id -u)/com.djbclark.orchard-dev   # restarts orchard: running VMs are lost (below)
orchard create vm --image ghcr.io/cirruslabs/ubuntu:24.04 --os linux --cpu 4 --memory 8192 --disk-size 80 gha-ubuntu-2404
orchard ssh vm -u admin -p admin gha-ubuntu-2404 "curl -sS -o /dev/null -w '%{http_code}' https://ports.ubuntu.com"
```

Never pass `--net-softnet` / `--net-softnet-allow` / `--net-softnet-block` to
`orchard create vm`. Test the rule with `sudo -k -n /sbin/route -n add -net
192.168.65.0/24 -interface bridge100` (it really runs; `sudo -l` cannot tell NOPASSWD
from `(ALL) ALL`).

## Caveats

1. Restarting the agent (or a reboot) kills the `tart run` children; Orchard 0.55 then
   marks the VMs `failed` ("Worker lost track of VM") and, with restart policy `Never`,
   leaves them. Recreate them (`orchard delete vm NAME`, then the `create` above), and
   `tart delete` any orphaned `orchard-gha-*` clone `tart list` still shows. Base images
   are never touched.
2. Do not start an Apple `container` while a tart VM runs: it takes bridge100 away from
   tart (see `~/src/cfengine-all/docs/local-ci-containers-vs-tart.md` §C3).
3. With a container and a VM both up Tailscale may install a wider `192.168.64/23`; the
   rule does not cover it and the caller prints the hand fix (exit 1).
4. Accepted risk: the rule allows the add on bridge100 and on bridge101 whichever one
   tart holds, so code running as this user could point 192.168.65.0/24 at the Apple
   container bridge and let a container answer for the VMs. Such code already owns the
   Orchard API, the VMs and their admin/admin logins, so this grants nothing new; the
   caller itself only ever adds the bridge holding 192.168.65.1.
5. **The CLI token changes at every launcher start.** `orchard-launch.py` writes a new
   admin token into `~/.orchard/orchard.yml` each time, so a long-running `orchard`
   process started before a restart gets 401 and must be rerun. The token is stored only
   in that 0600 file and in the two child processes' environment/stdin (Orchard's own
   `bootstrap-context` file has the same shape); `sudo-secretspec` is not used because the
   credential is self-generated, local and loopback-only. The API is `https://127.0.0.1:6120`
   (loopback): tart guests at `192.168.65.1` and the LAN cannot reach it. TLS exists for
   pinning, not for the wire: the controller runs without `--insecure-no-tls`, Orchard
   makes a self-signed certificate in its data dir, and the worker (through the bootstrap
   token) and the CLI (the `certificate:` field of the `local` context) trust only that
   certificate. If the controller dies, another local account that binds 127.0.0.1:6120
   cannot impersonate it to the still-running worker (which would obey any VM spec,
   including hostDir mounts of the home directory): it lacks the key, the TLS handshake
   fails and the worker never sends it a request. The certificate (10 years) is created
   once and reused across restarts; deleting `~/.orchard/controller/controller.crt` and
   `.key` gets a new one at the next start. Each start also generates a new random token
   (see above), so the pinned certificate is not the only secret. Do not
   set `--host-dir-policies` (default: every hostDir mount is rejected) and never
   re-introduce `orchard dev`.
6. The launcher sets `umask 077` and `chmod 700 ~/.orchard` itself. launchd opens its
   logs (`~/.orchard/launchd.stdout.log`, `launchd.stderr.log`) before the launcher
   runs, so their mode follows the plist's `Umask` key (`<integer>63</integer>` in
   `~/Library/LaunchAgents/com.djbclark.orchard-dev.plist`, outside this role; without it
   0644). Either way they live inside `~/.orchard`, which is 0700, so other accounts
   cannot read them; the token is never written to them in any case.
7. The launcher refuses to start if anything already listens on 127.0.0.1:6120, and
   checks with `lsof` that its own controller owns the listener before any credential
   leaves it (another local account cannot capture the admin token by binding first).

## Reboot checklist

After a login or reboot the LaunchAgent starts the controller, worker and route watcher by
itself, but the VMs do not survive (caveat 1). Within about 15 s of the first VM boot the
watcher repairs the route.

1. `launchctl list com.djbclark.orchard-dev` shows a PID; `lsof -nP -iTCP:6120 -sTCP:LISTEN`
   shows `127.0.0.1:6120` and nothing wider.
2. `orchard list workers` shows `bigmac`.
3. `orchard list vms`: a VM in `failed` or missing is recreated (`orchard delete vm NAME`,
   then the `create` in "Use"); `tart list` must show no leftover `orchard-gha-*` clone.
4. `netstat -rn -f inet | rg '^192\.168\.6[45] '` shows `bridge100` (or `bridge101` for
   192.168.65), not `en0`, for whichever of the two subnets tart holds (192.168.64 when no
   container network is up). If it does
   not after 30 s: `~/.orchard/fix-vmnet-route.sh`, then `tail ~/.orchard/route-watch.log`
   (`sudo: a password is required` means `/etc/sudoers.d/tart-route` is missing: `just
   tart-route-setup`; for 192.168.64 the message names `container-route`: `just
   container-route-setup`).
5. `orchard ssh vm -u admin -p admin gha-ubuntu-2404 'lsb_release -rs'` (and `gha-ubuntu-2204`).
6. `~/.tart` stays under 300 GiB (`dust -d1 ~/.tart`; last measured 30 GiB). No macOS
   images.

## Removal

When tailscale#22119 is fixed, or Orchard is retired:

```
sudo rm /etc/sudoers.d/tart-route
```

and drop the route-watch thread from `~/.orchard/orchard-launch.py` (or the whole agent:
`launchctl bootout gui/$(id -u)/com.djbclark.orchard-dev`).
