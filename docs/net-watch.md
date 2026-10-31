# net-watch

Detects sustained download slowdowns on the home link (TP-Link Deco mesh), pings **once** when a slowdown
starts and **once** when it ends, collects debugging data, and tries **one** Deco reboot per episode.
Files: `bin/net-watch`, the pinned Deco helper `bin/net-watch-deco` + `bin/net-watch-deco.lock`, `tests/test_net_watch.py`,
the launchd job `com.djbclark.net-watch` (`macos/net-watch/com.djbclark.net-watch.plist`), and the config template
`config/net-watch.toml.example`. `site-private/bin/net-watch*` are symlinks to the `bin/` files here (the convention `fleet-watch` uses).

## Behaviour

| Item | Value |
|---|---|
| Tick | launchd runs `net-watch tick` every 60 s; it returns at once unless a probe is due (and takes a lock, so overlapping ticks do nothing) |
| Cadence | probe every 5 min while healthy, every 1 min after a slow sample, until recovery |
| Probe | 4 parallel `curl` streams (5 MB each, hard max 8 s) bound to the **physical** interface (`--interface en0`; the system default route here is the Tailscale `utun4`), plus 2 smaller streams (2 MB) through the default route for comparison. Mbps = megabits. Objects: Cloudflare `speed.cloudflare.com/__down` and Hetzner `ash-speed.hetzner.com/100MB.bin` (range-limited) |
| UNKNOWN sample | A sample is **UNKNOWN**, not slow, when no physical interface was discovered (nothing is downloaded: it would measure the Tailscale exit node), every stream failed (outage, DNS, Wi-Fi off), no stream got an HTTP 2xx/206 (CDN error or rate limit), or zero bytes arrived. It neither extends nor resets the slow clock, never starts an episode, never reboots, never counts toward recovery. A run of unknowns longer than 3 ticks cannot bridge two slow samples. **A total outage does not reboot the Deco.** If no stream got any answer at all (outage, or connect/TLS timeouts on every stream) for `sustain_min`, with the home identity verified, ONE ping says "internet unusable at home" (and whether the gateway answers); no reboot, no snapshot |
| Slow sample | Mbps < `threshold_mbps` (30). Mbps = the best of each host's streams (bytes over that host's slowest OK stream) and all OK streams together: failed, stalled or HTTP-error streams take no part in bytes or time, so one slow or blackholed speed-test host cannot make a sample slow. "Clearly under", not exact: the probe moves only 20 MB, so TCP ramp-up makes it read low on very fast links. Which path counts is `reboot.trigger` (default `direct` = the interface sample; `tunnel` = the default-route sample, judged by the same rules and UNKNOWN when unmeasurable; `either` = slower of the two) |
| Tunnel in/out | When the default route is a tunnel (Tailscale exit node), each probe also uploads 1 MB to `speed.cloudflare.com/__up` through it. Recorded per sample as `default_up_mbps` next to the default-route download (`default_mbps`) so an inbound-only collapse is visible; **never part of a verdict**. No server on the exit node is needed (so it measures the path out to Cloudflare, not Mac to the exit node itself; a Mac-to-exit-node transfer would need a listener on that host) |
| Direct upload | Every probe on the home network also uploads 1 MB to `speed.cloudflare.com/__up` bound to the **physical** interface (`--interface en0`, 2026-10-31), recorded per sample as `direct_up_mbps` and printed by `probe`/`status` as "direct upload". With the tunnel upload (`default_up_mbps`) it tells a slow home uplink from a slow exit-node path: direct up much lower than direct down is the ISP uplink; direct up fine but tunnel up low is the Tailscale path. **Never part of a verdict.** About 1 MB per probe (12 MB/h healthy) |
| Episode start | slow samples cover >= `sustain_min` (10) minutes with no healthy sample between (timestamps; one missing tick is tolerated, a gap over 3 x `slow_interval_s` such as a sleep restarts the count) |
| At start | one snapshot, **one** `hermes-ping`, then (enabled, `[deco] host` set, credentials present, cooldown ok) **one** Deco reboot. A failed reboot is never retried in the same episode and still starts the cooldown; the cooldown is re-checked when a delayed reboot fires |
| Episode close without recovery | still **one** end ping, saying why and "recovery unknown": `gap` (no tick for over 3 intervals inside an episode: the Mac slept; the sleep is not counted as slow time), `abandoned` (open longer than `episode_max_h`, default 12 h), `away` (left the home network) |
| Home network only | measures, snapshots and calls the Deco **only** when the gateway's arp MAC is in `[home] gateway_mac` and `[deco] host` is set. Otherwise (café, hotel, hotspot, or not configured) it is "not measuring": no probe, no episode, no snapshot, no Deco call, no data use; `status` says why. A tick that merely cannot read the MAC/interface ("unsure") is tolerated twice inside a slowdown before it counts as away |
| Episode end | `recover_samples` (2) consecutive healthy samples: **one** `hermes-ping` (duration, min/avg Mbps, reboot done and how long after it speed recovered) |
| Nothing else | no per-sample pings, no "still slow" pings. Tool errors go to the log; at most one error ping a day |
| Baseline | rolling median of healthy samples of the last 24 h (in the pings and `status`) |

