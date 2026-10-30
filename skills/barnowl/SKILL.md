---
name: barnowl
description: >-
  Do anything in BarnOwl or Zephyr from plain English: list or change
  subscriptions, read logs, locate someone, send a zephyr, or run a BarnOwl
  command in the live client. Use when the user runs /barnowl, the shell
  command gr or go, or asks to list subscriptions, subs, zwrite, a zephyr
  class, or anything in BarnOwl.
argument-hint: list my subs
---

# BarnOwl, in plain English

Turn the request into the smallest real BarnOwl or Zephyr operation and run it.
The helper is `~/src/djbclark-ade/skills/barnowl/scripts/bo`. Read a command
you do not already know from `~/src/barnowl/commands.c` (`OWLCMD_*` name and
the summary string). That file is the command list. BarnOwl source is
`~/src/barnowl` (github.com/barnowl/barnowl, 1.10).

From a shell, `gr list my subs` runs this skill through Grok and `go list my
subs` runs it through goose: `gr` is `bin/gr`, `go` is `bin/go`. `gr` uses
`grok-4.5` at low effort, the weakest Grok model available; `go` uses goose's
own configured model. Inside any client, `/barnowl` and a sentence such as
"list my subscriptions" are the same request. The old shell `g` and the slash
`/g` are gone: `gr` is Grok, `go` is goose. `subs` means subscriptions.

At BarnOwl's `:` prompt, `g` is the command in `g-cmd.pl`, loaded from
`~/.owl/startup`. `:g show my subs` opens the live subscription list in the
popup. Leave every other `:g` request for the shell command `gr` or `go`. A
model driving this same window would stall on the command that started it.

## Which client

The persistent BarnOwl is the tmux session `barnowl`, started and repaired by
`bo-a` (`bin/bo-a`, linked into `~/.local/bin`; the operator runs it). `bo` talks only to that session.
A second `barnowl` process may be sitting on another tty. Do not type into it.

`zctl retrieve` fails here (`No such file or directory while finding
WindowGram port`) because BarnOwl, not zwgc, holds the port. Live
subscriptions come from `bo subs`.

## Safety

Do the thing the sentence asks for.

- A read (`bo subs`, `bo file`, `bo locate`, `bo capture`, reading `~/zlog`,
  `getvar`) runs immediately.
- Subscribe, unsubscribe, punt, or change a startup command only when the
  sentence asks to change that subscription or setting.
- Send a zephyr only when the sentence asks to send one, and send only the
  text it gives. Personal zephyrs go to a user. Class zephyrs need the class
  it names. Do not invent a message.
- `quit`, `unsuball`, and `zctl cancel` only when the sentence says to leave
  or drop every subscription.
- If `bo` exits 3, BarnOwl is mid-compose or already on a command line. Say so
  and stop. Do not send more keys.

## What to run

| Request | Run |
|---|---|
| list subscriptions, my subs, what am I on | `bo subs` |
| subscriptions that will reload next start | `bo file` (same text as `~/.zephyr.subs`) |
| subscribe to a class | `bo run 'sub CLASS * *'` |
| subscribe for this session only | `bo run 'sub -t CLASS * *'` |
| unsubscribe | `bo run 'unsub CLASS * *'` |
| where is a person | `bo locate USER` |
| recent personals or a class log | read `~/zlog/people/USER` or `~/zlog/class/CLASS` |
| send | `bo run 'zwrite ... -m TEXT'` with the flags from `commands.c` |
| any other BarnOwl command | `bo run '<command>'` |
| a value only Perl can see | `bo perl '<expression>'` (one expression) |

`bo subs` prints Zephyr triples `<class,instance,recipient>`. The server adds
personals (`message,personal,…` and `message,*,…`) that are not lines in
`~/.zephyr.subs`. When the user asks for "my subs", print the `bo subs` list.
Mention the file only when they ask what is saved, or when a live triple is
not in the file and that difference matters.

Instance and recipient default to `*` on `sub` and `unsub`. The personal class
is `message`, instance `personal`. A class zephyr is `zwrite -c CLASS -i
INSTANCE`. A personal is `zwrite USER`. `-m` must be the last zwrite argument.

`bo run` prints the type window. If the command opens a pager (show, help,
getsubs), `bo` prints that screen and closes it with `q`. Prefer `bo subs`
over `:getsubs` so the pager does not flash.

Logs are already on: `~/.owl/startup` sets logging, classlogging, and
loggingdirection. New log text is under `~/zlog/`.

Tickets are Kerberos. If a send or `bo subs` says the ticket is gone, say so
and stop. Do not run `kinit`.

## On this machine

`~/src/djbclark-ade/bin/gr` is linked at `~/.local/bin/gr` and `bin/go` at `~/.local/bin/go`, and `~/.local/bin` is on `PATH` from `~/.bashrc`. `/barnowl` is `claude/commands/barnowl.md`, linked at `~/.grok/commands/barnowl.md` and `~/.claude/commands/barnowl.md` (zcode has its own wrapper at `zcode/commands/barnowl.md`). The skill itself is linked by `bin/skill-everywhere barnowl` into every client, goose included (`~/.agents/skills/barnowl`). `go` runs `goose run --no-session -q --output-format json -t "Use the barnowl skill for this BarnOwl request: …"` and prints only the final assistant text.

## Answer

Print the command result, not a retelling of the procedure. For a subscription
list, one triple per line, class then instance then recipient. For a send,
say who it went to and the exact text.
