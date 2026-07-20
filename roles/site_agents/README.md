# site_agents — control-node maintenance LaunchAgents (Phase F1)

Adopts the hand-managed `com.djbclark.system-state-backup` and
`com.djbclark.hibernate-disk-check` LaunchAgents into Ansible-managed site
roles. Scripts install to `~/.local/bin`; plists render to
`~/Library/LaunchAgents/com.<site_ns>.*`.

## What it manages

| Agent | Label | Schedule | Output |
| ----- | ----- | -------- | ------ |
| system-state-backup | `com.{{ site_ns }}.system-state-backup` | Daily 12:00 + RunAtLoad | `{{ homebrew_prefix }}/var/system-state` + mirror `~/system-state` |
| hibernate-disk-check | `com.{{ site_ns }}.hibernate-disk-check` | Every 1800s + RunAtLoad | macOS notification when `/` free GB &lt; threshold (default 25) |

Homebrew prefix follows the LiteLLM / stayturgid pattern: Apple Silicon
`/opt/homebrew`, Intel `/usr/local` (from `ansible_facts.architecture`).

## Apply

```bash
cd ~/ops/site-djbclark
just site-agents-apply          # first apply
just site-agents-check          # dry-run (ansible --check)
just site-agents-status         # launchctl print both labels
```

Playbook targets `localhost` (control node). No secrets required.

## Manual one-shot

Safe to run by hand; system-state-backup only overwrites capture files on
success (does not clobber good snapshots on partial failure):

```bash
~/.local/bin/system-state-backup.sh
~/.local/bin/hibernate-disk-check   # notifies only when below threshold
```

## Rollback

Boot out the site labels (stops scheduled runs):

```bash
uid=$(id -u)
launchctl bootout "gui/$uid/com.djbclark.system-state-backup"
launchctl bootout "gui/$uid/com.djbclark.hibernate-disk-check"
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
```

Expected: both labels loaded in `gui/<uid>`; system-state LAST_RUN.txt updated;
`~/system-state` mirror refreshed.
