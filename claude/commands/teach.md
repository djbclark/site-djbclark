---
description: Today's one or two Claude Code things to install or start using, one prompt at a time
---

Follow the mounted `teach` skill exactly. Canonical copy:
`~/src/djbclark-ade/skills/teach/SKILL.md`.

Arguments: none = today's day as `scripts/next_item.py` picks it (the day
already done today if any, else the next unticked one; missed days never skip a
number), opened with the last day's command names; a day
number (`/teach 5`) = that day; `list` = print the schedule with ticks and stop.

Ask **one** AskUserQuestion per prompt, recommended option first, do the item
before asking the next, tick the box and commit when the day is done.
