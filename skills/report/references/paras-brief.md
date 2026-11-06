# Brief pattern: break up over-long paragraphs (formatting only)

Fill in the path, the scratchpad and the counts, append the delivery footer
(`acp-dispatch footer --report <scratchpad>/paras-report.md`), and dispatch to a
capable model at high effort (an Agent-tool sub-agent is fine; the reads stay
out of the lead's context).

---

Working directory: `<repo dir>`. File: `<report path>`. Edit only the body
(everything before the line `## Evidence table`). Do not touch the evidence
table, the `## Citation footnotes` section, headings, the TOC, or any wording.

The operator finds the text a "big wall": `<N>` body paragraphs run over 180
words, several over 400. Split every paragraph over ~180 words into 2-4
paragraphs of roughly 60-150 words each, breaking only at sentence boundaries
where the topic or the source shifts. Insert a blank line at each break; change
nothing else: no reordering, no rewording, no dropped or added words, no change
to the `<sup>[n](#E####)</sup>` citation markers (a marker stays attached to the
sentence it follows). Paragraphs under ~180 words stay as they are. Prefer one
paragraph per source or sub-claim.

Method: write a small Python helper in the scratchpad that lists the long
paragraphs with their sentences, then apply the breaks with the Edit tool (or a
script that inserts "\n\n" at the chosen sentence starts). Do not rewrite the
file by regenerating text from memory.

Verification (must pass, each to its own log in the scratchpad with the exit
status appended; never through a pipe):

1. Token check: the body's whitespace-separated token count before and after
   must be identical, and the sorted multiset of tokens identical (only
   whitespace changed). Print both counts.
2. `python3 -I ~/.claude/skills/research/scripts/research_check.py claims <run>`
   and `... numbers <run>` both rc=0.
3. No body paragraph over 220 words remains (print the counts over 180 and
   over 220).

A backup of the file as you received it is at `<scratchpad>/report.pre-paras.md`.

Report file (see footer): STATUS line; paragraphs split (count), token counts
before/after, the three check results one line each, DECIDED items, then DONE.
