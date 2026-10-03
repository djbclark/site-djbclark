# book-to-kb

Query a long technical book from any AI coding agent without ever loading it into
the context window.

A 500-page programming book is ~115,000 tokens. Pasting it in is impossible;
summarising it loses the thing you wanted (the author's exact words). `book-to-kb`
converts the book once — mechanically, costing **no model tokens** — into clean
Markdown chapters plus a **~2,500-token index**, and gives the agent three ways to
read it cheaply.

Measured on *Learning CFEngine* (O'Reilly, 2nd ed., 70,140 words):

| access path | tokens | lossless |
| --- | --: | --- |
| `book-kb query 'edit_line' learning-cfengine` | ~2,500–5,200 | yes |
| `book-kb toc` + read one chapter | ~2,500 + ~1,250 | yes |
| semantic search, 5 ranked excerpts | ~600 | yes |
| reading the whole book | 115,339 | yes |

A **46:1 reduction** to get oriented, and the answer still quotes the author and
cites a `file:line`.

## Install

Paste this into any agent CLI (Claude Code, Codex, Copilot, Cursor, opencode, …):

```
Install the book-to-kb skill and its toolchain for me.

1. Clone https://github.com/djbclark/site-djbclark (or sparse-checkout just
   tools/book-to-kb) into a scratch directory, and cd into tools/book-to-kb.
2. Make sure `uv` is installed. If not: `curl -LsSf https://astral.sh/uv/install.sh | sh`
   on Linux/macOS, or `brew install uv`. uv manages its own Python, so my system
   Python version does not matter.
3. Run `./install.sh`. It creates a Python 3.12 venv with docling (about 1.2 GB,
   a few minutes), installs the `book-kb` CLI to ~/.local/bin, symlinks the
   book-to-kb skill into every agent skills directory on this machine, and
   creates ~/kb.
4. Run `book-kb doctor` and show me the output. Tell me if ~/.local/bin is not on
   my PATH and how to add it.
5. Then tell me the one command to add my first book, and confirm you can see the
   book-to-kb skill.

Install nothing else. Basic Memory is optional — only needed for semantic search,
and the index and grep paths work without it.
```

<details>
<summary>Or install it by hand</summary>

```bash
git clone --depth 1 https://github.com/djbclark/site-djbclark.git
cd site-djbclark/tools/book-to-kb
./install.sh            # --check first, if you want to see what it would do
```

</details>

## Use

```bash
book-kb extract ~/books/some-book.epub     # add a book (idempotent, sha256-guarded)
book-kb list                               # what's in the KB, and what each costs to read
book-kb toc <slug>                         # the chapter index — read this first
book-kb toc <slug> --deep                  # every sub-heading, with file:line anchors
book-kb query '<regex>' <slug>             # exact match over the chapters
book-kb index                              # register with Basic Memory for semantic search
book-kb doctor                             # check the toolchain
```

The agent-facing half is `skills/book-to-kb/SKILL.md`, which teaches an agent to
query cheapest-first and — more importantly — to **verify an extraction before
trusting it**.

## How it works

```
book.epub ──► <pre> normalisation ──► docling ──► one big Markdown file
                                                        │
                        ┌───────────────────────────────┤
                        ▼                               ▼
              $KB_ROOT/raw/<slug>.md          chapter splitter (fence-aware)
              (full text, never read)                    │
                                                         ▼
                                   $KB_ROOT/md/<slug>/INDEX.md    ~2.5k tokens
                                                        /OUTLINE.md
                                                        /chapters/*.md
                                                        /meta.json
```

Three design choices that matter:

1. **The index is the product.** Chapters are split so the median is ~1,250 tokens
   and nothing exceeds ~8,000, and `INDEX.md` lists each one with its token cost
   so an agent can budget a read. `OUTLINE.md` is kept separate because the full
   sub-heading map is ~5k tokens — you pay for it only when the chapter table
   wasn't specific enough.
2. **The splitter tracks code fences.** Without that, `# ignore all .a files`
   from a `.gitignore` example becomes a chapter. (It did.)
3. **Exact search is the one that proves anything.** Semantic search ranks by
   similarity and returns its closest N notes whether or not any of them match, so
   it is for discovery; `book-kb query` is for proof.

## Prefer the EPUB when a book ships both

Counter-intuitive, and worth knowing before you spend three minutes on a PDF:

| | EPUB | PDF |
| --- | --- | --- |
| code listings | correct, indented, multi-line | **collapsed onto one line** |
| inline code markup | preserved | lost |
| real tables | 37 | 35 |
| time (247 pages) | 17 s | 188 s |

The PDF produced *more* code fences — 594 against 420 — which looks like a win
until you read one. Fence count is a trap.

## The docling bug this works around

Technical EPUBs frequently wrap every syntax-highlighted *token* in its own
`<code>` element inside a single `<pre>`. docling maps each to inline code, so a
listing arrives as a run of backtick fragments **with spaces injected inside
string literals** — `" s1 "` where the source says `"s1"`, quietly changing what
the code means.

On the test book that produced **12 recovered code blocks across 500 pages**.
Flattening each `<pre>` to plain text before docling sees it produced **210**.

Reported upstream as
[docling-project/docling#4549](https://github.com/docling-project/docling/issues/4549);
minimal repros in [`docs/docling-pre-bug/`](docs/docling-pre-bug/). If you are
*publishing* an EPUB, the correct markup is one `<code>` wrapping the block with
tokens as `<span class="…">` — which is what Pygments emits natively.

## Requirements

- **[uv](https://docs.astral.sh/uv/)** — the only hard prerequisite; it manages
  its own Python.
- ~1.5 GB of disk (docling pulls torch for PDF layout analysis).
- **Optional:** [Basic Memory](https://github.com/basicmachines-co/basic-memory)
  for semantic search, `ripgrep` for faster exact search (falls back to `grep`),
  `poppler` for PDF page counts, Calibre for MOBI/AZW (`ebook-convert in.azw3 out.epub`).

Configuration, all environment variables: `KB_ROOT` (default `~/kb`),
`BOOK_KB_VENV` (`~/.local/share/book-kb/venv`), `BOOK_KB_BM_PROJECT` (`books`),
`BOOK_KB_PYTHON` (`3.12`).

## Not a replacement for book-to-skill

[`book-to-skill`](https://github.com/virgiliojr94/book-to-skill) distils a book
into named frameworks, principles, anti-patterns and voice — genuinely useful, and
something a chapter index cannot give you. It costs roughly the book's own size in
input tokens per book and keeps no source text.

They are complementary: `book-to-kb` for lookup and citation on every book,
`book-to-skill` on top for the few whose method you want to apply while working.
Full measured comparison: [`docs/book-kb-vs-book-to-skill.md`](docs/book-kb-vs-book-to-skill.md).

## Also here

`bin/clip` — a `pbcopy` wrapper for macOS. Agent shells typically run with
`LC_CTYPE=C`, so bare `pbcopy` writes MacRoman to the pasteboard and an em dash
pastes as `‚Äî`. `clip` forces UTF-8 and then verifies the pasteboard through
AppKit, because `pbcopy | pbpaste` applies the inverse mangling and cannot detect
the problem.

## Licence

MIT — see [LICENSE](LICENSE).
