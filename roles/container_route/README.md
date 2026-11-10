# roles/container_route

NOPASSWD sudoers rule for exactly two `route` commands, so an unprivileged script can
repair Apple `container`'s network on this Mac.

## Why

With a Tailscale exit node and "Allow local network access" on, the Tailscale network
extension replaces vmnet's `192.168.64.0/24 -> bridge100` route with `192.168.64.0/24 via
192.168.68.1 (en0)` about 4 s after each container starts (log line `allowing exit node
access to local IPs: [... 192.168.64.0/24 ...]`). Guests then get DNS but no TCP.
Upstream: [tailscale#22119](https://github.com/tailscale/tailscale/issues/22119).

## Pieces

| Piece | What it does |
|---|---|
| `files/container-route-setup.sh` | One-time privileged install (Touch ID via `sudo-ask`) of `/etc/sudoers.d/container-route`. Idempotent. The dialog shows the rule text; root writes, `visudo -c`-checks and renames it in one step, absolute paths only. No root-owned script: the rule names `/sbin/route` and the full argv. |
| `~/src/cfengine-all/linuxgate/fix-route.sh` | The unprivileged caller. Runs `sudo -n` with exactly those argvs, and only when `netstat` shows the en0 variant. |

The rule (exact argv, no wildcards):

```
/sbin/route -n delete -net 192.168.64.0/24 192.168.68.1
/sbin/route -n add -net 192.168.64.0/24 -interface bridge100
```

## Use

```
just container-route-setup     # once
sudo -k -n /sbin/route -n delete ...   # test a rule: this really runs it; sudo -l cannot tell NOPASSWD from (ALL) ALL
~/src/cfengine-all/linuxgate/fix-route.sh   # after starting a networked container
```

The route is runtime-only and disappears when the last container stops, so the caller
runs after each networked container is up (the gate lanes use `--network none` and need
nothing). Remove the rule when Tailscale fixes #22119: `sudo rm /etc/sudoers.d/container-route`.
