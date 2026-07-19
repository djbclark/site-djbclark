# NEXT: M1-F — Phase D must-fix remediation (difficulty 55/100)

**Funding plan in force:** FUND-B revised (see
`docs/plans/site-djbclark-phase-d-funding-plans-v1.md`). Recovery-month
step 2 of {M1-R ✓, M1-F, M1-Q}; R3 stays deferred until after M1-Q.

**Recommended AI** (full rows from `docs/reference/available-ai-models.md`):

- **Primary —** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Sonnet 5 ·
  `claude-sonnet-5` · Adaptive Thinking + Effort (default High on Claude
  Code/API) · _Default for most plans_ — **original account** (per FUND-B
  M1-F assignment), default effort.
- **Alternate —** Codex 0.144.6 (oauth) · OpenAI · GPT-5.6 Sol ·
  `gpt-5.6-sol` · Light, Medium, High, Extra High, Max, Ultra · _Flagship;
  complex coding, computer use, research, cybersecurity_ — effort High.
- **Escalation —** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Fable 5 ·
  `claude-fable-5` · Low, Medium, High, Extra, Max, Ultra (GUI picker; no
  Auto) · _Next-gen long-running agents_ — **new second-Pro account**, effort
  Medium, only if a fix fights back (two failed attempts).

**Working dir:** `/Users/djbclark/ops/stayturgid` (product fixes; branch+PR)
and `/Users/djbclark/ops/site-djbclark` (site fixes + relay; straight to
master). `git fetch origin --prune && git pull --ff-only origin master` in
both before editing.

---

You are executing **M1-F**: the complete remediation of M1-R's must-fix list.
Read `docs/relay/reviews/m1-r-phase-d-design-review.md` (this repo) first —
it contains full context, refs, failure scenarios, acceptance tests, and
rollback notes for every item below. Also read `docs/relay/PROTOCOL.md`,
step2 plan §§0–2, and stayturgid `AGENTS.md`. Design baseline
`docs/design/phase-d-adapter-design-notes.md` is read-only.

## Must-fix items (MF-1..MF-5) — do all, in this order

1. **MF-1 — secrets out of world-readable plists (live fix; do first).**
   In `ansible/roles/serverapp_vector/tasks/main.yml` and
   `ansible/roles/serverapp_openobserve/tasks/main.yml`, change the plist
   template task `mode:` from `"0644"` to `"0600"`. Because the mode change
   marks the template task changed, the existing bootout+bootstrap-on-change
   path re-loads both daemons — that is expected and safe (pre/post health
   checks below). Acceptance: `stat -f %Lp` on both live
   `~/Library/LaunchAgents/com.djbclark.{vector,openobserve}.plist` → `600`;
   both daemons state=running; `curl 127.0.0.1:8686/health` and
   `127.0.0.1:5080/healthz` → 200; OTLP 4318 listening; second
   `just site-serverapps apps=vector,openobserve` exit 0. Rollback:
   `chmod 644 <plist>` (content unchanged; no daemon restart needed).
   Do not print, echo, or commit any credential value.

2. **MF-2 — persist hd8's otelcol incompatibility (site repo).**
   Add to `inventory/hosts.yml` under host `hd8` (or
   `inventory/group_vars/model_kindle_hd8.yml`):
   `stayturgid_otelcol_enabled: false` with comment
   `# D8: pending-incompatible-runtime — official contrib binary SIGSYS under Fire OS seccomp (cilium/ebpf memcg probe); recovery = minimal OCB build, see m1-r review §D8`.
   Acceptance: `ansible-inventory --host hd8` (site ANSIBLE_CONFIG) shows the
   var; s24/p7a unaffected; site registry lint green. No device contact.
   Rollback: remove the var.

3. **MF-3 — plist-change reload semantics (product).** In
   `serverapp_caddy`, `serverapp_grafana`, `serverapp_olivetin` tasks: clone
   vector's pattern — `Boot out <label> when its launchd plist changed`
   (when: loaded AND plist.changed) before the bootstrap task; bootstrap
   `when: unloaded or reload_bootout.changed` with `until/retries: 5`;
   restrict the existing kickstart to config-only changes (config.changed AND
   NOT plist.changed). Olivetin: also add retries to its bootstrap.
   Acceptance: focused test or assert on rendered task conditions; live: run
   `just site-serverapps apps=caddy,grafana,olivetin` twice — second run all
   skip, exit 0, all health 200 (no plist change → no churn).

