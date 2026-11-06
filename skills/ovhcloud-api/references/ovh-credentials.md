# OVHcloud credentials: the two models, and the decision record

Written 2026-10-25 by the Dann VPS instance, while provisioning its own OVH VPS.

## The decision, and why

The operator asked for a token with "unlimited, full rights". Two models exist; the choice is
recorded here because a legacy credential's scope **cannot be changed afterwards**.

**Chosen: the legacy `createToken` (AK/AS/CK) at `/*` on all four methods.**

1. It is what the operator asked for, on his own account, and it unblocks the work today.
2. A service account needs him in the Control Panel plus an IAM access policy; that is a second
   round trip for no immediate gain.
3. The service account stays on the list as a later addition **when a v2-only need appears** —
   not speculatively.

**The caveat recorded with it, and said out loud to the operator:** `*` on POST/DELETE reaches
`/order/cart*`, so the token **can order and bill**. "Unlimited, full rights" may not have been
priced at "can order hardware" when it was said.

**The discipline adopted as a standing rule:** *read-only-plus-frozen*. No order, cancellation,
upgrade or deletion of anything billable without a fresh explicit yes per action, whatever the
token permits. Read-only and non-billable operations need no permission.

## Model 1 — legacy createToken (AK/AS/CK)

- One page per region; three values issued once: **AK** (application key), **AS** (application
  secret), **CK** (consumer key).
- Rights: a list of HTTP method + path pattern rows. `*` in the path field means all APIs for that
  method. In practice the value is `/*` (OVH's own pre-filled links encode it as `%2F*`).
- **Immutable.** OVH documents only `GET /me/api/application`, `GET /me/api/application/{id}` and
  `DELETE /me/api/application/{id}` — list, inspect, revoke. There is no edit. A wrong scope means
  a new key (community thread 50187, 2017; unchanged in the 2026 docs).
- **Region-locked.** The three portals and endpoints are independent:
  | Region | Token page | Endpoint name | API base |
  |---|---|---|---|
  | United States | https://api.us.ovhcloud.com/createToken/ | `ovh-us` | https://api.us.ovhcloud.com/1.0 |
  | Europe | https://eu.api.ovh.com/createToken/ | `ovh-eu` | https://eu.api.ovh.com/1.0 |
  | Canada / APAC | https://ca.api.ovh.com/createToken/ | `ovh-ca` | https://ca.api.ovh.com/1.0 |
- **Signing** — `"$1$" + SHA1_HEX(AS+"+"+CK+"+"+METHOD+"+"+QUERY+"+"+BODY+"+"+TSTAMP)`, where QUERY
  is the full URL and TSTAMP is the *server's* time (use `GET /auth/time` for the delta). Headers:
  `X-Ovh-Application`, `X-Ovh-Consumer`, `X-Ovh-Timestamp`, `X-Ovh-Signature`.
- **Wrappers** exist so you do not hand-roll this: python-ovh (`pip install ovh` / `uv tool install
  ovh`, 1.2.0 as of 2026-10-25), go-ovh, php-ovh, node-ovh, csharp-ovh.
- **Listing and revoking needs its own rights.** A token created without rights on `/me/api/*`
  cannot revoke itself. `*` covers it.

## Model 2 — service account (OAuth2) + IAM access policy

- An identity of the form `urn:v1:<region>:identity:credential:<account>/oauth2-<hex>`, created via
  the API (`POST /me/api/oauth2/client`), with a `client_id` / `client_secret` pair.
- Token fetch: `POST <token-url>` with `grant_type=client_credentials`, `client_id`,
  `client_secret`, `scope=all`. Token URLs: EU `https://www.ovh.com/auth/oauth2/token`,
  CA `https://ca.ovh.com/auth/oauth2/token`, US `https://us.ovhcloud.com/auth/oauth2/token`
  (from `OAUTH2_TOKEN_URLS` in `ovh/client.py`).
- Calls then carry `Authorization: Bearer <access_token>`; tokens last ~3599 s.
- Rights come from an **access policy** naming actions, e.g. `webHosting:*` or `vps:*`, attached to
  the service account's URN and scoped to resource URNs. This is the least-privilege model and the
  one the v2/IAM surface is governed by.
- A wrong policy gives `403 User not granted for this request`. Permissions are evaluated when the
  policy is applied, so a bad policy is fixed by editing it — unlike the legacy model.
- Cost: needs the operator in the Control Panel, and `scope=all` on the token request regardless of
  the policy's narrower allow-list.

## Where the two models differ, in one line each

1. **Scope:** pattern-per-method (legacy) vs per-action allow-list (service account).
2. **Changeable:** no (legacy) vs yes, edit the policy (service account).
3. **Coverage:** legacy patterns cover the v1 surface; the v2/IAM surface is governed by policies,
   so a legacy `*` may be simultaneously broader (billing) and narrower (v2) than intended.
4. **Setup:** one web page (legacy) vs Control Panel + policy API (service account).

## Sources

1. https://docs.ovhcloud.com/en/guides/manage-and-operate/api/first-steps (last updated 2025-05-13)
2. https://support.us.ovhcloud.com/hc/en-us/articles/360018130839-First-steps-with-the-OVHcloud-API
   (updated 2026-06-15) — the "put an asterisk (`*`) into the path field" wording and the AK/AS/CK
   examples.
3. https://docs.ovhcloud.com/en/guides/account-and-service-management/account-information/authenticate-api-with-service-account
4. https://github.com/ovh/python-ovh — `ovh/client.py` (ENDPOINTS, OAUTH2_TOKEN_URLS, signing).
5. https://github.com/ovh/ovhcloud-cli — `doc/authentication.md` (env vars, config file, profiles).
6. https://community.ovhcloud.com/t/50187 — rights and lifetime cannot be edited after creation.
