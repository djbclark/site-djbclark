#!/usr/bin/env python3
"""Mechanical checks for a `research` run folder. Standard library only.

    research_check.py fetch  <source_id> <url> <run> [--via-proxy]
                                                       save sources/<source_id>.txt; with RESEARCH_PROXY_URL set
                                                       (EZproxy-style prefix) a paywalled page is retried via the proxy;
                                                       prints the HTTP status and final URL of every hop
    research_check.py quotes <run> [--no-update]        every quote occurs in its saved source
    research_check.py numbers <run>                     every number in report.md occurs in some quote
    research_check.py refs   <run>                      DOI / arXiv / PMID resolve; titles match
    research_check.py gate   <run> [--min-rows N] [--min-families M]
                                                       excerpt rows (kind "excerpt", or a source whose header says
                                                       "search-result excerpt") are leads and do not count
    research_check.py claims <run>                      every [E####] in report.md exists; ids unique; cited excerpt rows noted
    research_check.py all    <run> [--offline]          quotes, numbers, claims, gate, refs

<run> is the run folder (research/<slug>). Exit 0 when every check passes,
1 when a check fails, 2 on usage or I/O errors. `numbers` is an existence
check: it proves a figure was quoted somewhere, not that it is right.
"""
from __future__ import annotations

import html
import http.cookiejar
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, NoReturn

USER_AGENT = "research-skill-check/1.0 (+https://github.com/djbclark/site-djbclark)"
ID_RE = re.compile(r"\[(E\d{4,})\]")
NUM_RE = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?%?")
MIN_ROWS_DEFAULT = 6
MIN_FAMILIES_DEFAULT = 2


# ---------- helpers ----------

def die(msg: str, code: int = 2) -> NoReturn:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def polite_email() -> str | None:
    for var in ("PAPER_SEARCH_MCP_UNPAYWALL_EMAIL", "UNPAYWALL_EMAIL", "RESEARCH_CONTACT_EMAIL"):
        v = os.environ.get(var)
        if v:
            return v.strip()
    return None


def load_evidence(run: Path) -> list[dict[str, Any]]:
    path = run / "evidence.jsonl"
    if not path.is_file():
        die(f"{path} not found")
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                die(f"{path}:{n}: bad JSON ({exc})")
            if not isinstance(row, dict) or "id" not in row:
                die(f"{path}:{n}: row is not an object with an id")
            row["_line"] = n
            rows.append(row)
    return rows


def save_evidence(run: Path, rows: list[dict[str, Any]]) -> None:
    path = run / "evidence.jsonl"
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for row in rows:
            clean = {k: v for k, v in row.items() if not k.startswith("_")}
            fh.write(json.dumps(clean, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def normalise(text: str) -> str:
    """Case-fold, unify quotes/dashes/ligatures, drop soft hyphens, collapse whitespace."""
    text = unicodedata.normalize("NFKC", text)
    table = {
        "‘": "'", "’": "'", "“": '"', "”": '"',
        "–": "-", "—": "-", "−": "-", " ": " ",
        "­": "", "…": "...",
    }
    text = text.translate({ord(k): v for k, v in table.items()})
    text = text.casefold()
    return re.sub(r"\s+", " ", text).strip()


def normalise_source(text: str) -> tuple[str, str]:
    """Return (plain, dehyphenated) normalised forms of a source text."""
    plain = normalise(text)
    dehyph = normalise(re.sub(r"-\s*\n\s*", "", text))
    return plain, dehyph


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "td", "th", "pre", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(raw: str) -> str:
    p = _TextExtractor()
    p.feed(raw)
    text = html.unescape("".join(p.parts))
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


_COOKIES = http.cookiejar.CookieJar()
_OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_COOKIES))


