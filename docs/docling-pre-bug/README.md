# docling HTML backend: `<pre>` loses preformatted semantics with inline children

Reported upstream as [docling#4549](https://github.com/docling-project/docling/issues/4549).

Found 2026-10-03 while extracting `docs/books/learning-cfengine.epub` for the
book KB. docling **2.133.0**, Python 3.12.15, macOS 27.0 arm64.

`<pre>` is whitespace-preserving. docling honours that when the `<pre>` contains
only a text node, and breaks it two different ways when it contains inline
elements.

Reproduce: `docling convert --to md --output . <file>.html`

| file | input shape | result |
| --- | --- | --- |
| `a-text-only.html` | `<pre><code>text</code></pre>` | ✅ correct fenced block |
| `b-span-children.html` | `<pre><code><span>…</span>\n…</code></pre>` | ✅ correct |
| `c-sibling-codes.html` | `<pre><code>a</code>\n<code>b</code></pre>` | ❌ **block structure destroyed** — emitted as inline code fragments: `` `line one` `` `` `line two` `` |
| `d-mixed-text-and-spans.html` | `<pre>` with a bare text node next to a `<span>` | ❌ **newline collapsed to a space** between the text node and the following element |
| `e-wrapped-mixed.html` | same as d, inside one `<code>` | ❌ identical to d — the wrapper makes no difference |

## Why it matters

Case **C** is the markup O'Reilly's Learning CFEngine EPUB ships: Pygments token
classes with every `<span>` rewritten to `<code>`, giving up to 207 sibling
`<code>` elements inside one `<pre>`. Every code listing in the book arrives as a
line of backtick fragments with spaces injected inside string literals
(`" s1 "` for `"s1"`) — 12 recovered code blocks across a 500-page book instead
of 210.

Case **D/E** is why a *spec-correct* repair of that EPUB is still not enough:
rewriting the `<code>` tokens back to `<span>` fixes C, but any listing with a
bare text run beside a highlighted token still loses that line break.

## Prior art checked (none covers this)

- #222 → PR #302 (2024) added `<pre>` handling.
- #1302 (2025) fixed text extraction inside `<code>`.
- #3608 (2026) was whitespace inside `<p>`, the opposite direction.

## What we do instead

`bin/book-kb` flattens every `<pre>` to a single plain-text `<code>` before
docling sees it, which reduces the input to case A. That is a workaround, not a
fix: it discards the syntax-highlighting classes. For a publisher the correct
repair is one `<code>` wrapper with `<span class="…">` tokens — Pygments'
own `HtmlFormatter` output — which is what case B shows docling handles.
