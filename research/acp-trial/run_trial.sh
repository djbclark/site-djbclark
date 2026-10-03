#!/usr/bin/env bash
# Run each agent twice on the same task: over ACP and via its headless -p mode.
cd "$(dirname "$0")"; A=$PWD; rm -rf runs; mkdir -p runs; cd runs
P="In this directory, test_calc.py fails. Fix the bug in calc.py (do not edit test_calc.py), then run \`python3 test_calc.py\` to confirm it prints OK. Finish with one line: DONE or FAILED."
mk() { cp -R "$A/fixture" "$A/runs/$1"; echo "$A/runs/$1"; }
T="timeout 600"
acp() { local l=$1; shift; local d; d=$(mk $l); /usr/bin/time -p $T "$A/.venv/bin/python" "$A/trial_client.py" $l "$d" "$P" -- "$@" > $l.json 2> $l.time; }
hl() { local l=$1; shift; local d; d=$(mk $l); ( cd "$d" && /usr/bin/time -p $T "$@" ) </dev/null > $l.out 2> $l.time; echo "exit=$?" >> $l.out; }
acp acp-opencode opencode acp &
acp acp-copilot copilot --acp &
ANTHROPIC_MODEL=claude-sonnet-5-5 acp acp-claude npx -y @agentclientprotocol/claude-agent-acp &
hl hl-opencode opencode run "$P" &
hl hl-copilot copilot -p "$P" --allow-all-tools --allow-all-paths --silent &
hl hl-claude claude -p "$P" --model claude-sonnet-5-5 --permission-mode bypassPermissions --output-format json &
wait
for d in */; do d=${d%/}; ( cd $d && r=$(python3 test_calc.py 2>&1 | tail -1); cmp -s test_calc.py "$A/fixture/test_calc.py" && t=unchanged || t=EDITED; echo "$d test=$r testfile=$t" ); done > verify.txt
echo ALLDONE > ALLDONE
