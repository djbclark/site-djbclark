# Refuter brief and reviewer brief

Two separate roles that both work against the grain. Neither writes the
report. Both run in their own context, with a brief that does not include
the lead's current conclusion.

## Refuter (step 4): find what would contradict or limit

Input: `plan.md` (the hypotheses and what would refute them), the list of
high-impact claims with their `[E####]` IDs, and the same tools and budget as
a worker. Output: `research/<slug>/counter.md` and evidence rows in your
assigned ID range, same schema as `references/worker.md`.

1. For each hypothesis and each high-impact claim, search for evidence that
   would contradict it, limit its scope, or show it failed to replicate:
   failures, retractions, corrections, critiques, replications, deprecations,
   "limitations" sections, competing results, later versions.
2. Phrase every query neutrally and without the hypothesis wording. Write
   the query as the opposing side would.
3. Where a central source has a citation graph (papers, standards, court
   decisions), search the works that cite it; contradicting statements live
   there more often than in the source itself.
4. Log counter-evidence with the same discipline as supporting evidence:
   opened source, verbatim quote, locator, family. One-sided reporting of
   the counter side is as bad as one-sided reporting of the main side.
   A search excerpt is a lead, not a row: if you cannot open the page, put
   the URL and the excerpt under `## Leads (not opened)` in `counter.md`
   and log no evidence row. If you keep an excerpt row for traceability,
   set `kind` to `excerpt`; the checker drops it from the gate and the
   writer may cite it only as a lead (2026-10-09: five of ten refuter rows
   were excerpts and counted toward the gate).
5. `counter.md` has one section per hypothesis or claim:
   `### [E####] <claim>` then `Verdict:` one of supported / contested /
   limited / refuted / no-counter-evidence-found, then `Both sides:` the
   supporting quote and the contradicting quote side by side with their IDs,
   then `Scope:` what the contradiction actually covers (population, period,
   version, conditions). Automated contradiction detection over-flags, so a
   verdict without both quotes is not allowed.
6. Also list, under `## Not searched`, the routes you did not take and why
   (paywalled, non-English, no citation index), so the lead can say so.

## Reviewer (step 7): refute-mode read of the draft

Input: `report.md`, `evidence.jsonl`, `counter.md`, and the saved text in
`sources/*.txt`. Do not read `notes/`. Output: `research/<slug>/review.md`.
You change nothing in the draft.

1. For each claim in the report, find its `[E####]` rows and decide whether
   the quote supports the claim as written. Flag: claim stronger than quote,
   claim not in any cited quote, number not in any quote, inference labelled
   as fact, single-source claims not tagged, contested claims with the
   counter side missing, stale sources presented as current, preprints not
   labelled, a conclusion the counter-evidence section undercuts, a fact
   called unknown that a saved source states (then the fix is "add a row
   quoting line N of S###", not cut), an excerpt row cited as support, and
   a code block that claims to run or to behave in a way its text does not.
2. For each flag write: location (section, sentence), the `[E####]` IDs, the
   quote, why it fails, and the smallest fix (cut, weaken, retag, add the
   counter quote).
3. Check the "What was not established" section against `counter.md`'s
   `## Not searched` and the Gaps in the plan: anything missing is a flag.
4. End with `Independence:` and one of `independent (different model
   family)` or `non-independent (same family, fresh context)`. The lead
   copies that line into the report's confidence statement. A review that
   cannot say which it is counts as non-independent.
5. Be specific and short. "Seems fine" is not a review; "no findings" with
   the claim count checked is.
