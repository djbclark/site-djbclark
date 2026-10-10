---
name: report
description: Format a long Markdown report (research paper, spec, review) so it reads well in Marked 2 — numbered superscript citations, linked evidence table, descriptive file names, short paragraphs — and verify the render. Use when delivering or reformatting any document the operator will read in Marked 2.
---

# report — make a long Markdown document readable in Marked 2

Canonical copy: `~/src/djbclark-ade/skills/report/` (git: `~/src/djbclark-ade`);
every TUI reaches it through the skill-everywhere hub `~/ops/site-private/skills/report`.
Born 2026-10-10 from the `hiwymi/research/ai-heaven` delivery, where the operator
rejected three formats in a row (see "Why", below). Apply it before the first
`open -a "Marked 2"`, not after a complaint.

## 1. Rules

1. **File names say what the file is.** Never `report.md`, `plan.md`, `SPEC.md`,
   `transcript.md`: use `<slug>-research-report.md`, `<slug>-research-plan.md`,
   `<slug>-evidence.jsonl`, `<slug>-spec.md`, `<slug>-three-model-dialogue.md`.
   When a tool or skill expects the generic name (the `research` checker reads
   `report.md` and `evidence.jsonl`), keep a symlink at the generic name
   (`ln -s <slug>-research-report.md report.md`) and commit both.
2. **Citations are numbered superscript links, never bare ids and never
   Markdown footnotes.** Body form, one `<sup>` per run of adjacent citations,
   numbers by first appearance, space-separated, no commas:
   `<sup>[12](#E0927) [13](#E0931)</sup>`. Definitions are a numbered list under
   `## Citation footnotes`, one item per cited id in number order:
   `12. <a id="E0927"></a>E0927 — <claim> — <title> (<kind>; <family>), <locator>. <https://url>`.
   The URL is an autolink so it can wrap.
3. **An evidence table has no URL column.** The id cell links to the source
   (`[E0927](https://...)`); columns `id | claim | source (title, kind, family) | locator | tags`.
   Markdown cannot wrap a URL inside a cell, so a URL column makes the table
   unreadably wide.
4. **No walls of text.** Body paragraphs stay under ~180 words; an abstract is
   several paragraphs, one per topic. Split at sentence boundaries where the
   topic or source shifts; never reword while splitting (verify the token
   multiset is unchanged).
5. **Verify the render before saying it is done.** `open -a "Marked 2" <file>`,
   then capture only Marked's window (section 3) and look at it. Never take a
   full-screen capture: it records whatever else is on the operator's screen
   (another session's terminal, 2026-10-10).
6. **Say the file name in the delivery message** and reopen in Marked 2 after
   any rename.

## 2. Tools (stdlib Python, in `scripts/`)

A draft written with bare `[E0927]` markers (the `research` skill's writer form)
is converted in two passes, from the run folder's parent:

```
python3 -I ~/.claude/skills/report/scripts/reformat_citations.py <report.md>   # [E0927] -> [^E0927], table id linked, url column dropped, footnote defs
python3 -I ~/.claude/skills/report/scripts/cite_sup.py <report.md>             # [^E0927] -> <sup>[n](#E0927)</sup>, numbered anchored list
```

Both are idempotent (a converted file is left alone). Then the `research`
checker (`research_check.py quotes|numbers|claims|gate`) must still pass: its
`ID_RE` accepts `[E0927]`, `[^E0927]` and `(#E0927)`, and its numbers scan
strips `<sup>...</sup>` runs and stops at `## Citation footnotes`.

Paragraph splitting is judgement work: give it to a sub-agent with the brief
pattern in `references/paras-brief.md` (edit only the body, sentence-boundary
breaks, token multiset unchanged, no paragraph over 220 words, checker rc=0).

## 3. Capturing only the Marked 2 window

```
WID=$(swift -e 'import CoreGraphics; import Foundation; let l = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as! [[String: Any]]; for w in l { if (w["kCGWindowOwnerName"] as? String) == "Marked 2", ((w["kCGWindowName"] as? String) ?? "").contains("<file-stem>") { print(w["kCGWindowNumber"] as! Int); break } }')
screencapture -x -l "$WID" <scratchpad>/marked-win.png
```

(`python3` has no `Quartz` module on this machine; `swift -e` takes ~20 s the
first time.) Read the PNG with the Read tool and check: superscripts rendered
(no literal `[^E...` or `^E0100` text), repeated citations rendered, paragraphs
separated, table not wider than the window.

## 4. Why (what Marked 2 does with the alternatives)

Marked 2 renders with MultiMarkdown. Observed 2026-10-10 on a 57k-word report
with 575 evidence rows:

1. Inline `[E0927]` after every sentence: the operator called it "too
   distracting".
2. Markdown footnotes `[^E0927]`: MultiMarkdown parses two adjacent markers
   `[^A][^B]` as a reference link (`[text][label]`), showing `^E0100` as blue
   link text and losing both citations; and it cannot cite the same footnote
   twice, so every second citation of a row rendered literally. Commas between
   markers fixed the first problem, broke the operator's eye ("don't put commas
   between the superscripts") and did nothing for the second.
3. `<sup>[n](#id)</sup>` with an anchored numbered list: renders everywhere
   (MultiMarkdown, CommonMark, GitHub), repeats fine, no separators needed.

## 5. Skill maintenance

The two scripts started life in `hiwymi/research/ai-heaven/tools/`; this copy
is canonical. If the `research` skill's writer is ever changed to emit the
superscript form directly, keep `reformat_citations.py` for old drafts.
