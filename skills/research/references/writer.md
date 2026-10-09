# Writer brief (one writer, whole argument)

Input: `plan.md`, `evidence.jsonl`, every `notes/*.md`, `counter.md`, and
the saved text in `sources/*.txt`. Output: `research/<slug>/report.md` (on
a host that refuses that basename to a sub-agent, `draft.md`; the lead
renames it). You do not search the web or fetch anything. If the evidence
does not support an answer, the report says so; you do not fill the gap
from memory.

## Shape

1. **BLUF.** The answer in the first paragraph, with a confidence level
   (high / medium / low) and the one-sentence reason for that level. For a
   comparison, the recommendation and the condition under which it flips.
2. **Signpost headers.** Each section header states the section's finding
   ("Caching halves p95 latency in every benchmark found"), not its topic
   ("Latency"). A reader of the headers alone gets the argument.
3. **Dense prose.** Paragraphs that carry the argument, with inline
   citations `[E0012]` at the end of the sentence they support. Tables for
   comparisons across options or studies. Bullets only for genuinely
   parallel items.
4. **Contradicting or limiting evidence.** Its own section, always present,
   drawn from `counter.md`. For every contested claim show both quotes'
   IDs and say what the contradiction covers. "None found" names the
   searches that looked.
5. **What was not established.** Its own section, always present: the
   hypotheses that stayed open, the sources not searched (paywalled,
   non-English, no index), the questions that need a human or an
   experiment.
6. **Evidence table.** At the end: one row per cited ID with claim, source
   (title, year, kind, family), locator, and the tags below. Only IDs cited
   in the body appear; an uncited source is not listed anywhere.

## Labels and tags

Every substantive sentence is one of:

| label | meaning | how it reads |
|---|---|---|
| fact | the quote states it, and a second independent family agrees | plain statement + IDs |
| source-claim | one source says it; not independently corroborated | "X reports that …" + ID, tagged `single-source` |
| inference | your reasoning over quotes | "This suggests …" / "Taken together …" |
| unknown | nothing found either way | said as such, in the gaps section |

Tags, inline after the citation where they apply: `single-source`,
`contested` (counter-evidence exists; both IDs cited), `stale` (older than
the freshness need in the plan), `preprint` (not peer-reviewed), `abstract-
only` (full text not read).

## Rules

1. Claim wording stays as close to the quote as English allows. Hedges in
   the source ("in a sample of 12", "under laboratory conditions", "may")
   survive into the claim.
2. Every number in the body appears in a quote in `evidence.jsonl`; the
   checker enforces existence, you enforce meaning (same unit, same
   population, same period).
3. Do not reconcile contradictions by averaging or by choosing the newer one
   silently. Say which you weight and why, or leave it contested.
4. Preprints, press releases, vendor claims and secondary reports are named
   as such in the sentence that uses them.
5. No invented references, no citations to sources not in
   `evidence.jsonl`, no URLs in prose (they are in the evidence table).
6. Length follows the question: a quick-tier answer is a page; a deep-tier
   review is as long as the evidence table needs, not longer.
7. After the reviewer's flags come back, fix or cut each one; never defend
   a flagged sentence by adding adjectives.
8. **Read the saved sources before writing "unknown".** The quote field is
   only what a worker chose to carry; `sources/<source_id>.txt` is the whole
   page. Before labelling a fact unknown, open the saved text of every
   source in the relevant family. If the fact is there, append a row quoting
   it (same schema, ids in the range the lead assigned you, e.g. E09xx), run
   `research_check.py quotes` so it is verified, and cite it. Seen
   2026-10-09: an endpoint, auth header, model id and output price were all
   in the saved sources and the report called them unknown.
9. **Excerpt rows are leads.** A row the checker reports as an excerpt
   (`kind` `excerpt`, or a source header saying "search-result excerpt") is
   cited only as "seen only as a search excerpt", never as support, and it
   adds nothing to confidence.
10. **Code blocks say what they are.** The first line of every code block
    says `tested` (and the report says how it was run) or `sketch, not
    runnable`; a sketch names every undefined helper and every assumed
    field. A comment never claims behaviour the code does not have (a
    `None` price commented "fails closed" raised a TypeError instead,
    2026-10-09). Hard-coded values cite the row they come from.
11. **Name roles for the reader.** Write "the counter-evidence pass" and
    "the different-family review", not "the refuter" or "the reviewer";
    the reader did not see the run.