Pings read `djbclark: net-watch: download <x> Mbps (baseline <y>) for <n> min on en0; snapshot <path>; reboot <will try|skipped: reason>`
and `djbclark: net-watch: download recovered after <n> min on en0; min <a> / avg <b> Mbps during ...; <reboot summary>`.
Periodic snapshots inside an episode back off: 5, 15, 60 min after the start, then hourly; all episode directories together are capped at 256 MB (oldest go first), snapshots are owner-only (umask 077, 0700 directories).

### Tunnel-only slowdown (`tunnel_degraded`, trigger `direct` only)

Operator ruling 2026-10-26: with the default `reboot.trigger = "direct"` a slowdown of the default-route path (Tailscale exit node) while the direct path is fine **never reboots**. It is its own episode kind: ONE start ping ("tunnel-only slowdown ... direct path is fine ... no reboot attempted"), one evidence snapshot labelled `tunnel-degraded` (the full snapshot plus `tailscale netcheck`, a `tailscale ping` to the exit node, ping RTT idle versus during a bounded default-route download, the Deco info and interface counters it already has), and ONE end ping. Rule (frontier consult, `net-watch-frontier-report.md` F2): healthy baselines `D0` (direct) and `T0` (default route) are medians of the last 24 h of healthy pairs; alert after **3 consecutive valid pairs** with `D >= 0.60*D0`, `T <= 0.25*T0` and `T/D <= 0.20`; recovery after `recover_samples` pairs with `T > 0.25*T0` and `T/D > 0.20`. Baselines never take a degraded pair, so they stay frozen during degradation. A pair whose default-route sample timed out, failed or moved zero bytes is not a pair: it neither counts nor resets the count (timeout, error and zero bytes stay distinct from slow). A gateway ICMP non-reply is never evidence (this gateway does not answer ICMP while forwarding fine). While a collapse is suspected or open the probe runs every minute. The episode also closes (one end ping) when the direct path goes slow too (a normal slowdown episode takes over), on `gap`, `abandoned` and `away`. With `trigger = "tunnel"` or `"either"` the tunnel verdict is a normal slowdown (and may reboot): that is the opt-in for later. No baseline yet (fewer than 3 healthy pairs) means no alert.

**Probe budget.** One 20 MB probe per path per minute would be about 57.6 GB/day for two paths (2 MB each: about 5.76 GB/day). net-watch probes every 5 min when healthy and every minute only while a slowdown or a tunnel collapse is suspected or open; the direct and default-route samples run one after the other, never together.

### Network notes

If the Deco's WAN address is a private (RFC 1918) address from DHCP, the Deco sits behind an upstream router, i.e. **double NAT**. The snapshot's `deco` item keeps the WAN `ip`, `mask`, `gateway`, `dns1`, `dns2` (allowlisted), so this shows in every snapshot.

### Data use

Healthy: about 22 MB per probe (20 MB interface + up to 4 MB default route when fast; less when slow) x 288 probes/day is
about **6 GB/day** worst case. During a slowdown a probe moves at most `8 s x speed` (about 3 MB at 3 Mbps), so a day
fully slow is well under 6 GB. `networkQuality` is not used (heavy).

## Commands

```
net-watch tick                 # what launchd runs
net-watch status [--json]      # state, last 5 samples, baseline, episode, last reboot
net-watch probe [--record] [--json]   # one probe now; no state change unless --record
net-watch reboot [--dry-run]   # Deco reboot now: home network, [deco] host and credentials required; waits up to 150 s for a running tick, records the cooldown before the call, settles an open episode's reboot as manual
net-watch diagnose             # snapshot now, prints its directory
net-watch install | uninstall  # launchd job (install also runs warm)
net-watch warm                 # fetch the pinned helper packages into uv's cache (needs PyPI; run while the link is up)
```

