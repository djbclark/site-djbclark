Screens captured on 2026-11-01 from the BarnOwl built from upstream git master (package
`1.11~git20250813.1f65aee-1`, https://forgejo.mit.edu/djbclark/barnowl-debian) on pastebin, in a scratch session on its
own tmux socket (140x40, TERM=tmux-256color, UTF-8, `typewinsize 1`, `typewindelta 7`, eight synthetic class messages,
`-n`), by the same key sequence as `../barnowl-1.10`, with `tmux capture-pane -p -J`.
Same names as the 1.10 set except 13 (the getsubs popup needs zephyr; it is not captured here).
`tests/test_barnowl_skill.py` judges them with `bo`'s idle check exactly as it judges the 1.10 screens. The only
differences from 1.10 are the version string and `UNAUTH:` before the sender (the messages here carry `auth NO`).
