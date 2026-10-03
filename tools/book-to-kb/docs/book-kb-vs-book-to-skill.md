# book-kb vs /book-to-skill — measured token cost

All numbers from the same source: the *Learning CFEngine* EPUB (O'Reilly, 2nd
ed., 70,140 words). Token counts are bytes/4, applied
identically to both sides. Measured 2026-10-03.

## Build cost — paid once per book

|  | book-kb | /book-to-skill |
| --- | --- | --- |
| Agent tokens to build | **~0** (fully mechanical) | **~91k input minimum** — Steps 3, 7 and 8 require reading the whole book, then generating summaries |
| Wall clock | 21 s | minutes of agent turns |
| Repeatable without an agent | yes (`just book-add`) | no |

`book-kb` spends no model tokens at all: docling, the splitter and the index are
deterministic. `/book-to-skill` must read the book to distil it, so every book
costs roughly the book's own size in input tokens, plus generation.

## Per-query cost — paid every time you use it

| Access path | tokens | lossless? |
| --- | --: | --- |
| `just book-query 'convergen' learning-cfengine` | ~2,531 | yes |
| `just book-query 'bundlesequence' …` | ~3,955 | yes |
| `just book-query 'edit_line' …` (a very common term) | ~5,153 | yes |
| `just book-toc` + one median chapter | ~2,495 + ~1,243 = **~3,738** | yes |
| `search_notes(project="books", …)`, 5 ranked excerpts | ~600 | yes |
| **book-to-skill**: SKILL.md body on trigger | up to **4,000** | no — a distillation |
| **book-to-skill**: + one chapter summary (technical) | +1,200–1,800 | no |
| Reading the raw book | 115,339 | yes |

book-to-skill's figures are its own documented budgets (`SKILL.md` lines 447–448
and 557: "Keep SKILL.md body under 4,000 tokens"), not estimates.

## Verdict

**Per query, book-kb is cheaper and lossless.** A typical lookup is ~0.6–3.7k
tokens against ~5.2–5.8k for a skill trigger plus one chapter summary, and
book-kb returns the author's actual words — so it can answer "what exactly is the
syntax" and cite a `file:line`. A generated skill holds summaries; the source
text is gone, so a precise question sends you back to the book it no longer has.

**On the build, it is not close:** ~0 agent tokens against ~91k per book.

**They are complementary, not competing.** What a chapter index cannot give you
is the thing book-to-skill is actually for: named frameworks, principles,
anti-patterns and voice — *how the author thinks*, usable while working. The
sensible arrangement is book-kb as the lookup and citation layer for every book,
and book-to-skill on top for the few books whose method you want to apply, with
the KB still there to check the skill against.

## One correctness caveat, not just cost

book-to-skill's EPUB path is plain text — docling is its PDF-only route
(`book_to_skill/utils.py:1100`). On this book it recovered **0 code fences**
against **420** from book-kb, which flattens the EPUB's per-token `<code>`
markup before docling sees it. For a book that is mostly policy listings, that
is the difference between a usable KB and an unusable one. `just book-skill-env`
exports `PYTHON_BIN` so book-to-skill's *PDF* path gets docling too.
