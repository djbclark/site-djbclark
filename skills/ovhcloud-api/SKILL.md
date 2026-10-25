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

Declare first, then store. `set` reads the value from stdin when stdin is not a terminal, so the
value never enters argv, history or a transcript:

```bash
sudo-secretspec add OVH_APPLICATION_KEY    --description "..." --optional --reason "R"
sudo-secretspec add OVH_APPLICATION_SECRET --description "..." --optional --reason "R"
sudo-secretspec add OVH_CONSUMER_KEY       --description "..." --optional --reason "R"
sudo-secretspec add OVH_ENDPOINT           --description "..." --optional --reason "R"

# store from the clipboard, one value at a time, validating shape in the SAME process
export LC_CTYPE=en_US.UTF-8
pbpaste | scripts/ovh-store.py OVH_APPLICATION_KEY     # prints only len + shape verdict
printf 'cleared' | ~/ops/site-private/bin/clip         # then overwrite the clipboard
```

`scripts/ovh-store.py` refuses a value that is not the documented shape, in one process, so the
clipboard race in the `sudo-secretspec` skill (the operator's *next* copy getting stored) cannot
happen. Then prove reach without printing anything — see Verification.

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

