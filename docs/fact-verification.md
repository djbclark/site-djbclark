# Checking facts a model mined from sessions

`bin/mine_sessions.py` reads session transcripts out of the S1 evidence store
and asks a model to write down what is durably true. That is a genuinely good
way to find knowledge nobody would sit down and write, and it produces claims
nobody has checked. `bin/verify_facts.py` is the check.

Snapshot **2026-08-24**, from the first 78-fact run.

## Why the model's own confidence field is not the answer

`mine_sessions` asks the model for `"confidence": "high"|"medium"`. In the
first run **72 of 78 facts said "high"**. A field that is nearly constant
cannot rank anything, and self-reported confidence is not evidence in the
first place.

There is a sharper version of this problem in the literature. Consolidation
pipelines systematically **upgrade tentative source material into confident
assertions** — a hedged remark in a transcript becomes a dated, declarative
fact that later agents obey. Two findings from that work shaped this tool:

- **A passive `unverified` tag is not a reliable brake.** Measured across five
  models it changed behaviour anywhere from never to most of the time. Tagging
  our 78 facts "unverified" and moving on would have felt like diligence and
  bought approximately nothing.
- **A second, independent source is what actually works.** Adding an
  authoritative cross-check eliminated the failure entirely in that study,
  because it gives the reader something to discriminate _with_ rather than a
  mood to be cautious about.

So this tool never asks how sure anyone is. It asks two questions with
checkable answers, and reports what it checked.

## The two checks

### 1. Grounding — is the claim in its own evidence?

Pull the concrete literals out of a fact — paths, flags, env vars, `just`
recipes, backticked code — and look for them in the passages the fact was
mined from. A fact whose own subject matter appears in none of its sources was
not read out of the evidence.

This also repairs a real defect in the pipeline. `mine_sessions.py:210` stamps
**every fact in a batch with all six of the batch's passage ids**, so
provenance is batch-level and no fact can be checked against the passage it
actually came from. Grounding each claim to its own source text is the
standard fix for exactly this; the scoring pass recovers fact→passage
attribution after the fact by finding which passage carries the claim's
literals.

Threshold: a third of a fact's literals, or two absolute. One literal in
common is what any two passages about the same tool will share.

### 2. Machine truth — is it still true here?

This corpus is unusual in a way that helps enormously. The facts are about
**this machine**, not about the world. `~/.hermes/config.yaml` either exists or
it does not. `just ops-memory-sync` either is a recipe or it is not. So the
second source the research says you need is not another model — it is the
filesystem, and it is free, instant, and not guessing.

Only existence is ever read. Several of these paths are credential surfaces;
whether a file is there is worth knowing and its contents are nobody's
business.

### 3. Entailment (`--entail`, opt-in)

Only for facts stage 1 pinned to a passage: ask a cheap model whether that
passage really establishes the claim, rather than merely discussing the topic.
This is the only stage that spends tokens, which is why it is a flag.

## Reading the output

Every verdict names what was checked, never how confident anything felt.
`ungrounded` (the sources do not contain the claim's subject) and
`no-literals` (the fact is too abstract for this check) are deliberately
different words. Collapsing them into one is how a knowledge base launders a
guess into a fact.

The number that matters is the cross-tab, because neither axis alone is
enough — a claim can be perfectly grounded in a transcript that has since gone
stale, or true today but invented rather than observed.

First run, 78 facts, 24 seconds, $0:

|                                       |     |
| ------------------------------------- | --- |
| grounded **and** machine-confirmed    | 9   |
| grounded, nothing probeable           | 31  |
| no literals **and** nothing probeable | 30  |
| flagged for a human                   | 6   |

Two of the six flagged were real errors, confirmed by hand:
`~/.config/secretspec/atlassian.env` and `~/.hermes/cache/blocked-scripts/`
are both named confidently by facts and neither exists.

More interesting is the pattern the cross-tab exposes: **three facts are
machine-confirmed but ungrounded**. They state something true about this
machine that their cited evidence does not support — right answer, fictional
provenance. That is precisely the failure the research describes, and no
amount of asking the model how sure it was would have surfaced it.

The 30 unfalsifiable facts are not wrong. They are claims about judgement and
rationale rather than about artifacts, and they need a different kind of
review — which is worth knowing before anyone reports "78 facts verified".

## Reusing this for other review passes

The shape generalises to any "a model produced a pile of claims, now what"
problem, and the ordering is the point:

1. **Deterministic checks first, always.** They cost nothing, they never
   hallucinate, and they narrow the expensive stage's input. Here they took
   78 facts down to the handful worth a model's attention.
2. **Extract literals and check them against reality.** Anything naming a
   path, a command, a flag, a version, or an API surface can be re-probed. Do
   that before asking anyone's opinion.
3. **Make the checker's own bugs loud.** The first run here scored almost
   everything ungrounded because the passage reconstruction dropped the
   anchor's neighbours — mass fabrication and a broken checker look identical
   in the output. Spot-check by hand before believing a bad result; both
   fixes in this tool's history came from that.
4. **Never let an ambiguous signal decide.** Command names and repo-relative
   paths are recorded and displayed here but cannot condemn a fact on their
   own, because a backticked word is as often a subcommand as a binary and the
   repo list is a guess.
5. **Say what you checked, not how you felt.** Including an honest
   "unfalsifiable by this method".

## Running it

```bash
python3 bin/verify_facts.py check FACTS.json           # deterministic, free
python3 bin/verify_facts.py check FACTS.json --entail  # + model entailment
python3 bin/verify_facts.py check FACTS.json --json -o out.json
```

Mined facts and their verdicts live in `~/.local/state/mined-facts/` — **not**
in this repo, which is public and which they are not safe for, having been
distilled from private sessions.
