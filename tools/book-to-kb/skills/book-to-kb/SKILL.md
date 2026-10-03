---
name: book-to-kb
description: >-
  Add a book or long document (EPUB, PDF, DOCX, HTML, Markdown, TXT, RTF) to a
  local token-efficient knowledge base, so it can be queried from any agent
  session without loading it into context: docling extraction, chapter split, a
  ~2.5k-token index, and optional semantic search. Use when the user gives one or
  more book paths, says "add this book", "index this PDF/EPUB", "put this in the
  KB", or asks how to query a book already in it. Not for turning a book into an
  agent skill of frameworks and voice — that is book-to-skill, which is
  complementary.
---

# book-to-kb

Turn a document into a queryable corpus, not a context-window problem. The
pipeline is mechanical and costs **no model tokens**: docling → clean Markdown →
chapters → a chapter index. Your job is the judgment around it — picking the
source format, naming the slug, and **verifying the extraction actually worked**
before telling the user it did.

Implementation is `book-kb`, installed alongside this skill. Never reimplement
it; call it. If it is not on `PATH`, it is at `$BOOK_KB_BIN` or
`~/.local/bin/book-kb`.

Layout, all overridable by environment variable:

| | default | env var |
| --- | --- | --- |
| KB root | `~/kb` | `KB_ROOT` |
| docling venv | `~/.local/share/book-kb/venv` | `BOOK_KB_VENV` |
| semantic project | `books` | `BOOK_KB_BM_PROJECT` |

## Step 1 — Resolve inputs

Expand the paths given; directories and globs are fine. Supported: `.pdf`,
`.epub`, `.docx`, `.pptx`, `.xlsx`, `.html`, `.md`, `.txt`, `.csv`, `.rtf`,
`.odt`, `.tex`, `.xml`.

**MOBI/AZW/AZW3 are not supported** — docling cannot read them. Say so and offer
Calibre (`ebook-convert book.azw3 book.epub`) rather than failing obscurely.

Check the toolchain once with `book-kb doctor`. If the venv is missing, run the
installer from this package's README (~1.2 GB, one time).

## Step 2 — Pick ONE source per book

If a book is present in more than one format, **extract the EPUB, not the PDF**,
and say why in one line. Measured on the same book in both formats:

| | EPUB | PDF |
| --- | --- | --- |
| code listings | correct, indented, multi-line | **collapsed onto one line** |
| inline code markup | preserved | lost |
| real tables | 37 | 35 |
| extraction time | 17 s | 188 s (247 pages) |

The PDF's fence *count* was higher (594 vs 420) and that is a trap — the code
inside those fences had lost its line structure. **Never judge extraction quality
by fence count alone.**

Use the PDF only when there is no EPUB, or when the EPUB fails Step 4.

## Step 3 — Extract

```bash
book-kb extract <path>             # slug derived from the filename
book-kb extract <path> --slug <s>  # when the filename is unhelpful
```

The slug is the handle the user and every other agent will type. Derive it from
the book's real title, lowercase-kebab, no edition or year: `learning-cfengine`,
not `learning_cfengine_2nd_edition_final`.

Idempotent — re-running on an unchanged file is a no-op (sha256 guard). Add
`--force` after a pipeline change. For a first look at a very long PDF,
`--pages 1-40` keeps it cheap.

**Run a long PDF in the background.** Roughly 0.8 s/page, and the first PDF ever
converted also downloads docling's layout models.

## Step 4 — Verify, before claiming success

The step that matters. Extraction can "succeed" and produce unusable output.
Check all four:

```bash
slug=<slug>; d="${KB_ROOT:-$HOME/kb}/md/$slug"
python3 -c "import json;m=json.load(open('$d/meta.json'));print(m['title'],'|',m['chapters'],'chapters |',m['tokens'],'tokens')"
echo "fences: $(cat $d/chapters/*.md | grep -c '^```')"
for f in $d/chapters/*.md; do echo $(( $(wc -c < "$f") / 4 )); done | sort -n \
  | awk '{a[NR]=$1} END{print "tokens/chapter: p50="a[int(NR*0.5)], "max="a[NR]}'
echo "index: ~$(( $(wc -c < $d/INDEX.md)/4 )) tokens"
```

1. **Title** is the book's title — not "Table of Contents", "License" or the
   filename. `book-kb` reads EPUB `dc:title` and PDF `Title` for this. If it is
   still wrong, pass `--slug` and mention the metadata is poor.
2. **Code fences**, for anything technical. Near-zero on a programming book means
   extraction failed, not that the book has no code. Then read one listing: it
   must be multi-line and indented, not one long line.
3. **Chapter sizes**: p50 ~1–2k tokens, max under ~8k. One chapter holding most
   of the book means the heading split failed.
4. **Index cost**: `INDEX.md` should be 1–3k tokens. Over ~5k means the book has
   too many top-level sections to be a useful map; say so.

If (2) fails on an EPUB, that is usually
[docling#4549](https://github.com/docling-project/docling/issues/4549) — `<pre>`
losing its structure when it contains inline elements. `book-kb` already flattens
`<pre>` to work around it, so a failure here is a *new* variant: add a minimal
repro next to `docs/docling-pre-bug/` and tell the user, rather than shipping a
corrupt corpus.

## Step 5 — Index for semantic search (optional)

```bash
book-kb index
```

Registers the KB with [Basic Memory](https://github.com/basicmachines-co/basic-memory)
as project `books` and reindexes. It must report a non-zero note count: adding a
project does **not** index it, and the first run is slow because it loads the
embedding model. Skip this step entirely if Basic Memory is not installed — the
index and grep paths do not need it.

## Step 6 — Report

Give the user the slug, chapter count, index cost against whole-book cost, and
the query commands.

```
<slug>: N chapters, ~Xk tokens total. Index is ~Yk — a Z:1 reduction.
  exact    book-kb query '<regex>' <slug>
  outline  book-kb toc <slug>          (--deep for file:line anchors)
  semantic search_notes(project="books", query=...)
```

**If the book is authoritative for work done in a repo on this machine, offer to
add a pointer to that repo's `AGENTS.md`/`CLAUDE.md`** so future sessions query it
instead of guessing. Ask first; never edit repos unprompted.

## Hard rules

1. **Never read `${KB_ROOT:-~/kb}/raw/<slug>.md`.** That is the whole book. The
   index exists precisely so nothing has to.
2. **Semantic search is discovery, never proof.** It ranks by similarity and
   returns its closest N notes whether or not any match. To answer "does the book
   say X", use `book-kb query`.
3. **Keep the source.** `book-kb` copies it into `$KB_ROOT/sources/`.
4. **Never commit book text to a git repo.** The KB lives outside version control
   on purpose: books are large and usually not yours to redistribute. Only the
   path, slug and query commands belong in a repo.

## Not this skill

[`book-to-skill`](https://github.com/virgiliojr94/book-to-skill) distils a book
into frameworks, principles and voice. It costs roughly the book's own size in
input tokens and keeps no source text. The two are complementary — `book-to-kb`
for lookup and citation on every book, `book-to-skill` on top for the few whose
method you want to apply while working. Measured comparison:
`docs/book-kb-vs-book-to-skill.md`.
