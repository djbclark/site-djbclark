# Draft note to the Learning CFEngine publisher/author — EPUB code markup

Written 2026-10-03, **not sent**. Kept because the clipboard and `/tmp` are both
ephemeral and this took measurement to produce.

Evidence behind every number is in
[`docs/docling-pre-bug/`](../docling-pre-bug/) and
[`docs/book-kb-vs-book-to-skill.md`](../book-kb-vs-book-to-skill.md). The claim
that Pygments emits `<span>` natively is from its own HtmlFormatter docs; the
"single `<code>` wrapper" pattern is MDN's.

Deliberately excluded from the note: docling#4549. That is our converter's
defect, not theirs, and mixing it in would muddy an actionable request.

Copy it with `bin/clip --unwrap docs/correspondence/learning-cfengine-epub-markup.md`
after stripping this header — or keep the body below in sync if it is edited.

---

Subject: Learning CFEngine EPUB — code listings lose their line structure in converters

Hi —

Small markup issue in the Learning CFEngine EPUB (2nd ed.) that affects code listings. Inside each <pre>, every syntax-highlighted token is wrapped in its own <code> element rather than a <span>: the file has 10,486 <code> elements against 17 <span>, up to 207 of them inside a single <pre>, across 270 listings.

The effect is that anything consuming the HTML semantically treats each <code> as a separate inline code fragment, so a listing loses its block structure and spaces get introduced at the element boundaries. A string literal written "s1" comes out as " s1 ", which quietly changes what the code means. It also degrades copy-paste and screen-reader output. Converting the EPUB to Markdown, I recovered 12 code blocks from the whole book; after correcting the markup, 210.

The fix is one element name: per listing, a single <pre><code> wrapping the whole block, with the highlight tokens as <span class="k">, <span class="s"> and so on instead of <code class="...">. The stylesheet needs no change — those class names are already what it targets. The classes are Pygments', and Pygments emits <span> natively, so the substitution looks like it happens somewhere after highlighting rather than in the highlighter itself.

Happy to send a five-file minimal reproduction if that's useful. Thanks for the book — it's the reference I reach for.