## Config `~/.config/net-watch/config.toml` (REQUIRED: `[deco] host` and `[home] gateway_mac`)

The real file is machine-local and lives in **neither repo** (it holds the home gateway's hardware address and the Deco's LAN address);
`NET_WATCH_CONFIG` overrides the path. Copy `config/net-watch.toml.example` and fill in the two required values. The block below is the
same template with placeholder values (`192.0.2.1` and `aa:bb:cc:dd:ee:ff` are documentation placeholders):

```toml
threshold_mbps = 30
sustain_min = 10          # >= 1
healthy_interval_s = 300
slow_interval_s = 60
recover_samples = 2       # >= 1 (invalid values fall back to the default, with a log line)
episode_max_h = 12        # close an episode as abandoned after this long
interface = ""          # "" = discover (physical default-route interface, never utun*)
gateway = ""            # "" = discover
urls = ["https://speed.cloudflare.com/__down?bytes=5000000", "https://ash-speed.hetzner.com/100MB.bin"]
[reboot]
enabled = true          # must be a TOML boolean; anything else disables reboots (logged)
min_cooldown_h = 2      # >= 0 (bad values fall back to the default with a log line)
after_min = 10          # >= 0: reboot once the episode is this old (the start notice fires at sustain_min)
max_per_day = 3         # >= 1: automatic reboots in any rolling 24 h (manual ones counted), whatever the trigger
trigger = "direct"      # WHICH slow path arms an episode and so the one reboot: "direct" (Wi-Fi/WAN on en0, today's rule) | "tunnel" (default route, e.g. the Tailscale exit node) | "either"
[deco]
host = "192.0.2.1"   # REQUIRED for any Deco call; never defaults to the discovered gateway
[home]
gateway_mac = ["aa:bb:cc:dd:ee:ff"]   # REQUIRED: arp MAC of the home Deco master; `net-watch status` shows the current one
```

### Roaming

The Deco login hands the admin password to whatever answers on the gateway address (the library does not verify TLS),
and 192.168.68.0/24 is the Deco default subnet that other networks use too. So identity is the gateway's hardware address
(`arp -n <gateway>`), not the subnet. SSID/BSSID pins are not used: macOS withholds the SSID/BSSID from tools without
Location permission. Off the home network net-watch is idle (no probes, so no tethered-data use; no snapshots; no Deco
call); an open episode is closed with one "left the home network" ping. Back home it resumes by itself. Copy the MAC
from `net-watch status` (net: `gateway_mac`) while at home; if the Deco master is replaced, update it.

### ARP and Local Network privacy (`bin/net-watch-tick`)

macOS Local Network privacy hides the ARP table from processes that are not Apple-signed. Under launchd, `arp -n <gateway>` and `ping` work from a bash job and from Apple's `/usr/bin/python3`, but fail from Homebrew/uv Python, even with a bash parent. net-watch needs Python 3.11 or newer, so Apple's Python is not an option, and without the gateway MAC it reports "NOT MEASURING: gateway MAC unknown (arp has no entry)" forever.

So launchd starts `bin/net-watch-tick`, a bash script, not `net-watch`. Each run first deletes the previous `arp.snapshot` (and any stale temp file) as a courtesy, then pings the gateway once (the first IPv4 default route on an interface that is not a tunnel; it uses the same interface-prefix list as `TUNNEL_PREFIXES` in `bin/net-watch`, and a test fails if the two lists differ) and writes the snapshot to `~/.local/state/net-watch/arp.snapshot` (temp file in the same directory, mode 0600, `mv -f`; nothing is written if that path is a directory). The file's **first line is `# net-watch-tick pid <wrapper PID>`**, followed by the `arp -an` output. Only after the `mv` succeeded does the wrapper export `NET_WATCH_VIA_TICK_WRAPPER=<its PID>`; a skipped or failed run exports nothing and also unsets any value it inherited. It then `exec`s `net-watch` with its arguments (the PID stays the same). A snapshot failure is skipped and never fails the tick. Tests may override the tools with `NW_ARP`, `NW_PING` and `NW_NETSTAT`; `NET_WATCH_STATE_DIR` moves the directory.

