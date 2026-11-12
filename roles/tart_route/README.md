# roles/tart_route

Local Orchard (`orchard dev`, launchd agent `com.djbclark.orchard-dev`) running tart
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
   internet.
3. **`orchard dev` logs at DEBUG** with no flag to lower it: ~15 MB/day of sync-loop
   lines into `~/.orchard/launchd.stderr.log`.

## Pieces

| Piece | Installed at | What it does |
|---|---|---|
| `files/tart-route-setup.sh` | `/etc/sudoers.d/tart-route` | One-time privileged install (Touch ID via `sudo-ask`), same mechanism as `container-route-setup.sh`: rule text in the dialog, root writes a dotted temp, `visudo -c`, `root:wheel 0440`, rename. `--print` shows the rule without installing. |
| `files/fix-vmnet-route.sh` | `~/.orchard/fix-vmnet-route.sh` | Unprivileged caller. Finds the bridge holding `192.168.65.1` (bridge100, or bridge101 when a container network came up first), and only when `netstat` shows the en0 variant runs the exact argvs with `sudo -n`. Exit 0 ok/nothing to do, 1 a case the rule does not cover (printed with the hand fix), 3 rule missing. |
| `files/orchard-run-dev.sh` | `~/.orchard/run-dev.sh` | The launchd program. Starts a watcher that runs the caller every 15 s (logs to `~/.orchard/route-watch.log` only when its output changes; backs off 5 min when the rule is missing), filters DEBUG and the worker's own 5 s poll lines out of stderr, then `exec orchard dev`. |

The rule (exact argv, no wildcards; `/sbin/route` is root-owned and SIP-protected):

```
/sbin/route -n delete -net 192.168.65.0/24 192.168.68.1
/sbin/route -n add -net 192.168.65.0/24 -interface bridge100
/sbin/route -n add -net 192.168.65.0/24 -interface bridge101
```

## Use

```
just tart-route-setup                      # once (Touch ID)
install -m 0755 roles/tart_route/files/fix-vmnet-route.sh ~/.orchard/.fix-vmnet-route.sh.new && mv -f ~/.orchard/.fix-vmnet-route.sh.new ~/.orchard/fix-vmnet-route.sh
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
5. **`orchard dev` has no auth and listens on `*:6120`** (no listen flag; the macOS
   firewall is off): any LAN device or tailnet peer can drive the API, and with the route
   repaired so can the VMs (`192.168.65.1:6120`). Not changed here; the fix is to replace
   `orchard dev` with `orchard controller run --listen 127.0.0.1:6120` plus
   `orchard worker run` (service-account tokens).

## Removal

When tailscale#22119 is fixed, or Orchard is retired:

```
sudo rm /etc/sudoers.d/tart-route
```

and drop the watcher block from `~/.orchard/run-dev.sh` (or the whole agent:
`launchctl bootout gui/$(id -u)/com.djbclark.orchard-dev`).
