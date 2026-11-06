---
name: ovhcloud-api
description: >-
  Drive the OVHcloud API from an agent: create the credential (legacy
  createToken AK/AS/CK vs an OAuth2 service account + IAM policy), store it in
  sudo-secretspec, sign requests with the python-ovh client or curl, and manage
  VPS instances, snapshots and IPs. Covers the exact Rights-field syntax for
  full access, the region-locked endpoint (ovh-us/ovh-eu/ovh-ca), why rights
  cannot be edited after creation, and the billing reach of `*`. Use when a task
  mentions OVH, OVHcloud, api.us.ovhcloud.com, createToken, an AK/AS/CK triple,
  or provisioning an OVH VPS.
version: 0.1.0
author: Dan Clark (djbclark), Dann VPS instance
license: Apache-2.0
platforms: macos, linux
tags: ovhcloud, api, credentials, provisioning, vps
---

# OVHcloud API — credentials, requests, and VPS provisioning

Canonical source: `skills/ovhcloud-api/` in `~/src/djbclark-ade`
(https://github.com/djbclark/djbclark-ade) (written 2026-10-25).

OVHcloud has **two credential models** and they are not interchangeable. Pick deliberately before
you create anything, because **a legacy credential's rights can never be edited** — OVH documents
only list and revoke, so a wrong scope means creating a new key and deleting the old one
(community, 2017, still true 2026-10: https://community.ovhcloud.com/t/50187).

1. **Legacy `createToken` (AK/AS/CK)** — one page, works immediately, region-locked, rights are a
   per-HTTP-method list of path patterns. Use this when you need access today.
2. **Service account (OAuth2 `client_credentials`) + IAM access policy** — per-action scopes
   (`vps:*`), rotatable, and the model the v2/IAM API surface is governed by. Needs the operator in
   the Control Panel and an access policy. Use this when you hit a v2-only need.

Full detail and the decision record: `references/ovh-credentials.md`.

## Creating a legacy token (the form, exactly)

Page per region — **the region must match where the token will be used**:

1. United States — https://api.us.ovhcloud.com/createToken/ → endpoint `ovh-us`
2. Europe — https://eu.api.ovh.com/createToken/ → endpoint `ovh-eu`
3. Canada / APAC — https://ca.api.ovh.com/createToken/ → endpoint `ovh-ca`

Fields:

1. **Application name / Script name** — pick something you will recognise in the key list later
   (e.g. `dann-vps-agent`). OVH's docs call it "the name … useful later if you want to allow others
   to use it".
2. **Description** — free text.
3. **Validity** — a period, or **Unlimited**. Prefer a finite period for anything you can rotate;
   Unlimited only for a credential you have a revocation plan for.
4. **Rights** — a list of `METHOD` + `PATH` rows. **To allow all OVHcloud APIs for a method, put an
   asterisk in the path field** (OVH's own wording: "In order to allow all OVHcloud APIs for an HTTP
   method, put an asterisk (`*`) into the field").

**Full access = four rows, and the path is `/*`, not a bare `*`:**

| Method | Path |
|---|---|
| GET | `/*` |
| PUT | `/*` |
| POST | `/*` |
| DELETE | `/*` |

The `+` button adds rows for PUT/POST/DELETE; the `-` button removes one. Confirmed by the
`createToken` URL format OVH itself generates and indexes:
`https://api.us.ovhcloud.com/createToken/index.cgi?DELETE=&GET=%2F*&POST=%2F*&PUT=%2F*` — i.e. each
path is `/` followed by `*` (URL-encoded `%2F*`). So a **pre-filled** link avoids typing the rows:

```text
https://api.us.ovhcloud.com/createToken/?GET=/*&POST=/*&PUT=/*&DELETE=/*
```


**`/domain` and `/domain/*` are different rules.** `*` covers everything *below* a path but not the
path itself, so a scoped token usually needs both rows. Getting this wrong fails as
`NOT_GRANTED_CALL` / `This call has not been granted` while other calls keep working — reads fine,
one write failing, is this bug, not a network problem.

### Say the billing sentence out loud

`*` on POST/DELETE reaches `/order/cart*`. **A full-rights token can order and bill.** If the
operator asked for "unlimited, full rights", they may not have priced that sentence at "can order
hardware" — state it plainly rather than assuming consent covers it. Standing discipline for an
agent holding such a token: **read-only-plus-frozen** — do not order, cancel, upgrade or delete
anything billable without a fresh explicit yes per action, whatever the token permits.

### The three keys

After **Create keys** you get, once:

1. **AK** — application key, e.g. `7kbG7Bk7S9Nt7ZSV` (16 alphanumeric).
2. **AS** — application secret, e.g. `EXEgWIz07P0HYwtQDs7cNIqCiQaWSuHF` (32 alphanumeric).
3. **CK** — consumer key, e.g. `MtSwSrPpNjqfVSmJhLbPyr2i45lSwPU1` (32 alphanumeric).

They are shown **once**. Close the page and they are gone — create a new set and delete the old.
AK/AS/CK are all `[A-Za-z0-9]`; treat a value with punctuation or box-drawing characters as a
mis-copied UI rendering, not a key.

## Storing the credential

Declare first, then store. **Have the operator run the general collector** — it is the safe path for
any value a human types, and it is not OVH-specific:

```bash
# 1. declare the names (no values yet; --optional keeps `check` green until they are set)
for n in OVH_APPLICATION_KEY OVH_APPLICATION_SECRET OVH_CONSUMER_KEY OVH_ENDPOINT; do
  sudo-secretspec add "$n" --description "OVHcloud API credential" --optional --reason "R"
done

# 2. the operator runs this; prompts hidden, all-or-nothing, shape-checked
S=~/src/sudo-secretspec/skills/sudo-secretspec/scripts/secrets-collect.py
python3 $S \
  --secret 'OVH_APPLICATION_KEY=Application Key (AK):16' \
  --secret 'OVH_APPLICATION_SECRET=Application Secret (AS):32' \
  --secret 'OVH_CONSUMER_KEY=Consumer Key (CK):32' \
  --secret 'OVH_ENDPOINT=API endpoint (ovh-us|ovh-eu|ovh-ca)' --literal
```

`secrets-collect.py` is in the `sudo-secretspec` skill (every agent TUI links that skill, so it is
always reachable). It reads each value with the input **hidden**, refuses anything that cannot be a
key (the alphanumeric check is what catches a masked UI rendering), stores nothing until all values
are collected and confirmed, and prints **names and lengths only**. Add `--notify-to <role>` and it
also messages that peer when done, again without values.

`scripts/ovh-store.py` remains as the single-value clipboard variant for a one-off re-copy: it
validates and forwards in one process, so the clipboard race in the `sudo-secretspec` skill (the
operator's *next* copy getting stored) cannot happen. Then prove reach without printing anything —
see Verification.

**Never write `~/.ovh.conf` into a repo, and never echo a key.** If a tool needs a config file,
generate it at runtime into a mode-600 temp path under `sudo-secretspec run`, or pass the values as
`OVH_ENDPOINT` / `OVH_APPLICATION_KEY` / `OVH_APPLICATION_SECRET` / `OVH_CONSUMER_KEY` environment
variables, which both the `ovhcloud` CLI and the python-ovh client read
(https://github.com/ovh/ovhcloud-cli `doc/authentication.md`).

## Making requests

1. **`scripts/ovh-api.py METHOD PATH [JSON]`** — signs and calls one endpoint with the credentials
   from `sudo-secretspec run`, printing the JSON response. Safe by default: it refuses any
   non-GET method unless `--allow-write` is passed, and refuses paths matching a billable pattern
   (`/order`, `/cart`, `/billing`, `/payment`, `/refund`, `/credit`) unless `--allow-billable` is
   passed too. This is the read-only-plus-frozen rule enforced in code rather than remembered.
2. **curl**, if you must — the signature is
   `"$1$" + SHA1_HEX(AS+"+"+CK+"+"+METHOD+"+"+QUERY+"+"+BODY+"+"+TSTAMP)` with headers
   `X-Ovh-Application`, `X-Ovh-Consumer`, `X-Ovh-Timestamp`, `X-Ovh-Signature`. `QUERY` is the
   **full** URL including `https://api.us.ovhcloud.com/1.0`. Prefer the wrapper; the signing is
   easy to get subtly wrong and a wrong signature looks like a bad key.
3. **Endpoint names** (from `ovh/client.py`): `ovh-us` → `https://api.us.ovhcloud.com/1.0`,
   `ovh-eu` → `https://eu.api.ovh.com/1.0`, `ovh-ca` → `https://ca.api.ovh.com/1.0`. A `ovh-us` key
   does not work against `ovh-eu`.
4. **v1 vs v2**: paths beginning `/v1` or `/v2` drop the `/1.0` from the endpoint. The `ovh` Python
   client handles this; a hand-rolled signer must too, and must sign the *final* URL.


## VPS operations

Useful calls for the provisioning project (`/vps` section of the console). All are on the legacy
surface and covered by `*`:

| Call | What it does |
|---|---|
| `GET /vps` | list VPS service names |
| `GET /vps/{serviceName}` | model, state, zone, `vcore`, `memoryLimit`, `disk` |
| `GET /vps/{serviceName}/serviceInfos` | status, renewal, expiry |
| `GET /vps/{serviceName}/ips` | attached IPs (find the public one) |
| `GET /vps/{serviceName}/snapshot` | snapshot state — evidence a backup exists |
| `GET /vps/{serviceName}/backupftp` | the backup FTP config, if offered |
| `POST /vps/{serviceName}/reboot` | **disruptive** — needs a fresh yes |
| `POST /vps/{serviceName}/reinstall` | **destroys the host** — needs a fresh yes |

Note what is *not* here: `GET /vps` returns service names, not addresses. The public IP comes from
`/vps/{serviceName}/ips` or the Control Panel. A VPS that has never been set up has no SSH key
installed, so "verify the VPS" before credentials exist is impossible by construction — record that
as expected, not as a fault.

## Verification

Assert the credential resolves and reaches the API **without printing any value**. Print a length,
a boolean, or an HTTP status only:

```bash
sudo-secretspec run --reason "prove the OVH credential resolves" -- \
  bash -c 'printf "AK len=%s AS len=%s CK len=%s endpoint=%s\n" \
    "${#OVH_APPLICATION_KEY}" "${#OVH_APPLICATION_SECRET}" "${#OVH_CONSUMER_KEY}" "$OVH_ENDPOINT"'

# the only call that proves AK/AS/CK agree: /me (needs GET /me, covered by GET /*)
sudo-secretspec run --reason "prove the OVH token works" -- \
  python3 skills/ovhcloud-api/scripts/ovh-api.py GET /me
```

A successful `/me` returns account fields and proves the triple. `403` with
`NOT_GRANTED_CALL` means the rights are wrong (usually a missing row, or `*` where the path itself
needed its own rule). `401` with `Invalid signature` means AS/CK mismatch — usually one value
belongs to a different key set. Neither is a network fault.

## Gotchas

**0. A declarative install must be EVALUATED before it is APPLIED — the failure modes are unbootable,
not noisy.** And a `POST` probe is a mutation, not a question. Both are the same lesson: checking first
costs minutes, not checking costs a machine.

**0a. Evaluate first.** Before any `nixos-anywhere` / disko / nixos-rebuild run against a real host:

```bash
nix eval .#nixosConfigurations.<host>.config.system.build.toplevel.drvPath
nix eval .#nixosConfigurations.<host>.config.system.build.diskoScript.drvPath
```

On 2026-10-25 this gate caught **four** defects on a first install, **two of which would have produced
an unbootable box**:

1. `partitions.*.type = "BIOS boot"` — **disko requires a GPT type GUID** (4-hex or 8-4-4-4-12), not a
   name. It rejects the name at evaluation. For a BIOS/GRUB layout use
   `21686148-6449-6E6F-744E-656564454649` (gdisk `ef02`).
2. **disko owns `fileSystems."/"`.** Declaring it yourself conflicts
   (`conflicting definition values`) because disko derives it from the layout as
   `/dev/disk/by-partlabel/disk-<disk>-<partition>`. Declare only `swapDevices`, which disko creates
   but does not register.
3. Without disko, a config still needs `fileSystems."/"` declared or evaluation fails with
   *"The 'fileSystems' option does not specify your root file system."*
4. **BIOS vs UEFI is not what the partition table suggests.** Check `/sys/firmware/efi` on the target,
   not the presence of a `/boot/efi` partition — this box had an ESP from its previous OS and BIOS
   firmware, so a UEFI layout would have been unbootable.

**0b. A `POST` probe is a mutation, not a question.** This generalises to every API, not just OVH.
Asking "does this endpoint exist?" with a POST *runs it*. On 2026-10-25 a sweep of `POST
/vps/{s}/<candidate>` expecting 404s hit a real `/reboot` and rebooted the box. **Discover with `GET`.
If you must test a POST-only path, do not sweep candidates — look it up in the console or the
provider's endpoint list.**

**0c. Never nest a heredoc inside a command string.** A `cat > file <<EOF` inside `ssh "..."` with
escaped quotes breaks (the shell eats the delimiter) — it cost three cycles in one day across two
agents, including a silently truncated message. **Write the file locally and copy it** (`scp`), or pass
it on stdin. If you must generate a file remotely, use `printf` with explicit `\n`, never a nested
heredoc.

**0d. A flake input added to `flake.nix` is not usable until `flake.lock` is regenerated.** Adding
`inputs.disko` without running `nix flake lock` makes every consumer fail with
`error: cannot write modified lock file of flake 'github:…'` — because from a git ref Nix cannot write
the lock it would need to create. The lock must be committed alongside the input.

**0d.1 The way this bites twice: reverting a lock that predated the input.** Real case, 2026-10-25,
and self-inflicted. A wrong `flake.lock` was committed by accident (it held a *standalone install
flake's* inputs, not the site flake's). The revert restored the previous lock from `HEAD~1` — which
**predated the `sops-nix` input added in between**. Result: `flake.nix` required `sops-nix`,
`flake.lock` had no `sops-nix` node, **every git-ref build failed** including the host's own
`nixos-upgrade`, and the host quietly stopped upgrading while the local build still worked.

Check it with one command. **Ask Nix rather than parsing** — it needs no regex and cannot miss a
declaration form:

```bash
# Checks the WORKING TREE (uncommitted tracked edits included), so it is the right check to run
# BEFORE committing - and NOT proof that the pushed ref is sound.
nix flake metadata --json --no-update-lock-file ./nixos >/dev/null

# After pushing, check the ref the host actually builds. This is the authoritative form - but it
# needs --refresh, because Nix caches which commit a github: branch points to for `tarball-ttl`
# (3600 s by default). Without it, a re-check within the hour can silently test the PREVIOUS commit
# and pass - the same false-pass hazard as the local form, inside the check meant to catch it.
nix flake metadata --json --refresh --no-update-lock-file \
  'github:OWNER/REPO/<deploy-branch>?dir=nixos' > meta.json
jq -r .revision meta.json   # must equal: git rev-parse origin/<deploy-branch>

# exit 0 = the lock matches flake.nix
# non-zero, "requires lock file changes but they're not allowed due to
# '--no-update-lock-file'" = the lock is stale or missing an input
```

**Two traps in that command, both verified on vps-primary (2026-10-25):**

1. **`tarball-ttl` is 3600** (`nix config show tarball-ttl`), so without `--refresh` a check run within
   the hour of a push may test the *old* commit — and it can pass or fail either way. **Always compare
   the reported `.revision` against `git rev-parse origin/<branch>`**; that comparison is the actual
   check, not the exit code.
2. **Push order matters when a promotion branch is involved** (house rule 36: `master` is promoted to
   the deploy branch). Checking `<deploy-branch>` *before* promoting tests the previous deploy head,
   which may well pass. Promote first, then check.

**The local form is a false-pass hazard** (verified on vps-primary, 2026-10-25): `./nixos` inside a git
checkout resolves to `git+file:` over the **tracked working tree**, uncommitted edits included. So you
can regenerate the lock, see exit 0, then push only `flake.nix` — and the host still fails. The
`github:` form above is what catches that.

If you need the *names* (e.g. to report which input is missing) without Nix, parse carefully — the
fallback below **reads the working tree too** (same weakness as the local form) and handles **only
top-level `inputs.<name>…` lines**, so it misses the `inputs = { foo.url = …; };` attrset form and can
be confused by a nested `inputs.bar.url = …` at the start of a line inside another input's block.
**The Nix command above is authoritative; the fallback is for naming what is missing.** It also
compares against the **root** inputs, not every node in the lock: `set(lock["nodes"])` includes
transitive nodes and the `root` entry itself, so a transitive node of the same name can mask a missing
root input.

```bash
python3 - <<'EOF'
import json, re, pathlib
d = pathlib.Path("nixos")
flake = (d / "flake.nix").read_text()
lock = json.loads((d / "flake.lock").read_text())
# Root inputs only - what flake.nix actually declares.
root_inputs = set(lock["nodes"][lock["root"]].get("inputs", {}))
declared = set(re.findall(r"^\s*inputs\.([A-Za-z0-9_-]+)(?:\.url)?\s*=", flake, re.M))
print("declared:", sorted(declared))
print("root inputs in lock:", sorted(root_inputs))
print("MISSING FROM LOCK:", sorted(declared - root_inputs) or "none")
EOF
```

**Reverting a lock is not safe on its own** — re-check it against `flake.nix` afterwards, because the
failure appears only on the git-ref path (local builds still work), which is why it survives local
testing.

**And `nixos-upgrade` failing is quiet in the sense that nobody is notified** — not in the sense that
the state is unreadable. A failed oneshot lands in the `failed` state, and systemd can tell you:

```bash
systemctl is-failed nixos-upgrade      # 'failed' after a failure, 'inactive' after a success
systemctl show nixos-upgrade -p Result # Result=exit-code vs Result=success
```

What *is* easy to miss is that **`is-active`'s exit code is non-zero in both cases** (verified on the
host: exit 3 after a success and after a failure), so an `if systemctl is-active …` script cannot tell
them apart — the *printed word* differs (`inactive` vs `failed`) but the *status* does not. Use
`is-failed` (exit 0 only when failed) or `show -p Result` to distinguish them. Note the `failed` state
only reflects the **latest** run: it clears on the next timer run or a `reset-failed`. That is why the
authoritative check is comparing `nixos-version --configuration-revision` against the deploy branch
head — it catches a stale host however the state got there.

Three levels of gate, and they are deliberately separate so one broad yes cannot reach the next:

| level | examples | why |
|---|---|---|
| read (default) | `GET /vps`, `serviceInfos`, `/ips` | asks a question |
| `--allow-write` | `getConsoleUrl`, config changes | changes *our* access, not the box |
| `--allow-destructive` | `reboot`, `reinstall`, `rescue`, `delete`, `snapshot` | acts on the machine or the service |


1. **Rights are immutable.** Plan the scope before creating; a fix is a new key.
2. **`*` is not `/*` for a path, and `*` does not include the parent path.** Add both rows.
3. **Region-locked.** Keys made on one region's page fail on another with "Authentication failed".
4. **Keys are shown once.** Copy all three before leaving the page.
5. **Sub-user accounts** use the same page but the ID is `XXXX-XXXX-XX/user`, and keys made that way
   belong to the sub-user.
6. **`ovhcloud-cli` is not in Homebrew** (checked 2026-10-25: `brew info ovhcloud-cli` → no formula).
   Install the Go binary from https://github.com/ovh/ovhcloud-cli releases, or use
   `uv tool install ovh` for the Python client (`ovh` 1.2.0 on PyPI, verified 2026-10-25).
7. **`/me/api/application`** lists keys, `/me/api/application/{id}` inspects one, and
   `DELETE /me/api/application/{id}` revokes it — but revoking needs rights on `/me/api/*`, so a
   token created without it cannot revoke itself. `*` covers it.

## Glitches actually hit, and what to do instead (all 2026-10-25, one session)

Kept because this work repeats: these cost real time and each one looks like something else.

1. **A wrong `OVH_ENDPOINT` produces `403 This application key is invalid`, which reads like a rights
   failure.** It is not — rights failures are `NOT_GRANTED_CALL`. The credential was a **US**
   credential (`ovh-us`, account accepted 200) on a service named `…vps.ovh.ca`, and the endpoint
   value was `ovh-ca`. **Test the region before believing any 403:** `scripts/ovh-region-check.py`
   probes all three with `/me` (read-only) and names the one that works. `scripts/ovh-api.py` now
   does this automatically on an auth failure.
   **Also note:** the *service name* tells you nothing about the API region — `.ovh.ca` on a US
   account is normal. The resource's IAM URN does tell you: `urn:v1:us:resource:…`.
2. **A `POST` probe is a mutation, not a question.** Probing whether `/vps/{s}/reboot` exists with
   `POST … --allow-write` expected a 404 ("no such path") and instead got `202` plus a queued
   reboot — **the box rebooted.** A discovery sweep must never be able to act. `ovh-api.py` now
   refuses reboot/reinstall/rescue/delete/snapshot/console paths unless `--allow-destructive` is
   passed *separately* from `--allow-write`, so one broad yes cannot reach them. **Use `GET` to
   discover; never sweep `POST` across candidate paths.**
3. **The first SSH user on an OVH VPS is not `root`.** It is the OS's default user (`debian` for
   Debian, `ubuntu`, `rocky`, …) with a temporary password delivered by a **secure link in the
   delivery email**, and the first login forces a password change. `root` login is disabled. So a
   fresh OVH VPS is unreachable by key until someone with console/email access adds one.
4. **The KVM console has an API endpoint:** `POST /vps/{serviceName}/getConsoleUrl` returns the
   console URL (the docs list it; the console UI path is VPS → General information → `...` → KVM).
   That is the way in when there is no key and no password — so **do not reinstall just to get
   access.**
5. **`GET /vps/{s}/snapshot` returning 404 does NOT mean "no backup".** It is the *manual* snapshot
   slot, empty by default. The automatic one is a different resource: `GET /vps/{s}/automatedBackup`
   → `{state, rotation, schedule}`. Check the right endpoint before reporting a backup gap.
6. **`serviceInfos.expiration` is the billing period, not a countdown to loss.** A monthly plan shows
   a date ~30 days out with `renew.automatic: true`. Do not raise it as a risk; check
   `renewalType`/`renew.period` first.
7. **A 404 on `GET /vps/{s}/<sub>` does not prove the sub-resource is absent** — it may be POST-only
   (e.g. `/reboot` 404s on GET and exists on POST). The `option` list (`GET /vps/{s}/option`) and the
   console are the honest sources. And per (2), never resolve this ambiguity with a POST probe.
9. **A forced password change needs a PTY, and `expect`'s `-re "assword:"` matches the wrong prompt.**
   OVH's first login forces a password change; a non-interactive SSH fails with *"Password change
   required but no TTY available"*, so use `ssh -tt` under `expect`. **Order the expect patterns
   most-specific-first**, because a bare `assword:` also matches **"Current password:"** — my first
   attempt fed the *new* password as the *current* one and got `passwd: Authentication token
   manipulation error`. Correct order: `Retype new password` → `New password` → `Current password` →
   `'s password:`.
10. **A password change on a remote box is a two-step operation.** The change closes the session, so
   installing a key must be a *second* login with the new password. Do the change first, verify the
   new password works, then install the key — and keep both values in 600 files, never argv.

