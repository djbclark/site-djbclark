Screens captured on 2026-11-01 from a real BarnOwl 1.10 (Debian 1.10-2) client on pastebin, in a scratch
session on its own tmux socket (140x40, TERM=tmux-256color, UTF-8, `typewinsize 1`, `typewindelta 7`,
as in the live ~/.owl/startup), with `tmux capture-pane -p -J`. The message list holds eight synthetic
class messages. `tests/test_barnowl_skill.py` judges them with `bo`'s idle check.

01-idle, 02-after-perl-ok (bo's own `q{ok}` leaves "ok" on the message line), 03-command-line-empty,
04-command-line-typed (`command: zwrite eve`), 05-after-cancel, 06-compose (`----> zwrite eve`),
07-after-compose-cancel, 08-question (`bo asks: ...`), 09-after-question, 10-popup-show-commands
(popup box with message text beside its edge), 11-after-q, 13-popup-getsubs, 15-search-prompt.
