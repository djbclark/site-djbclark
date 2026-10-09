# Scientific literature playbook

Applies when the question is scientific, medical, or technical enough that
the answer lives in papers, standards or datasets rather than on the open
web. Everything in `worker.md` still holds; this adds where to search, how
to identify, and how to grade.

## Search strategy

1. **Decompose** the question into 3-5 concepts; write a synonym set per
   concept (field terms, abbreviations, older names). Record every query
   verbatim with source, date and hit count in the search log.
2. **Reviews first.** Recent reviews, systematic reviews and meta-analyses
   give the vocabulary, the landmark papers and a ready reference list.
3. **Two indexes minimum** per concept set: OpenAlex or Semantic Scholar for
   breadth; PubMed or Europe PMC for biomedicine; arXiv for CS, physics,
   maths; Crossref for anything with a DOI. Union the hits, then dedupe by
   DOI, then arXiv id, then normalised title.
4. **Chase citations both ways** for the 3-5 most central papers: their
   reference lists (backward) and the papers citing them (forward, the only
   way to find work newer than the reviews). One more hop only for papers
   cited by two or more seeds.
5. **Rank** by relevance to the question and by influential-citation or
   recommendation signals, not raw citation counts, which favour old work.
6. **Date filters last.** Search wide, then narrow to the last 3-5 years for
   the state of the art; keep foundational older papers found by chasing.
7. **Triage cheaply, read properly.** Title, abstract and TLDR to select;
   full text (results, discussion, limitations) for the top ~10. Abstracts
   overstate claim strength; a number quoted from an abstract is tagged
   `abstract-only`.
8. **Stop** when a full chase round (backward plus forward on the new seeds)
   adds no relevant paper above the relevance bar, and say so in the notes
   along with what was not searched.

## Identifiers and status

1. Resolve every cited item to a DOI, arXiv id or PMID before it enters
   `evidence.jsonl`; `research_check.py refs` verifies the id resolves and
   the title matches. An item that will not resolve is listed as unresolved,
   never cited as fact.
2. Label every arXiv, bioRxiv, medRxiv, SSRN item `preprint`. Check for a
   published version (OpenAlex, Semantic Scholar and Crossref link them) and
   cite the published one.
3. Check retractions and corrections (Crossref `update-to`, PubMed
   "Retracted publication" tags, publisher notices) for every central paper.
4. Never compare citation counts across tools; name the tool with any count.
5. A model-generated citation is unverified until it resolves.

## Evidence grading (recorded per row in `locator` or the notes)

| dimension | record |
|---|---|
| study type | RCT, cohort, case-control, in vitro, animal, simulation, benchmark, survey, review, meta-analysis, opinion |
| size | n, number of studies, dataset size |
| status | peer-reviewed, preprint, retracted, corrected |
| provenance | the paper's own result, or its citation of someone else's (cite the original when it is the latter) |
| conflicts | funding and declared interests when stated |

A quote from a paper's own results section outranks the same number quoted
from its introduction citing another paper.

## Tools (use what the host has; the REST calls need only curl)

1. **`paper-search` CLI** (from `paper-search-mcp`; also an MCP server):
   `paper-search sources`; `paper-search search "<query>" -s openalex,semantic,pubmed -n 10 [-y 2020-2026]`;
   `paper-search read <id-or-url>` extracts text (save it as the source
   file). Covers arXiv, PubMed/PMC/Europe PMC, bioRxiv/medRxiv, Semantic
   Scholar, Crossref, OpenAlex, CORE, Unpaywall and more. Set
   `PAPER_SEARCH_MCP_UNPAYWALL_EMAIL` for the Unpaywall full-text fallback.
   Never pass `use_scihub=true` or any Sci-Hub option. Install with
   `uv tool install --with 'mcp<2' paper-search-mcp` (the server imports the
   1.x FastMCP API and fails under mcp 2.x).
2. **arXiv MCP server** (`arxiv-mcp-server`): section-level HTML/LaTeX reads
   keep context small; BibTeX export.
3. **Keyless REST** (polite pool: add `mailto=`/`email=` from the
   `PAPER_SEARCH_MCP_UNPAYWALL_EMAIL` env var when set, never hard-code):
   `https://api.openalex.org/works?search=…`,
   `https://api.openalex.org/works?filter=cites:W…` (forward),
   `https://api.crossref.org/works/<doi>`,
   `https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=…&format=json`,
   `https://export.arxiv.org/api/query?id_list=…`.
4. **Whole papers**: `pdftotext` into `sources/<id>.txt` (the `fetch`
   subcommand does this for a PDF URL when `pdftotext` is on PATH). For a
   long paper you will query repeatedly, a book-KB style ingest and
   regex query beats pasting the PDF into context.
5. **Host research tools** (for example a research-paper search in the host's
   web connector) are fine for triage; the evidence row still needs the
   opened text.
6. **Institutional access.** If `RESEARCH_PROXY_URL` is set (an EZproxy-style
   prefix such as `https://proxy.example.edu/login?url=`), the `fetch`
   subcommand retries a page that looks paywalled through the proxy
   (`--via-proxy` forces it), keeping the proxy's session cookie across its
   redirect chain, and writes `via_proxy: true` into the saved header; tag
   the evidence row `via-proxy`. Use it only after the open-access ladder
   (Unpaywall, PMC, arXiv, publisher OA) fails. Never store credentials in the run folder; never put
   institution-specific recipes in this public file. Two cautions: a VPN
   that egresses through a cloud gateway may not present the institution's
   address to publishers, so confirm with an "Access provided by …" banner
   in a browser before relying on it; and an EZproxy login needs a
   browser session with the institution's cookie, so proxied reads go
   through a browser tool, not `fetch`. Library licences usually forbid
   bulk downloading, so read per paper and quote-sized.

## Reporting extras for literature work

1. The search log in `plan.md` is complete enough to rerun: database, exact
   query, filters, date, hit count.
2. The evidence table adds study type, n and status columns.
3. "What was not established" names the databases not searched, the
   paywalled items not read, and the languages not covered.