`net-watch` asks its own `arp` first (so `arp_source` is `arp` in `status --json` `net`). Only when that finds no MAC does it read the snapshot (`arp_source` is `snapshot`). The binding is by PID, not by deletion: the variable must name this process or its parent (`uv run` starts Python as a child of the exec'd wrapper) **and** the file's first line must name that same PID. So a value inherited from a shell or environment, another run's file (two runs overlapping), and a file the wrapper could not delete (read-only state directory) are all refused, whatever they contain. Fail closed: the file must also be a regular file, not a symlink, owned by this uid, mode 0600 or tighter, modified in the last **30 s** (`ARP_SNAPSHOT_MAX_AGE_S`; the wrapper wrote it seconds earlier), and have a line for exactly the gateway IP on exactly the discovered interface (` on <interface>` as a whole word) with a MAC; the header line is not matched as an ARP line. Otherwise there is no MAC, as before. The home check itself is unchanged: the MAC must still be one of `[home] gateway_mac`. What is new is only this: the process the wrapper started, with a snapshot it wrote moments before for the same gateway and interface, can supply the MAC that `arp` cannot.

`net-watch status` shows what the job last saw (`state.json`), so it works from any shell. `net-watch <command>` run by hand (`probe`, `diagnose`, `reboot`, `tick`) never uses a snapshot: a file left by the last tick might describe the network the laptop has just left, and nothing in a shell's environment can make it trusted. From an agent shell it therefore says "NOT MEASURING: gateway MAC unknown" whenever the live `arp` is hidden, exactly as before the wrapper existed. `net-watch-tick <command>` run by hand is the wrapper, so it does use a snapshot, but one it wrote itself a moment earlier, bound to its own PID; that is a legitimate way to measure from a shell, and the wrapper is not launchd-only. Do not export `NET_WATCH_VIA_TICK_WRAPPER` by hand: only the wrapper sets it, and a value that is not the reader's PID or its parent's is ignored. `status` run before the first tick with the new plist also says so.

## State and files

`~/.local/state/net-watch/`: `state.json` (atomic writes; samples 24 h, episode, last reboot), `net-watch.log`,
`launchd.out/.err`, `episodes/<YYYYmmddTHHMMSS>-<label>/`. Nothing here is committed. Episodes older than 60 days are pruned.

### Reading a snapshot directory

Labels: `start` (full, at the start ping), `periodic` (short, every 5 min during an episode), `post-reboot-recovered`
(at the end, if rebooted), `post-reboot-still-slow` (10 min after a reboot that did not help), `manual` (`diagnose`).
Per directory: `meta.json` (episode id, last 12 samples), `index.json` (each item ok/failed + seconds, one failing item never
aborts the rest), then one file per item, each capped at 64 KB (directory at 2 MB):

| File | What |
|---|---|
| `wifi` | RSSI, noise, channel, tx rate, BSSID, security (`wdutil info` needs root; falls back to `system_profiler SPAirPortDataType -json`) |
| `ping-gateway`, `ping-1.1.1.1`, `ping-8.8.8.8` | loss, min/avg/max/stddev (JSON first, raw after), pinged with `ping -b en0` so they use the physical link. `ping-1.1.1.1-default-route` (full snapshots) pings the same host via the default route. Gateway loss or high stddev = Wi-Fi/mesh; gateway fine but 1.1.1.1 bad = ISP/modem; bound vs default-route differing = the Tailscale exit node |
| `dns` | dig timings against the gateway and 1.1.1.1 |
| `http-timing` | curl dns/connect/tls/ttfb/total to 3 hosts on the physical interface |
| `traceroute` | `traceroute -n -m 8` to 1.1.1.1 via the default route (here: first hop is the Tailscale exit node, which is itself a finding) |
| `counters-and-rates` | `netstat -I` bytes/errors, TCP retransmit counters, diff vs the previous snapshot, **5 s in/out Mbps**. High out Mbps = upload saturation, which slows downloads |
| `top-talkers` | `nettop -P` top 10 processes over 5 s: are our own agents saturating the link? |
| `link` | ifconfig + `networksetup -getMedia` (speed/duplex) |
| `uptime-load` | uptime and load |
| `tailscale` | trimmed `tailscale status --json`: exit node in use?, relay vs direct peers |
| `deco` | node list with signal, WAN/LAN IP info, CPU/mem, client count (only on the home network with credentials). Allowlisted fields only: no PPPoE/ISP login, no Wi-Fi passwords |

## Deco credentials (sudo-secretspec; nothing else)

net-watch reads exactly two names with `sudo-secretspec get` (argv list, stdin /dev/null, values kept in memory for
the one process, never written anywhere): `DECO_ADMIN_USER` and `DECO_ADMIN_PASSWORD`. It does **not** run the helper
under `sudo-secretspec run`, so the rest of the vault (OVH, GitHub, LiteLLM keys...) is never handed to a child in its
environment. The helper `bin/net-watch-deco` runs with env `{PATH, HOME, DECO_ADMIN_USER, DECO_ADMIN_PASSWORD}` only. That is **not a trust boundary**: the helper and its dependencies run as the operator and can call `sudo-secretspec get/export` or read `~/.ssh` themselves; the only control is the hash-pinned dependency set (Known limits 10).
Missing credentials are a normal outcome: the start ping says `reboot skipped: no credentials ...`. Operator steps, once:

```bash
sudo-secretspec add DECO_ADMIN_USER     --optional --description "TP-Link Deco admin login (net-watch)" --reason "net-watch Deco reboot"
sudo-secretspec add DECO_ADMIN_PASSWORD --optional --description "TP-Link Deco admin password (net-watch)" --reason "net-watch Deco reboot"
python3 ~/src/sudo-secretspec/skills/sudo-secretspec/scripts/secrets-collect.py \
  --secret 'DECO_ADMIN_USER=Deco admin username (the literal `admin`)' --literal \
  --secret 'DECO_ADMIN_PASSWORD=Deco admin password (the owner TP-Link ID password)' --literal
sudo-secretspec run --reason "check" -- sh -c 'echo ${#DECO_ADMIN_USER} ${#DECO_ADMIN_PASSWORD}'   # lengths only
net-watch warm      # once, with the link up
```

(`--optional` so an unset value never blocks other `sudo-secretspec run` users.)

**Pinned helper.** `bin/net-watch-deco` is a PEP 723 script: `tplink-deco-api==2.0.0` (current release on PyPI,
**HTTP goes through `/usr/bin/curl`.** On this Mac (macOS 27) every Python build gets `EHOSTUNREACH` (errno 65) connecting to the LAN Deco while `/usr/bin/curl` and `nc` work (a local-network restriction on non-platform binaries; cause unconfirmed). The helper therefore replaces the library's `HttpTransport._post` with a curl one (argv list, body on **stdin** `--data-binary @-` so the encrypted login password is never in argv, the URL (it carries the session token `;stok=`) and the `Cookie` header through `-K /dev/fd/N`, an inherited pipe, so no session credential is in argv either, `-sk -m <timeout>`, `-D -` for headers, `Expect:`, `Accept-Encoding: identity`, `Connection: close`, the `sysauth` cookie parsed with the library's own regex, HTTP >= 400 -> `TransportError(status_code=N)`, never connected -> `TransportError`, connected then timed out/reset -> raw `TimeoutError`/`ConnectionResetError`, which `sent_then_dropped` counts as "request sent" exactly as for urllib). Tested against a stub `curl` on PATH only; **not run against the real Deco by this round**. The login username is the literal `admin`; the password is the owner's TP-Link ID password (a TP-Link ID email returned 403 on every authenticated call, verified live by the operator 2026-10-26).

2026-10-14, requires Python >= 3.14), and `bin/net-watch-deco.lock` pins it and its dependencies (`cryptography`, `cffi`,
`pycparser`) by hash. It runs as `uv run --script --locked --offline`: nothing is resolved at run time, and a reboot during
an outage never needs PyPI. `net-watch warm` (also run by `install`) fills uv's cache while the link is up; a cold cache
shows up as `Deco helper did not run ... run: net-watch warm`. To bump: edit the version in the script, `uv lock --script bin/net-watch-deco`, review, `net-watch warm`.

