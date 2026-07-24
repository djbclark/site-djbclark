# site_agents — control-node maintenance LaunchAgents (Phase F1)

Adopts hand-managed LaunchAgents into Ansible-managed site roles. Scripts
install to `~/.local/bin`; plists render to
`~/Library/LaunchAgents/com.<site_ns>.*`.

## What it manages

| Agent | Label | Schedule | Output |
| ----- | ----- | -------- | ------ |
| system-state-backup | `com.{{ site_ns }}.system-state-backup` | Daily 12:00 + RunAtLoad | `{{ homebrew_prefix }}/var/system-state` + mirror `~/system-state` |
| hibernate-disk-check | `com.{{ site_ns }}.hibernate-disk-check` | Every 1800s + RunAtLoad | macOS notification when `/` free GB < threshold (default 25) |
| cswap-auto | `com.{{ site_ns }}.cswap-auto` | KeepAlive (long-running) | Auto-switches Claude Code accounts near rate limits |
| aiuse | `com.{{ site_ns }}.aiuse` | Every 21600s (6h) + RunAtLoad | `aiuse -q --json`; snapshots under `~/.cache/aiuse/snapshots` when `persist_snapshots` is on |

Homebrew prefix follows the LiteLLM / stayturgid pattern: Apple Silicon
`/opt/homebrew`, Intel `/usr/local` (from `ansible_facts.architecture`).

## Apply

```bash
cd ~/ops/site-djbclark
just site-agents-apply          # first apply
just site-agents-check          # dry-run (ansible --check)
just site-agents-status         # launchctl print all labels
```

Playbook targets `localhost` (control node). No secrets required.

## Manual one-shot

Safe to run by hand; system-state-backup only overwrites capture files on
success (does not clobber good snapshots on partial failure):

```bash
~/.local/bin/system-state-backup.sh
~/.local/bin/hibernate-disk-check   # notifies only when below threshold
# cswap-auto is a long-running agent; use cswap auto --once for a single tick:
cswap auto --once
```

## Rollback

Boot out the site labels (stops scheduled runs):

```bash
uid=$(id -u)
launchctl bootout "gui/$uid/com.djbclark.system-state-backup"
launchctl bootout "gui/$uid/com.djbclark.hibernate-disk-check"
launchctl bootout "gui/$uid/com.djbclark.cswap-auto"
launchctl bootout "gui/$uid/com.djbclark.aiuse"
```

To restore pre-F1 hand-managed copies after apply replaced them:

```bash
git -C ~/ops/site-djbclark checkout HEAD~1 -- \
  roles/site_agents/files/hibernate-disk-check \
  roles/site_agents/templates/system-state-backup.sh.j2
# Re-render/install manually or re-run an older playbook revision, then:
launchctl bootstrap "gui/$uid" ~/Library/LaunchAgents/com.djbclark.system-state-backup.plist
launchctl bootstrap "gui/$uid" ~/Library/LaunchAgents/com.djbclark.hibernate-disk-check.plist
```

**Note:** After the first F1 apply, the live scripts under `~/.local/bin` are
the role-managed copies; pre-F1 hand edits are overwritten.

## Verification checklist

```bash
just site-agents-apply
just site-agents-apply    # second run: changed=0
just site-agents-status
~/.local/bin/system-state-backup.sh
~/.local/bin/hibernate-disk-check
tail ~/.local/state/cswap-auto.log    # check it's polling
```

Expected: all four labels loaded in `gui/<uid>`; system-state LAST_RUN.txt updated;
`~/system-state` mirror refreshed; cswap-auto shows periodic polling output;
aiuse has written `~/.local/state/aiuse.log` and (with persist) files under
`~/.cache/aiuse/snapshots`.

## How to add a new LaunchAgent

All site LaunchAgents follow a three-layer pattern: **defaults → template → task**,
wired through the `launchagent.yml` sub-task for idempotent bootstrap lifecycle.

### 1. Add defaults (`defaults/main.yml`)

Define paths, label, and configurable settings under a `site_agents_<name>_`
namespace. Keep to the pattern:

```yaml
# --- my-agent ---------------------------------------------------------------
site_agents_my_label: "com.{{ site_ns }}.my-agent"
site_agents_my_plist: >-
  {{ site_agents_launchagents_dir }}/{{ site_agents_my_label }}.plist
site_agents_my_log: "{{ site_agents_state_dir }}/my-agent.log"
site_agents_my_error_log: "{{ site_agents_state_dir }}/my-agent.error.log"
site_agents_my_some_config: 60       # configurable knob
```

Reuse the shared variables: `site_agents_home`, `site_agents_bin_dir`,
`site_agents_state_dir`, `site_agents_launchagents_dir`, `site_agents_uid`.

### 2. Create the plist template (`templates/<name>.plist.j2`)

Two common patterns:

**KeepAlive server** (long-running daemon, e.g., cswap-auto):
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{{ site_agents_my_label }}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/binary</string>
        <string>--flag</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ThrottleInterval</key><integer>30</integer>
    <key>StandardOutPath</key>
    <string>{{ site_agents_my_log }}</string>
    <key>StandardErrorPath</key>
    <string>{{ site_agents_my_error_log }}</string>
</dict>
</plist>
```

**Scheduled interval** (periodic cron-like job, e.g., hibernate-disk-check):
```xml
    <key>StartInterval</key>
    <integer>1800</integer>
    <!-- or: StartCalendarInterval with Hour/Minute -->
    <key>RunAtLoad</key><true/>
    <!-- no KeepAlive for interval jobs -->
```

Copy the label and log paths from defaults; use `{{ }}` Jinja2 syntax for values.

### 3. Add tasks (`tasks/main.yml`)

Two steps — render the plist then bootstrap it:

```yaml
- name: Render my-agent LaunchAgent
  ansible.builtin.template:
    src: my-agent.plist.j2
    dest: "{{ site_agents_my_plist }}"
    mode: "0644"
  register: _my_plist

- name: Manage my-agent LaunchAgent
  ansible.builtin.include_tasks: launchagent.yml
  vars:
    _agent_label: "{{ site_agents_my_label }}"
    _agent_plist_path: "{{ site_agents_my_plist }}"
    _agent_plist: "{{ _my_plist }}"
    _agent_script: "{{ site_agents_my_plist }}"
```

The `launchagent.yml` sub-task handles:
- Probing current launchd state
- Booting out when the plist changed (to pick up new config)
- Bootstrapping when unloaded
- Kickstarting when only the script (not plist) changed

For agents that install an executable script (like system-state-backup), use
`ansible.builtin.template` or `ansible.builtin.copy` to place the script first,
then pass its register (`_my_script`) as `_agent_script` instead of the plist path.

### 4. Update `just site-agents-status`

Add a status check block to the `justfile`:

```just
@if launchctl print "gui/$(id -u)/com.{{ site_ns }}.my-agent" >/dev/null 2>&1; then \
  echo "launchd: loaded (com.{{ site_ns }}.my-agent)"; \
else \
  echo "launchd: not loaded (com.{{ site_ns }}.my-agent)"; \
fi
```

### 5. Deploy

```bash
just site-agents-check   # dry-run first
just site-agents-apply   # deploy
just site-agents-status  # verify
```