def http_get(url: str, accept: str = "*/*", timeout: int = 60) -> tuple[bytes, str, int, str]:
    """GET with a process-wide cookie jar (an institutional proxy sets a session
    cookie on its login redirect and expects it on the next request). Returns
    body, content type, the final HTTP status and the final URL after redirects."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    with _OPENER.open(req, timeout=timeout) as resp:  # noqa: S310 (operator-supplied URL)
        ctype = resp.headers.get("Content-Type", "")
        return resp.read(), ctype, int(resp.status), str(resp.geturl())


def http_json(url: str) -> dict[str, Any] | None:
    try:
        body, _, _, _ = http_get(url, accept="application/json", timeout=30)
        return json.loads(body.decode("utf-8", "replace"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError, OSError):
        return None


def title_tokens(title: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", normalise(title)) if len(t) > 2}


def titles_match(a: str, b: str) -> bool:
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return False
    overlap = len(ta & tb) / min(len(ta), len(tb))
    return overlap >= 0.7


# ---------- fetch ----------

PAYWALL_RE = re.compile(r"buy (this )?article|purchase (pdf|access)|access through your institution|get access|rent this article", re.I)
ACCEPT = "text/html,application/pdf,text/plain;q=0.9,*/*;q=0.5"


def fetch_via_proxy(url: str) -> tuple[bytes, str, int, str]:
    """Fetch through an EZproxy-style prefix (RESEARCH_PROXY_URL). The first request
    takes the login redirect and collects the session cookie; the second one, with
    the cookie, is redirected straight to the proxied content. Every hop's HTTP
    status and final URL is printed (a worker could not tell a proxied 200 from a
    hand-off page before 2026-10-09)."""
    prefix = os.environ["RESEARCH_PROXY_URL"]
    body, ctype, status, final = http_get(prefix + url, accept=ACCEPT)
    print(f"proxy hop: HTTP {status} {final[:140]}", file=sys.stderr)
    for _ in range(2):
        if "pdf" in ctype.lower() or body[:5] == b"%PDF-" or len(body) > 20000:
            break
        # A small HTML hand-off page: EZproxy's /connect sets the session cookie and
        # sends the browser on with a JS `location = '<proxied url>'` or a meta refresh.
        head = body[:4000].decode("utf-8", "replace")
        m = (re.search(r"""location(?:\.href)?\s*=\s*["']([^"']+)["']""", head, re.I)
             or re.search(r"""http-equiv=["']?refresh["']?[^>]*url=([^"'>]+)""", head, re.I))
        if not m:
            break
        body, ctype, status, final = http_get(html.unescape(m.group(1)), accept=ACCEPT)
        print(f"proxy hop: HTTP {status} {final[:140]}", file=sys.stderr)
    return body, ctype, status, final


def looks_paywalled(body: bytes, ctype: str, url: str) -> bool:
    if "pdf" in ctype.lower() or body[:5] == b"%PDF-":
        return False
    text = body.decode("utf-8", "replace")
    if url.lower().endswith(".pdf"):
        return True
    return bool(PAYWALL_RE.search(text)) or len(html_to_text(text).split()) < 200


def cmd_fetch(source_id: str, url: str, run: Path, via_proxy: bool = False) -> int:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", source_id):
        die("source_id must be [A-Za-z0-9_.-]+")
    out_dir = run / "sources"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{source_id}.txt"
    proxied = False
    try:
        if via_proxy and os.environ.get("RESEARCH_PROXY_URL"):
            body, ctype, status, final = fetch_via_proxy(url)
            proxied = True
        else:
            body, ctype, status, final = http_get(url, accept=ACCEPT)
            print(f"direct: HTTP {status} {final[:140]}", file=sys.stderr)
            if os.environ.get("RESEARCH_PROXY_URL") and looks_paywalled(body, ctype, url):
                print("direct fetch looks paywalled or empty; retrying through RESEARCH_PROXY_URL", file=sys.stderr)
                body, ctype, status, final = fetch_via_proxy(url)
                proxied = True
    except urllib.error.HTTPError as exc:
        die(f"fetch failed: HTTP {exc.code} {exc.reason} for {exc.url}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        die(f"fetch failed: {exc}")
    is_pdf = body[:5] == b"%PDF-" or ("pdf" in ctype.lower() and b"<html" not in body[:2000].lower())
    if is_pdf:
        tool = shutil.which("pdftotext")
        if not tool:
            die("PDF source but pdftotext is not on PATH; save the text by another route")
        with tempfile.TemporaryDirectory() as td:
            pdf = Path(td) / "in.pdf"
            pdf.write_bytes(body)
            txt = Path(td) / "out.txt"
            proc = subprocess.run([tool, "-layout", "-enc", "UTF-8", str(pdf), str(txt)],
                                  capture_output=True, text=True)
            if proc.returncode != 0:
                die(f"pdftotext failed: {proc.stderr.strip()}")
            text = txt.read_text(encoding="utf-8", errors="replace")
    else:
        raw = body.decode("utf-8", "replace")
        text = html_to_text(raw) if "<" in raw[:2000] and "html" in ctype.lower() or raw.lstrip().lower().startswith(("<!doctype", "<html")) else raw
    header = (f"# source_id: {source_id}\n# url: {url}\n# content_type: {ctype}\n# http_status: {status}\n"
              f"# final_url: {final}\n# via_proxy: {'true' if proxied else 'false'}\n\n")
    out.write_text(header + text, encoding="utf-8")
    words = len(text.split())
    print(f"saved {out} (HTTP {status}, {words} words, {'pdf' if is_pdf else 'text'}"
          f"{', via proxy: tag the evidence row via-proxy' if proxied else ''})")
    if words < 50:
        print("warning: very little text extracted; the page may need a browser or a PDF route", file=sys.stderr)
    return 0


# ---------- quotes ----------

def cmd_quotes(run: Path, update: bool = True) -> int:
    rows = load_evidence(run)
    cache: dict[str, tuple[str, str] | None] = {}
    ok = missing = unverifiable = 0
    for row in rows:
        sid = str(row.get("source_id", ""))
        quote = str(row.get("quote", "")).strip()
        if sid not in cache:
            path = run / "sources" / f"{sid}.txt"
            cache[sid] = normalise_source(path.read_text(encoding="utf-8", errors="replace")) if path.is_file() else None
        src = cache[sid]
        if not quote:
            missing += 1
            print(f"MISSING  {row['id']}: empty quote")
            row["verified_quote"] = False
            continue
        if src is None:
            unverifiable += 1
            print(f"UNVERIFIABLE {row['id']}: no sources/{sid}.txt")
            row["verified_quote"] = False
            continue
        q = normalise(quote)
        q_dehyph = normalise(re.sub(r"-\s*\n\s*", "", quote))
        found = q in src[0] or q in src[1] or q_dehyph in src[0] or q_dehyph in src[1]
        row["verified_quote"] = bool(found)
        if found:
            ok += 1
        else:
            missing += 1
            print(f"MISSING  {row['id']} in sources/{sid}.txt: {quote[:80]!r}")
    if update:
        save_evidence(run, rows)
    print(f"quotes: {ok} verified, {missing} missing, {unverifiable} unverifiable (of {len(rows)})")
    return 0 if missing == 0 and unverifiable == 0 else 1


# ---------- numbers ----------

def report_body_lines(report: str) -> list[str]:
    """Lines of the report that carry prose: drop code fences, table rows, headers, list markers."""
    lines: list[str] = []
    in_fence = False
    for line in report.splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or s.startswith("|") or s.startswith("#"):
            continue
        s = re.sub(r"^\s*(\d+[.)]|[-*+])\s+", "", s)  # list markers
        s = ID_RE.sub("", s)
        lines.append(s)
    return lines


def cmd_numbers(run: Path) -> int:
    report_path = run / "report.md"
    if not report_path.is_file():
        die(f"{report_path} not found")
    rows = load_evidence(run)
    quoted = " ".join(normalise(str(r.get("quote", ""))) for r in rows)
    quoted_nums = {n.replace(",", "").rstrip("%").lstrip("+") for n in NUM_RE.findall(quoted)}
    unmatched: dict[str, str] = {}
    for line in report_body_lines(report_path.read_text(encoding="utf-8")):
        for tok in NUM_RE.findall(line):
            key = tok.replace(",", "").rstrip("%").lstrip("+")
            if key.lstrip("-") == "" or key in quoted_nums:
                continue
            unmatched.setdefault(key, line.strip()[:100])
    for key, ctx in sorted(unmatched.items()):
        print(f"UNQUOTED {key}: {ctx}")
    print(f"numbers: {len(unmatched)} figures in report.md have no quote containing them "
          f"(existence check only; a match proves a figure was quoted, not that it is right)")
    return 0 if not unmatched else 1


# ---------- refs ----------

def resolve_doi(doi: str) -> tuple[bool, str]:
    """Crossref first, then DataCite (arXiv, Zenodo, datasets), then the bare handle for existence."""
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", doi.strip(), flags=re.I)
    email = polite_email()
    q = f"?mailto={urllib.parse.quote(email)}" if email else ""
    data = http_json(f"https://api.crossref.org/works/{urllib.parse.quote(doi)}{q}")
    if data and data.get("status") == "ok":
        title = (data.get("message", {}).get("title") or [""])[0]
        return True, title
    data = http_json(f"https://api.datacite.org/dois/{urllib.parse.quote(doi)}")
    if data and isinstance(data.get("data"), dict):
        titles = data["data"].get("attributes", {}).get("titles") or [{}]
        return True, str(titles[0].get("title", ""))
    data = http_json(f"https://doi.org/api/handles/{urllib.parse.quote(doi)}")
    if data and data.get("responseCode") == 1:
        return True, ""
    return False, ""


def resolve_arxiv(aid: str) -> tuple[bool, str]:
    aid = re.sub(r"^arxiv:", "", aid, flags=re.I)
    try:
        body, _, _, _ = http_get(f"https://export.arxiv.org/api/query?id_list={urllib.parse.quote(aid)}", accept="application/atom+xml", timeout=30)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return False, ""
    text = body.decode("utf-8", "replace")
    m = re.search(r"<entry>.*?<title>(.*?)</title>", text, re.S)
    if not m or "<id>http://arxiv.org/api/errors" in text:
        return False, ""
    title = html.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
    if title.lower().startswith("error"):
        return False, ""
    return True, title


def resolve_pmid(pmid: str) -> tuple[bool, str]:
    email = polite_email()
    q = f"&email={urllib.parse.quote(email)}" if email else ""
    data = http_json(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id={urllib.parse.quote(pmid)}&retmode=json{q}")
    if not data:
        return False, ""
    rec = data.get("result", {}).get(pmid)
    if not rec or "error" in rec:
        return False, ""
    return True, rec.get("title", "")


def cmd_refs(run: Path) -> int:
    rows = load_evidence(run)
    seen: dict[tuple[str, str], tuple[bool, str]] = {}
    failures = 0
    checked = 0
    for row in rows:
        ids = row.get("ids") or {}
        if not isinstance(ids, dict):
            print(f"BAD-IDS  {row['id']}: ids is not an object")
            failures += 1
            continue
        pairs = [(k, str(v).strip()) for k, v in ids.items() if v]
        if not pairs:
            continue
        for kind, value in pairs:
            if kind not in ("doi", "arxiv", "pmid"):
                continue
            key = (kind, value)
            if key not in seen:
                fn = {"doi": resolve_doi, "arxiv": resolve_arxiv, "pmid": resolve_pmid}[kind]
                seen[key] = fn(value)
                checked += 1
            resolved, title = seen[key]
            if not resolved:
                failures += 1
                print(f"UNRESOLVED {row['id']}: {kind}={value}")
                continue
            claimed = str(row.get("title") or "")
            if claimed and title and not titles_match(claimed, title):
                failures += 1
                print(f"TITLE-MISMATCH {row['id']}: {kind}={value}\n    row:      {claimed[:90]}\n    resolved: {title[:90]}")
    print(f"refs: {checked} identifiers resolved, {failures} problems")
    return 0 if failures == 0 else 1


# ---------- excerpt rows ----------

EXCERPT_RE = re.compile(r"excerpt|snippet|search[- ]result", re.I)


def is_excerpt(run: Path, row: dict[str, Any], cache: dict[str, bool]) -> bool:
    """A row whose source is a search-result excerpt (kind "excerpt", or a saved
    source whose `# content_type:` header says so) is a lead, not evidence. Seen
    2026-10-09: five refuter rows were excerpts and counted toward the gate."""
    if str(row.get("kind", "")).strip().casefold() == "excerpt":
        return True
    sid = str(row.get("source_id", ""))
    if sid not in cache:
        path = run / "sources" / f"{sid}.txt"
        head = path.read_text(encoding="utf-8", errors="replace")[:800] if path.is_file() else ""
        m = re.search(r"^# content_type:(.*)$", head, re.M)
        cache[sid] = bool(m and EXCERPT_RE.search(m.group(1)))
    return cache[sid]


# ---------- gate ----------

def cmd_gate(run: Path, min_rows: int, min_families: int) -> int:
    all_rows = load_evidence(run)
    cache: dict[str, bool] = {}
    excerpts = [r for r in all_rows if is_excerpt(run, r, cache)]
    rows = [r for r in all_rows if not is_excerpt(run, r, cache)]
    families = {str(r.get("family", "")).strip().casefold() for r in rows if str(r.get("family", "")).strip()}
    verified = sum(1 for r in rows if r.get("verified_quote") is True)
    print(f"gate: {len(rows)} rows ({verified} with verified quotes), {len(families)} source families; "
          f"{len(excerpts)} excerpt rows excluded (leads, not evidence); "
          f"need >= {min_rows} rows from >= {min_families} families")
    if len(rows) < min_rows or len(families) < min_families:
        print("gate: THIN — broaden the search or report the gap; do not synthesise around it")
        return 1
    print("gate: ok")
    return 0


# ---------- claims ----------

def cmd_claims(run: Path) -> int:
    report_path = run / "report.md"
    if not report_path.is_file():
        die(f"{report_path} not found")
    rows = load_evidence(run)
    ids = [str(r["id"]) for r in rows]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    known = set(ids)
    cited = set(ID_RE.findall(report_path.read_text(encoding="utf-8")))
    missing = sorted(cited - known)
    uncited = sorted(known - cited)
    problems = 0
    for d in dupes:
        print(f"DUPLICATE-ID {d}")
        problems += 1
    for m in missing:
        print(f"UNKNOWN-ID {m}: cited in report.md but not in evidence.jsonl")
        problems += 1
    for u in uncited:
        print(f"note: {u} in evidence.jsonl is not cited (drop it from the evidence table)")
    cache: dict[str, bool] = {}
    excerpt_cited = sorted(str(r["id"]) for r in rows if str(r["id"]) in cited and is_excerpt(run, r, cache))
    for e in excerpt_cited:
        print(f"note: {e} is an excerpt row (search-result text, page not opened): cite it only as a lead")
    print(f"claims: {len(cited)} ids cited, {len(missing)} unknown, {len(dupes)} duplicate, {len(uncited)} uncited, "
          f"{len(excerpt_cited)} excerpt rows cited")
    return 0 if problems == 0 else 1


# ---------- main ----------

def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 2
    sub = argv[1]
    args = argv[2:]
    flags = {a for a in args if a.startswith("--")}
    pos = [a for a in args if not a.startswith("--")]

    def opt(name: str, default: int) -> int:
        for a in args:
            if a.startswith(f"{name}="):
                return int(a.split("=", 1)[1])
        return default

    if sub == "fetch":
        if len(pos) != 3:
            die("usage: fetch <source_id> <url> <run> [--via-proxy]")
        return cmd_fetch(pos[0], pos[1], Path(pos[2]), via_proxy="--via-proxy" in flags)
    if len(pos) != 1:
        die(f"usage: {sub} <run>")
    run = Path(pos[0])
    if not run.is_dir():
        die(f"{run} is not a directory")
    if sub == "quotes":
        return cmd_quotes(run, update="--no-update" not in flags)
    if sub == "numbers":
        return cmd_numbers(run)
    if sub == "refs":
        return cmd_refs(run)
    if sub == "gate":
        return cmd_gate(run, opt("--min-rows", MIN_ROWS_DEFAULT), opt("--min-families", MIN_FAMILIES_DEFAULT))
    if sub == "claims":
        return cmd_claims(run)
    if sub == "all":
        results = {
            "quotes": cmd_quotes(run),
            "numbers": cmd_numbers(run),
            "claims": cmd_claims(run),
            "gate": cmd_gate(run, opt("--min-rows", MIN_ROWS_DEFAULT), opt("--min-families", MIN_FAMILIES_DEFAULT)),
        }
        if "--offline" not in flags:
            results["refs"] = cmd_refs(run)
        failed = [k for k, v in results.items() if v]
        print("all: " + ("ok" if not failed else "FAILED " + ", ".join(failed)))
        return 1 if failed else 0
    die(f"unknown subcommand {sub!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