**Reboot call** (library and `amosyuen/ha-tplink-deco` sources): login, `device_list`, then `POST admin/device?form=system`
`{"operation":"reboot","params":{"mac_list":[{"mac":...}, ...]}}` listing the master first and every node (whole group).
Success means the call returned, or a timeout/connection reset happened while waiting for the response (what a rebooting
router does). A refused connection, DNS or TLS error, HTTP error or API error is a failure. Afterwards the helper polls
`device_list` for up to 180 s: **confirmed** = it stopped answering and then answered again; otherwise the outcome says
**unconfirmed**. Error text anywhere (state, pings, snapshots, log) is an error class plus a fixed message, never the
exception text. Logging in to the Deco API signs the Deco app / web UI admin out for a moment.

## Install

```bash
~/ops/site-public-djbclark/bin/net-watch install      # copies the plist to ~/Library/LaunchAgents and bootstraps it
~/ops/site-public-djbclark/bin/net-watch status       # ~/ops/site-private-djbclark/bin/net-watch is the same file through a symlink
```

The plist runs `~/ops/site-public-djbclark/bin/net-watch-tick tick` (see "ARP and Local Network privacy"), so the branch must be merged there first. `net-watch uninstall` removes it.
No `ProcessType` key is set (Standard): `Adaptive` would behave as `Background` for this XPC-less job (see Known limits 3).

