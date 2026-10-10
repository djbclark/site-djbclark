"""Turn footnote-style citations into numbered superscript links.

Run after reformat_citations.py (which produced `[^E0927]` markers and a
`## Citation footnotes` section of `[^E0927]: ...` definitions).

MultiMarkdown (Marked 2's renderer) cannot cite the same footnote twice and
parses `[^A][^B]` as a reference link, so Markdown footnotes do not work for a
report that cites 575 rows many times each. This script instead writes, in the
body (everything before `## Evidence table`):

    <sup>[12](#E0927) [13](#E0931)</sup>

one `<sup>` per run of adjacent citations, numbers assigned by first appearance,
space-separated, no commas; and rewrites the footnote section as a numbered
list, one item per cited id in citation-number order:

    12. <a id="E0927"></a>E0927 — <claim> — <source>, <locator>. <url>

Idempotent: a file with no `[^E####]` markers is left unchanged. Stdlib only.
"""
import re
import sys

MARK = re.compile(r"\[\^(E\d{4,})\]")
RUN = re.compile(r"\[\^E\d{4,}\](?:\s*,?\s*\[\^E\d{4,}\])*")
DEF = re.compile(r"^\[\^(E\d{4,})\]: (.*)$")
TABLE_RE = re.compile(r"^## (?:\d+\.\s*)?Evidence table\n", re.M)  # optional section number
FOOT = "## Citation footnotes\n"


def main() -> int:
    path = sys.argv[1]
    text = open(path, encoding="utf-8").read()
    hm = TABLE_RE.search(text)
    if not hm:
        print("ERROR: no '## [N.] Evidence table' heading")
        return 1
    TABLE = hm.group(0)
    body, rest = text.split(TABLE, 1)
    if not MARK.search(body):
        print("no [^E####] markers in body; nothing to do")
        return 0
    table, foot = rest.split(FOOT, 1)

    defs = {}
    for line in foot.splitlines():
        m = DEF.match(line)
        if m:
            defs[m.group(1)] = m.group(2)

    number = {}

    def num(i):
        if i not in number:
            number[i] = len(number) + 1
        return number[i]

    def sub_run(m):
        ids = MARK.findall(m.group(0))
        return "<sup>" + " ".join(f"[{num(i)}](#{i})" for i in ids) + "</sup>"

    new_body = RUN.sub(sub_run, body)
    missing = [i for i in number if i not in defs]
    if missing:
        print(f"ERROR: {len(missing)} cited ids have no footnote definition: {missing[:10]}")
        return 1
    items = [f'{n}. <a id="{i}"></a>{i} — {defs[i]}' for i, n in sorted(number.items(), key=lambda kv: kv[1])]
    new_foot = "\n".join(items) + "\n"
    open(path, "w", encoding="utf-8").write(new_body + TABLE + table + FOOT + "\n" + new_foot)
    print(f"citations numbered: {len(number)}; sup runs written: {len(RUN.findall(body))}; definitions unused: {len(set(defs) - set(number))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
