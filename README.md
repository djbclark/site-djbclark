# site-djbclark

> **AI agents:** start at [AGENTS.md](AGENTS.md) instead of this file — it's
> the entry point with the doc map, conventions, and **this site's slice** of
> the three-way memory/docs policy (stayturgid / site-`<name>` / site-private).

Private **site repo** for djbclark's machines (M1 MacBook Air, Intel Mac
mini, Linux VPSs) — the identity/allocation authority paired with the public
product repo [stayturgid](https://github.com/djbclark/stayturgid). Base
layout is three sibling checkouts under `${OPS_ROOT:-~/ops}/`: this repo, `stayturgid`, and
`site-private`. Policy is distributed — see [AGENTS.md](AGENTS.md) and the
links there to
[stayturgid's AGENTS.md](https://github.com/djbclark/stayturgid/blob/master/AGENTS.md)
and
[site-private's AGENTS.md](https://github.com/djbclark/site-private/blob/master/AGENTS.md).

| Where                                                            | What                                                                                                                                                                |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `docs/relay/NEXT-PROMPT.md`                                      | **Start here to continue the work** — the baton: which AI to use and the exact prompt to paste ([protocol](docs/relay/PROTOCOL.md), [ledger](docs/relay/LEDGER.md)) |
| `docs/plans/site-djbclark-step1-segmentation-architecture-v1.md` | Architecture + decision log (2026-07-18)                                                                                                                            |
| `docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`     | Phased execution plan: steps, difficulty, AI routing, risk register                                                                                                 |
| `docs/plans/site-djbclark-step0-plan-v1.md`                      | Goose + LiteLLM AI-stack plan (see amendment header)                                                                                                                |
| `registry/ports.yml`, `registry/paths.yml`                       | Port and path/namespace allocation authorities — check before adding either; lint with `bin/registry_lint.py`                                                       |
| `bin/check_hostnames.py`                                         | Site-specific Mac/Linux/Android hostname audit (`just hostnames-audit`)                                                                                             |

## Versioned deployments

The three `${OPS_ROOT:-~/ops}` checkouts deploy as one coordinated suite and
advance only to published `ops-vMAJOR.MINOR.PATCH` releases. Use
`just ops-release-check`, `just ops-release-deploy`, and
`just ops-release-status`; do not pull deploy checkouts directly from
`master`. The guarded `just ops-memory-sync` command is the sole data-only
exception for `site-private/memory/`.

Full release, rollback, and verification policy:
[docs/OPS-RELEASES.md](docs/OPS-RELEASES.md).

## LiteLLM proxy (Phase E1 + E4 keys + E5 multi-host)

The site-owned LiteLLM proxy listens on **`127.0.0.1:4000`** (loopback default;
no public bind without a master-key / auth design).

| Host (inventory `site_litellm`) | Runtime                               | Default                           |
| ------------------------------- | ------------------------------------- | --------------------------------- |
| `m1-air`                        | launchd `com.djbclark.litellm`        | **online** — `just litellm-apply` |
| `mac-mini-intel`                | launchd (Intel Homebrew `/usr/local`) | planned until online              |
| `vps-primary`                   | systemd user unit                     | planned until online              |

```bash
just litellm-apply          # limit m1-air
just litellm-check
just litellm-status
LITELLM_HOSTS=site_litellm just litellm-apply   # all members; skips unprovisioned
```

**API Keys – Human Step:** SecretSpec dotenv + unit injection (LaunchAgent or
systemd user unit mode 0600). Checklist:
[`human/API-KEYS-E4.md`](human/API-KEYS-E4.md).

```bash
secretspec run --reason "apply LiteLLM provider keys" -- just litellm-apply
```

See `roles/litellm/README.md` for multi-host, routing, verification, rollback.
Goose against this proxy: `roles/goose/README.md`.

## Merged-Brewfile + brew flock (Phase F4)

Site-owned **package claims** live under `brew/fragments/*.yml`. Projection
writes `generated/Merged-Brewfile` (annotated, visibility only). Diff against
the system-state Brewfile snapshot is read-only — never mass-uninstalls.

```bash
just brew-project              # regenerate Merged-Brewfile
just brew-diff                 # project + compare to ~/system-state/Brewfile
just brew-lock -- brew info just   # exclusive lock around brew-touching cmds
```

Concurrent brew mutations (e.g. `just goose-apply`) take
`~/.local/state/site-djbclark/brew.lock` (or `$XDG_RUNTIME_DIR` / `$TMPDIR`) via `bin/brew_flock.py` (`fcntl.flock`; macOS
has no util-linux `flock(1)` by default). Details and rollback:
[`brew/README.md`](brew/README.md).

## OliveTin user actions

`stayturgid`'s D6 OliveTin projection (`control/site_contract/olivetin_projection.py`,
`USER_ACTIONS_RELATIVE`) merges an optional site-local action file into the
live OliveTin config alongside the product's own fragment:

- Product actions: `generated/stayturgid/fragments/olivetin/stayturgid_actions.yaml`
  (rendered by site-sync, `stayturgid_`-prefixed ids).
- Site actions: [`olivetin/user-actions.yaml`](olivetin/user-actions.yaml)
  (`user_`-prefixed ids). Currently: **Herdr** status / start / stop / restart /
  reload-config (`user_herdr_*`). Herdr is UDS-only — no TCP row in
  `registry/ports.yml`; claim is under `registry/paths.yml`.

After editing user actions, reproject the live config:

```bash
just site-sync   # apply (default); uses this checkout as STAYTURGID_SITE_DIR
```

CLI equivalents: `just herdr-status`, `just herdr-start`, `just herdr-stop`,
`just herdr-restart`, `just herdr-reload`. Details:
[`docs/reference/herdr-brew-service.md`](docs/reference/herdr-brew-service.md).

## Caddy route naming

The existing Phase D route scheme is the site convention: the public hostname
root serves the network landing page, while product UIs use stable lowercase
noun paths (`/dashboard/`, `/stats/`, and `/opencode/`). Internal
service health and observability ports remain loopback-only and do not receive
public route names. D7 adopts this scheme as-is; M1 may revisit the naming as an
architecture improvement without changing the current route contract.

## Local MTA / Postfix (System Utilities)

macOS provides a built-in Postfix MTA managed by launchd. It is configured to run on-demand for local mail delivery, supporting system utilities like `cron` and `jobber`. The launchd label is `com.apple.postfix.master` on current macOS (older releases through El Capitan used `org.postfix.master`) — confirmed on this control node via `ls /System/Library/LaunchDaemons/ | grep postfix`.

- **Service Status**: Active on-demand, managed by the system LaunchDaemon (not user-configurable without a custom override).
- **Verification**: `echo "Test" | mail -s "Test" $USER` and check `/var/mail/$USER`.
- **Note**: Local delivery works out-of-the-box without additional configuration; no `sudo` modifications or passwordless exceptions are required.