## Known limits

1. A Deco reboot also drops this Mac's own link for 2-3 minutes; those samples are UNKNOWN (no data) inside an already open episode and are harmless.
2. Probes measure this Mac's path (Wi-Fi hop + WAN), not the whole LAN. A Wi-Fi-only problem on this Mac looks like a Deco problem.
3. launchd `ProcessType`: the plist sets none (Standard). `Adaptive` only moves a job between Background and Interactive on XPC activity, and this StartInterval job has none, so it would have been Background for its whole life (suspected to throttle its network traffic). Before trusting reboots, compare `net-watch probe` run by hand under load with what the job records (`status`).
4. `wdutil info` needs root, so Wi-Fi details come from `system_profiler` (no live rssi/noise on recent macOS; the snapshot says which source it used).
5. The Deco reboot payload was verified from source only, never against the real device; a failure is logged, noted in the end ping, and not retried.
6. Probes leave the link measurably busier for up to 8 s every 5 min (1 min when slow).
7. DNS timings (`dig`) and `traceroute` cannot be bound to an interface on macOS and follow the default route; on 2026-10-25 that was the Tailscale exit node, not the Deco.
8. The home check needs the gateway's arp entry. net-watch pings the gateway once when there is none; if arp still has no entry, the Mac counts as not home (`status`: "gateway MAC unknown (arp has no entry)"), never a guess. On 2026-10-25 an agent shell on this Mac saw `arp -n 192.0.2.1` report "no entry" and `arp -an` list nothing at all, although ping worked and the routing table showed the gateway (round 2 reproduced it in a second shell), so the live MAC read is **unverified in a normal terminal and under launchd**: run `net-watch status` from a terminal and from the launchd job and check that `gateway_mac` is filled before relying on it. If the arp table is hidden from the job, net-watch measures nothing; it is no longer silent about it: after 30 min of "gateway present, MAC unreadable" it sends one tool-error ping a day ("net-watch is inert: the gateway MAC cannot be read"). There is deliberately no weaker fallback identity (DHCP server id, IP): a foreign network can present those too.
9. A "cannot tell if home" tick (arp reply lost, Wi-Fi re-associating) inside a slowdown is tolerated for 2 ticks and changes nothing; only a readable MAC that differs, or a third consecutive unsure tick, closes the episode as "left the home network".
10. The Deco helper is **not sandboxed**. The env it gets is `{PATH, HOME, user, password}`, so the rest of the vault is never handed to it, but code in `tplink-deco-api` or its dependencies runs as the operator and could itself call `sudo-secretspec` or read `~/.ssh`. The control is the version + hash pin. **Audit, 2026-10-26 (one pass, by grep and reading of the transport/auth code):** `tplink-deco-api` 2.0.0 (uploaded 2026-10-14; wheel sha256 `27b06840...` equals the lock entry, and its 43 files / 1843 lines are identical to the sdist source read) has no `subprocess`/`os.system`/`exec`/`eval`/`pickle`/`ctypes`/`socket`/`open`/`environ` use; its only I/O is `urllib` to the configured host with TLS verification **off**, plus an `.env` reader (`_env.py`) that the client never imports. `cryptography`, `cffi` and `pycparser` are hash-pinned and **not** audited. Still not done: a `sandbox-exec` profile (network cannot be limited to one host there), pinning the Deco's login RSA key (cannot be verified without the real device), and a `requires-python` pin (an interpreter switch breaks the offline helper until `net-watch warm`; the end ping then says "run: net-watch warm").
11. A chronic slowdown no longer reboots the mesh every ~12 h: after an episode is abandoned (open `episode_max_h`) the automatic reboot stays off until a healthy sample is seen, and at most `reboot.max_per_day` (3) reboots (manual ones counted) happen in any 24 h whatever the trigger. The start and "abandoned" pings still repeat every ~12 h while it stays slow.