4. **MF-4 — fragment-change reload for caddy + vector (product).** In each
   role, before the launchd block, stat/checksum the fragment inputs
   (caddy: files matching `serverapp_caddy_fragment_glob`; vector: the
   `serverapp_vector_fragment_configs` list) against a recorded state file
   (e.g. `~/.config/<site_ns>/<app>/.fragments.sha256`, written by the role)
   and register `_<app>_fragments_changed`; add it to the kickstart
   condition (kickstart is correct here — fragments are config, not plist).
   Acceptance: pytest/unit where a fragment byte change flips the reload
   condition; live: run apply twice, second run no reload, exit 0, health 200. Keep OliveTin (hot-reload) and Grafana (provider updateInterval)
   unchanged.

5. **MF-5 — checksum-pin OpenObserve + OliveTin downloads (product).** Add
   `serverapp_openobserve_archive_sha256` (per `_oo_arch`, version 0.91.1)
   and `serverapp_olivetin_archive_sha256` (per `_ot_arch`, version
   3000.17.1) defaults; pass `checksum: "sha256:{{ … }}"` to both `get_url`
   tasks; fail with a clear message if the var is empty. Obtain the sha256
   values from the vendors' published checksums where available, else by
   downloading over HTTPS to a temp dir and hashing (record the method in
   the PR). Acceptance: role syntax + ansible-lint green; roles still no-op
   on this machine (binaries present); a deliberately wrong checksum var
   makes a scratch get_url fail (test in /tmp, not against the live roles).

## Cheap architecture fixes (from M1-R; include in the same PR)

6. **A-10 —** remove `commit: {{ product_commit }}` from generated-file
   headers (keep `product_version`; commit stays in `.lockfile.yml`). Update
   affected sync templates + role config templates + any tests asserting the
   header. Then in the site repo run `just site-sync mode=apply`, commit the
   re-stamped `generated/` (+ live olivetin projection rewrite is expected),
   and verify a second `just site-sync mode=dry-run` is **all skip** — this
   restores durable second-sync no-op.
7. **A-11 —** delete the hard-coded `~/ops/site-djbclark` fallback (and the
   site-naming comment) from `just/services.just` `landing-discover`;
   `discover.py` already resolves STAYTURGID_SITE_DIR → OPS_ROOT/site-*.
   Verify `just landing-discover` from the site wrapper still reports
   registry drift.
8. **A-12 —** change the fleet dashboard `noValue` from
   `no data (pre-D8)` to an honest label (`no metrics pipeline yet`) in
   `stayturgid-fleet.json.j2` (rides the A-10 re-stamp).

## Constraints

- No device contact (MF-2 is inventory-only). No secrets in output or
  commits. No design-baseline edits. No monitor retirement. Do not start the
  hd8 OCB recovery build — that is a separate post-M1-Q step.
- stayturgid: one branch + PR (`fix/m1-f-phase-d-mustfix`), merge it
  yourself after evidence per PROTOCOL.md, end on pulled master. Site:
  straight to master.

## Verification checklist (record evidence in ledger note)

1. stayturgid `just check` + full `just test` + `pre-commit run --all-files`
   green (record counts).
2. Overlay + upstream-only `just validate-identity` clean;
   `just site-contract-check`; `generate_registry_seeds --check`.
3. Site `bin/registry_lint.py` OK.
4. Live (read-only + the MF-1/MF-3 applies): all 9 health endpoints 200
   (8080/health, 8686/health, 5080/healthz, 8428/health, 3000/api/health,
   1337/, 8088/health, 4097/, HTTPS front door); both secret-bearing plists
   mode 0600; second site-serverapps apply exit 0.
5. Post-A-10: second `just site-sync mode=dry-run` all-skip on the
   re-stamped site.
6. Hosted CI green on the merged PR and merged master.

## End of session

Per `docs/relay/PROTOCOL.md`: append one `M1-F` ledger line (evidence +
anything deferred); rewrite `NEXT-PROMPT.md` for **M1-Q** (work the M1-Q
list in `docs/relay/reviews/m1-r-phase-d-design-review.md` §Code quality +
the justified-kept documentation items; no behavior changes; tests stay
green; R3 follows M1-Q). Commit and push site master; merge + delete the
stayturgid branch; both repos clean on pulled master. Print the new
NEXT-PROMPT.md in chat and run `pbcopy < docs/relay/NEXT-PROMPT.md`.
