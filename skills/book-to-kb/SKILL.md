---
name: book-to-kb
description: >-
  Add a book or long document (EPUB, PDF, DOCX, HTML, Markdown, TXT, RTF) to the
  local token-efficient knowledge base at ~/kb, so it can be queried from any
  agent session without loading it into context: docling extraction, chapter
  split, a ~2.5k-token index, and basic-memory semantic search. Use when the
  operator gives one or more book paths, says "add this book", "index this
  PDF/EPUB", "put this in the KB", or asks how to query a book already in it.
  Not for turning a book into an agent skill with frameworks and voice — that is
  book-to-skill, which is complementary.
---

# book-to-kb

Turn a document into a queryable corpus, not a context-window problem. The
pipeline is mechanical and costs **no model tokens**: docling → clean Markdown →
chapters → a chapter index. Your job is the judgment around it — picking the
source format, naming the slug, and **verifying the extraction actually worked**
before telling the operator it did.

Implementation: `~/ops/site-private/bin/book-kb` (recipes: `just book-*` in
`site-private`). Never reimplement it; call it.

## Step 1 — Resolve inputs

Expand the paths given. Directories and globs are fine. Supported: `.pdf`,
`.epub`, `.docx`, `.pptx`, `.xlsx`, `.html`, `.md`, `.txt`, `.csv`, `.rtf`,
`.odt`, `.tex`, `.xml`.

**MOBI/AZW/AZW3 are not supported** — docling cannot read them and Calibre is not
installed. Say so and ask whether to install Calibre or get another format.

Check the toolchain once: `book-kb doctor`. If the venv is missing, run
`just book-setup` from `~/ops/site-private` (~1.2 GB, one time).

## Step 2 — Pick ONE source per book

If a book is present in more than one format, **extract the EPUB, not the PDF**,
and say why in one line. Measured on Learning CFEngine (same book, both formats):

| | EPUB | PDF |
| --- | --- | --- |
| code listings | correct, indented, multi-line | **collapsed onto one line** |
| inline code markup | preserved | lost |
| real tables | 37 | 35 |
| extraction time | 17 s | 188 s (247 pages) |

The PDF's fence *count* was higher (594 vs 420) and that is a trap — the code
inside those fences had lost its line structure. Never judge extraction quality
by fence count alone.

Use the PDF only when there is no EPUB, or when the EPUB extraction fails Step 4.

## Step 3 — Extract

```bash
cd ~/ops/site-private
./bin/book-kb extract <path>            # slug derived from the filename
./bin/book-kb extract <path> --slug <s> # when the filename is unhelpful
```

The slug is the handle the operator and every other agent will type. Derive it
from the book's real title, lowercase-kebab, no edition or year — `learning-cfengine`,
not `learning_cfengine_2nd_edition_final`.

Idempotent: re-running on an unchanged file is a no-op (sha256). Add `--force`
after a pipeline change. For a first look at a very long PDF, `--pages 1-40`
keeps it cheap.

**On a huge PDF, run it in the background** (`run_in_background: true`) — roughly
0.8 s/page, and the first PDF ever converted also downloads layout models.

## Step 4 — Verify, before claiming success

This is the step that matters. Extraction can "succeed" and produce unusable
output. Check all four:

```bash
slug=<slug>; d=~/kb/md/$slug
python3 -c "import json;m=json.load(open('$d/meta.json'));print(m['title'],'|',m['chapters'],'chapters |',m['tokens'],'tokens')"
echo "fences: $(cat $d/chapters/*.md | grep -c '^\`\`\`')"
for f in $d/chapters/*.md; do echo $(( $(wc -c < "$f") / 4 )); done | sort -n \
  | awk '{a[NR]=$1} END{print "tokens/chapter: p50="a[int(NR*0.5)], "max="a[NR]}'
```

1. **Title** is the book's title — not "Table of Contents", "License" or the
   filename. `book-kb` reads EPUB `dc:title` and PDF `Title` for this; if it
   still looks wrong, pass `--slug` and mention the metadata is poor.
2. **Code fences**, for anything technical. Near-zero on a programming book means
   the extraction failed, not that the book has no code. Then read one listing:
   it must be multi-line and indented, not one long line.
3. **Chapter sizes**: p50 should be ~1–2k tokens, max under ~8k. A single chapter
   holding most of the book means the heading split failed.
4. **Index cost**: `INDEX.md` should be 1–3k tokens. If it is over ~5k the book
   has too many top-level sections to be a useful map; say so.

If 2 fails on an EPUB, that is usually [docling#4549](https://github.com/docling-project/docling/issues/4549)
— `<pre>` losing its structure when it contains inline elements. `book-kb`
already flattens `<pre>` to work around it, so a failure here means a *new*
variant: capture it in `site-private/docs/docling-pre-bug/` and tell the operator
rather than shipping a corrupt corpus.

## Step 5 — Index for semantic search

```bash
./bin/book-kb index
```

Registers `~/kb/md` as basic-memory project `books` and reindexes. Must report a
non-zero note count. `bm project add` alone does **not** index, and the first run
is slow because it loads the fastembed model.

## Step 6 — Report, and offer a cross-reference

Give the operator: the slug, chapter count, index cost vs whole-book cost, and
the three query commands.

```
<slug>: N chapters, ~Xk tokens total. Index is ~Yk — a Z:1 reduction.
  exact    ~/ops/site-private/bin/book-kb query '<regex>' <slug>
  outline  ~/ops/site-private/bin/book-kb toc <slug>   (--deep for file:line anchors)
  semantic search_notes(project="books", query=...)
```

**If the book is authoritative for work done in a repo on this machine, offer to
add a pointer to that repo's `AGENTS.md`** (`CLAUDE.md` is a symlink to it) so future sessions query it
instead of guessing — the pattern already applied for CFEngine across
`home-agents.md`, `site-djbclark`, `stayturgid`, `ShizukuTendCF`, `tendcf`,
`nix2cf` and `cfengine-all`. Ask first; do not edit repos unprompted.

## Hard rules

1. **Never read `~/kb/raw/<slug>.md`.** That is the whole book. The index exists
   precisely so nothing has to.
2. **Semantic search is discovery, never proof.** It ranks by similarity and
   returns its closest N notes whether or not any match. To answer "does the book
   say X", use `book-kb query`.
3. **Keep the source file.** `book-kb` copies it into `~/kb/sources/`. `~/kb` is
   outside git on purpose — books are large and usually not ours to
   redistribute. Carbon Copy Cloner backs up `~` daily.
4. **Do not put book text in a git repo**, including `site-private/memory`. Only
   the path, slug and query commands belong there.

## Not this skill

`book-to-skill` distils a book into frameworks, principles and voice, costs about
the book's own size in input tokens, and keeps no source text. It is
complementary — use `book-to-kb` for lookup and citation on every book, and
`book-to-skill` on top for the few whose method you want to apply while working.
Measured comparison: `site-private/docs/book-kb-vs-book-to-skill.md`.
