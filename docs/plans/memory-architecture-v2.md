# Shared agent memory architecture v2

- **Status:** accepted architecture; phased implementation gated below
- **Issue:** [#139](https://github.com/djbclark/site-djbclark/issues/139)
- **Scope:** Hermes and Claude first; portable to other local agents
- **Date:** 2026-08-13

## 1. Decision summary

Build one governed memory system around four architectural primitives, not one product per memory level:

1. **SQLite evidence and operations** — lossless cross-client events, exact retrieval, queues, leases, provenance, redactions, and projection receipts.
2. **Link** — presumptive reviewed-memory and source-backed Markdown wiki layer, with SQLite FTS5 and optional local semantic retrieval as rebuildable indexes.
3. **Git-owned instructions and canon** — `AGENTS.md`, thin `CLAUDE.md` bridges, decisions, policies, and reviewed Link memories under `site-private/memory/link/`.
4. **Bounded bootstrap projections** — small, validated context packets for Hermes and Claude rather than treating their always-injected memory files as the durable store.

Keep **Hindsight** active during a measured shadow comparison. Retire it only if Link proves equal or better for durable preference/fact recall, provenance, correction, latency, token cost, and availability. Keep **Graphiti** optional; add it only if Link plus explicit temporal metadata fails controlled temporal-relationship tests. Do not adopt **Basic Memory** alongside Link unless it demonstrates a unique capability. Do not adopt **MemPalace** unless SQLite exact/span/neighborhood retrieval fails its acceptance tests.

The intended authority model is:

```text
S1 Evidence (SQLite, not Git)
  exact events + attachments + provenance
        │
        ├── exact/FTS/trigram/neighborhood recall
        │
        └── normalized sources and candidate extraction
                         ↓
G Gate (SQLite workflow + Link capture/review UI)
  candidates, conflicts, approvals, rejections, provenance
                         ↓
S2 Canon (Git Markdown)            S3 Projections (rebuildable)
  AGENTS.md, policies, docs          Link indexes, Hindsight,
  reviewed Link wiki/memories        optional graph/vector views
             └──────────────┬──────────────┘
                            ↓
B Bootstrap projections
  bounded Hermes MEMORY/USER and Claude brief/cache
```

## 2. Non-negotiable requirements

- Preserve complete raw Hermes and Claude transcripts, tool calls/results, reasoning fields where available, and attachment references without injecting the entire archive into prompts.
- Hermes and Claude are first-class clients. Other MCP/CLI-capable agents should be supportable without copying canonical state into each runtime.
- A valid write is durably accepted before any LLM consolidation runs.
- LLMs may extract, merge, classify, and propose; they may not be required for exact preservation, operation identity, crash recovery, or rollback.
- Every promoted claim resolves to surviving evidence event IDs or a Git-canonical source. Empty provenance is a hard rejection.
- Human-owned instructions and high-impact policy never auto-promote.
- Canon, evidence, candidates, and projections remain distinct authority classes.
- Built-in bootstrap capacity must not silently reject or discard valid memory writes.
- The user must not need to memorize taxonomies, exact type names, positional syntax, or quoting conventions. Free-form input is primary; classification fields are inferred and remain editable.
- SQLite is preferred for local durable machine state, transactional workflows, evidence, and rebuildable indexes. Markdown/Git remains preferable for human-owned knowledge.
- All phases are reversible and independently measurable.

### 2.1 Threat model and trust boundaries

Adversaries and failures include untrusted web/tool/transcript content, a malicious or buggy extractor, a compromised third-party MCP server, mistaken batch approval, concurrent writers, process crash, sleep/wake, lock contention, disk pressure, and backup/restore failure.

- Deterministic ingestion assigns producer, source coordinates, account, origin, scope, sensitivity floor, timestamps, and evidence IDs. An LLM may not override those envelope fields.
- Raw content, extraction output, and retrieval results are untrusted data even when they come from a second model.
- Only human-origin, explicitly human-approved claims may enter the instruction class or automatic bootstrap projection.
- Claims supported by web/tool-origin evidence may become reviewed ordinary knowledge, but never instructions; they are excluded from low-attention batch approval.
- The bootstrap is a high-privilege surface. A deterministic validator enforces class, provenance, scope, sensitivity, protected entries, and size before atomic publication.
- Third-party components are commit-pinned. Updating Link or any MCP integration requires re-running the spike, security checks, and compatibility suite.
- Pre-ingest secret detection classifies and alerts; suspected secrets are encrypted/quarantined and excluded from semantic projections. Redaction is remediation, not a substitute for prevention.

## 3. Levels 0–6 coverage

| Level | Function | Implementation | Acceptance evidence |
|---:|---|---|---|
| **0** | Bounded bootstrap capacity and overflow safety | SQLite acceptance journal, projection receipts, bounded projection generator, explicit accepted/applied/injected states | Deliberately fill both Hermes stores; prove journal → validated projection → retry; no loss under crash, timeout, or model outage |
| **1** | Native/project instructions and always-loaded context | Git-canonical `AGENTS.md`; thin `CLAUDE.md` bridge/symlink; bounded Link/Hermes brief; canary verification | Both clients resolve and obey the same canary by reference; no copied divergent canon; unknown injection telemetry stays `unknown` |
| **2** | Structured file memory, hooks, maintenance | Link Markdown memories/wiki, capture inbox, review lifecycle, consolidation plans, session hooks/adapters | Free-form capture → proposal → approve/reject → archive/restore with provenance |
| **3** | Semantic working memory | Link SQLite FTS5 plus optional local embeddings/reranker; Hindsight shadow comparator | Same-corpus retrieval benchmark, paraphrase/abstention tests, latency and token accounting |
| **4** | Verbatim transcript/event recall | SQLite evidence store, FTS5 + trigram/exact search, event-neighbor expansion, attachment CAS references | Exact quote and rationale recovery across Hermes/Claude, including tool results and compacted Hermes messages |
| **5** | Interlinked knowledge base | Link source-backed Markdown wiki, entities/concepts/backlinks, explicit supersession; Git for operator-owned docs | Rebuild indexes from Markdown; cite raw/Git provenance; inspect and revert changes |
| **6** | Shared cross-tool memory | Link MCP/CLI plus native Hermes adapter and Claude connector; writes through the gate | Hermes and Claude retrieve the same approved memory and produce one auditable update path |

The levels are a completeness checklist, not seven databases.

## 4. Store and authority contracts

### 4.1 S1 — raw evidence and SQLite control plane

S1 is the only irreplaceable machine-readable store. It retains producer bytes before normalization, uses SQLite for identity and transactional state, and stores large attachments in a content-addressed object store (CAS).

Minimum control schema:

```sql
CREATE TABLE event (
  event_id            TEXT PRIMARY KEY,
  producer            TEXT NOT NULL CHECK (producer <> ''),
  producer_version    TEXT,
  account_id          TEXT NOT NULL,
  source_uri          TEXT NOT NULL,
  source_locator      TEXT NOT NULL,
  producer_session_id TEXT,
  source_seq          INTEGER,
  ingest_lsn          INTEGER NOT NULL UNIQUE,
  ts_utc              TEXT NOT NULL,
  ts_source           TEXT NOT NULL CHECK (ts_source IN ('producer','filesystem','ingest','inferred')),
  role                TEXT NOT NULL CHECK (role IN ('user','assistant','system','tool','unknown')),
  event_type          TEXT NOT NULL,
  tool_name           TEXT,
  tool_call_id        TEXT,
  raw_ref             TEXT NOT NULL,
  raw_sha256          TEXT NOT NULL,
  raw_size            INTEGER NOT NULL CHECK (raw_size >= 0),
  content_encoding    TEXT NOT NULL,
  origin              TEXT NOT NULL CHECK (origin IN ('human','model','tool','web','system','derived')),
  scope               TEXT NOT NULL,
  sensitivity         TEXT NOT NULL,
  redaction_state     TEXT NOT NULL DEFAULT 'none',
  ingest_batch        TEXT NOT NULL,
  UNIQUE(producer, source_uri, source_locator)
);

CREATE TABLE conversation_member (
  event_id        TEXT NOT NULL REFERENCES event(event_id),
  conversation_id TEXT NOT NULL,
  assigned_by     TEXT NOT NULL,
  confidence      REAL,
  assigned_at     TEXT NOT NULL,
  PRIMARY KEY (event_id, conversation_id)
);
```

`event_id` is deterministic from `producer | source_uri | source_locator | raw_sha256`. `source_locator` is producer-specific but stable within the immutable source (for example a JSONL byte range plus record index). Raw hashes cover exact pre-normalization bytes. Native session IDs and `source_seq` are evidence, not identity. Conversation grouping is revisable metadata; prefer a false split over an unsupported merge. Within one producer session, order by `source_seq`; across sources, order by `ts_utc`, producer/source coordinates, then `ingest_lsn` as a deterministic tie-break. Timestamps use RFC 3339 UTC with `Z`.

Related tables include:

- `raw_object` / `attachment` — CAS references, MIME/type/dimensions/duration, source event, hash, encryption/sensitivity, and extraction versions.
- `ingest_checkpoint` and `ingest_gap` — source fingerprint/cursor, adapter version, committed position, and explicit intervals whose evidence is missing.
- versioned normalized-event tables — rebuildable S3 projections over raw bytes, never the sole evidence.
- `candidate` / `candidate_evidence` — quarantined claims and exact evidence joins.
- `operation` — unique idempotency key, queue state, attempts, error, expected/result hashes, monotonic fencing counter when multiple workers are enabled, and projection receipt joins.
- `redaction` and projection-redaction receipts — audit record and cascade state.
- FTS5/trigram/vector tables — derived, disposable, and rebuildable.

SQLite requirements:

- `PRAGMA journal_mode=WAL`, `foreign_keys=ON`, schema migrations via `user_version`, and a bounded `busy_timeout`.
- Acceptance transactions use `synchronous=FULL`; `accepted` means `COMMIT` returned successfully.
- Start with one supervised writer process and short transactions. Do not add leases until multiple concurrent writers are required; if added, use monotonically allocated fencing counters and compare-and-swap at publication, never wall-clock timestamps as fences.
- Append-only triggers reject event deletion and unauthorized updates. Redaction may change only active payload references/state in the same transaction as an audit row; the immutable original hash remains.
- Add indexes for source identity, raw hash, timestamps, producer session/sequence, tool calls, scope, and neighborhood retrieval.

Retention, redaction, and backup:

- Never put raw evidence or transcript dumps in Git.
- Preserve exact producer bytes by default. Historical coverage before sink activation is best-effort; record gaps rather than claiming losslessness.
- Redaction is forward removal from active stores and projections, not erasure from historical backups. A live redaction completes only after every registered FTS/vector/Link/Hindsight/graph projection records a receipt and the literal is unfindable through active retrieval.
- Any promoted claim depending on redacted evidence becomes `evidence_withdrawn` and re-enters review.
- Produce consistent SQLite backup snapshots with the backup API or `VACUUM INTO`; Arq backs up stable snapshots and CAS objects rather than assuming a live WAL copy is valid. Restore runs `integrity_check`, `foreign_key_check`, sampled raw-hash verification, and a retrieval/rebuild drill.
- FileVault is the baseline at-rest control; sensitive CAS objects may add application encryption. Restore artifacts are production-sensitive.
- Export a versioned producer-neutral JSONL view without re-exposing redacted payloads.
- Estimate growth in Phase B; default to lossless retention and trigger an explicit storage-policy review at 50 GB rather than silently expiring evidence.

### 4.2 G — candidate and promotion gate

The gate combines SQLite transactional state with Link's capture/review interface. `/z` remains the natural Hermes command surface but should not maintain a competing authority store.

Candidate states:

```text
captured → proposed → quarantined → approved → promoted
                         ├── rejected
                         ├── expired
                         └── superseded
```

Every candidate requires:

- candidate and operation IDs;
- source event IDs or Git source URI and revision;
- client, agent, user, project, workspace, and scope;
- origin (`human`, `model`, `tool`, `web`, `derived`);
- extractor and policy version;
- confidence and sensitivity;
- temporal fields and supersession links where applicable;
- content hash and review history.

Hybrid governance:

| Class | Examples | Handling |
|---|---|---|
| Derived index data | chunks, embeddings, FTS rows, graph edges | Automatic, rebuildable, no per-item review |
| Low-risk grounded facts | current language/runtime from an exact source | Quarantine initially; later eligible for reversible auto-promotion only after measured precision and explicit policy approval |
| Interpretive/personal memory | preferences, intentions, relationships, lessons | Auto-propose; review in batches or when retrieved and materially useful |
| Instructions/high-impact claims | deployment policy, security, health, legal, financial, global behavior | Manual approval every time; never auto-promote |

An unapproved candidate may be shown only in a structurally separate **untrusted candidate** block with its evidence and may not affect an action. This model-dependent display path stays disabled until Phase E threat-model tests pass.

`/z approve` should become a façade over the gate and Link acceptance path. Rejection should suppress repetitive resurfacing while retaining the audit record.

### 4.3 S2 — human-owned canon

S2 contains material whose correctness and wording humans intentionally own:

- repository `AGENTS.md` files;
- thin `CLAUDE.md` bridges or symlinks;
- architecture decisions, policies, and plans;
- reviewed Link Markdown memories and wiki pages where Link is the chosen canon;
- source citations and stable links into S1.

Rules:

- Agents propose; humans review/merge high-impact Canon changes.
- Do not continuously copy `AGENTS.md`/`CLAUDE.md` into Hermes `MEMORY.md`.
- Link and repository documentation must not become two canons for the same document. Repository-owned policy stays in repository Git; Link stores a concise pointer/recall cue where useful.
- Indexes, backlinks, summaries, and embeddings are not canon.

The operator chose `site-private/memory/link/` as Link's canonical home from Phase C onward under the existing narrow memory-data exception. Only accepted, reviewed one-memory-per-file Markdown belongs there. Raw captures, candidate queues, operations, locks, caches, generated indexes, and whole-file summaries remain outside Git. The SQLite gate is the single canonical write coordinator: run `just ops-memory-sync` immediately before each write, reject/retry concurrent generations rather than overwrite, create a memory-only commit on `master`, push immediately, and verify a clean tree. Repository policy/docs remain in their owning repositories; Link stores pointers, not duplicate canon. Codex-owned consolidated summaries remain non-interference territory.

### 4.4 S3 — projections

S3 includes anything that can be deleted and rebuilt from S1 + S2 **after its unique incumbent contents have been exported and backfilled**:

- Link FTS5/page cache/semantic index;
- Hindsight during the comparison and, if retained, approved semantic memories with evidence pointers;
- optional Graphiti temporal graph;
- summaries, digests, relevance scores, and bootstrap candidates;
- Claude auto-memory and runtime-specific caches.

Every S3 component needs:

- a documented rebuild command;
- a source watermark/generation ID;
- a destructive rebuild test;
- provenance preservation;
- clear unavailability behavior;
- no exclusive copy of user data.

Hindsight is not yet rebuildable: existing records may be unique. Export and backfill them to S1 before applying the S3 contract or considering retirement.

## 5. Link disposition

Link 2.2.1 at commit `643e208adbbe2dfd1c91bf9e8305e6dec2b037a6` is the presumptive Level 2/3/5/6 component, subject to the adoption gates below.

Verified in an isolated spike:

- `link-mcp 2.2.1` installed and the cross-agent proof passed.
- 202 focused tests passed.
- A 10,082-page/30,000-edge smoke used SQLite FTS and passed all reported latency health thresholds.
- Capture, review planning, lifecycle, backup, FTS, and optional local Model2Vec semantic setup worked in a disposable workspace.

Observed limitations:

- No Hermes connector exists.
- Automatic transcript capture is bounded, omits tool calls/results, and is not Level 4.
- Link's own benchmark recorded an 11,269-estimated-token first MCP response; this fails the proposed 8,000-token bootstrap p95 gate and must be fixed or bypassed before active injection.
- `raw/` is not an immutable evidence log: capture refresh can rewrite a same-conversation file, captures can be deleted/deduplicated, and general raw creation is capped at 60 KiB.
- Multi-file writes use per-file atomic replacement and rollback journals, not serializable workspace transactions. Concurrent admission, deduplication, and supersession must therefore be fenced by the SQLite gate.
- Free-form preference classification misclassified one preference as a note.
- A direct SQLite/PostgreSQL contradiction was accepted without warning.
- Natural lexical paraphrase was weak before semantic setup.
- Plain text and unsupported JSONL transcript shapes produced zero or malformed proposals.
- Link's Markdown store and local indexes do not replace SQLite transaction/evidence semantics.

Therefore:

- **Use Link** for reviewed memory/wiki, source-backed knowledge, candidate review UX, bounded recall, lifecycle, and MCP/CLI sharing.
- **Do not use Link** as the sole evidence archive, write-ahead journal, contradiction oracle, or native transcript recorder.
- Normalize Hermes and Claude events before producing Link sources/candidates.
- Treat Link's Markdown pages as reviewed human-readable Canon only after gate acceptance; Link's capture files are proposals, not authoritative evidence.
- Contribute a Hermes connector upstream if the integration contract proves stable and the maintainer accepts it; keep the evidence adapter outside Link.

## 6. Bounded bootstrap and Area 0

`MEMORY` and `USER` become bounded hot projections, not the durable memory system.

### 6.1 What belongs in bootstrap

- universal routing/authority rules;
- a few high-frequency, high-impact user preferences;
- critical environment facts needed before retrieval;
- concise pointers to Link, skills, Git canon, and evidence retrieval;
- no long project history, procedures, raw evidence, or transient evaluations.

### 6.2 Write protocol

```text
memory request
  1. commit exact request + deterministic envelope to the SQLite operation journal
  2. if SQLite fails, fsync an append-only fallback record; otherwise return explicit not-accepted
  3. return accepted/not-applied with operation ID only after one durable write succeeds
  4. classify destination and generate consolidation proposal
  5. deterministically validate provenance, protected entries, size, and hashes
  6. build and validate an immutable projection generation
  7. atomically publish its current-generation pointer
  8. verify resulting hash and mark applied/injected
```

The LLM may perform step 4. All durability, validation, publication, and receipt steps are deterministic. Recall overlays accepted-pending writes as visibly pending so a client does not retry or incorrectly claim the write disappeared.

States are never conflated:

- `accepted` — durably journaled;
- `approved` — passed policy/human gate;
- `applied` — landed in its durable destination/projection;
- `injected` — observed in a client context.

### 6.3 Capacity behavior

- Trigger curation before the hard cap, with real high/low-water hysteresis.
- Current caps are 10,000 characters for `MEMORY` and 5,000 for `USER`. Phase A starts with warning at 75%, acceptance/consolidation at 85%, and a validated projection target at or below 70%; tune only from measured incidents.
- Do not blindly evict oldest entries from `USER` or `MEMORY`.
- If consolidation is unavailable or invalid, leave the operation pending and alert; exact content is safe in SQLite.
- Deterministic emergency eviction is allowed only for entries explicitly marked evictable and recoverable.
- Reset cancels/fences active projection operations before deleting a store.
- Archive/restore must be exposed and tested before automated removal is enabled.
- Client unavailability never breaks ordinary chat; it may reduce recalled context and produce a visible degraded-state marker.
- Bootstrap priority is deterministic: authority/security routing, critical cross-session user constraints, retrieval pointers, then high-frequency facts. Drop lowest-priority recall candidates first; never silently drop protected routing/security entries.
- A launchd-supervised single writer drains accepted operations with bounded exponential retry. Pending >15 minutes or any fallback-journal use alerts the Inbox thread (Telegram `22158`); ordinary queued acknowledgements remain quiet.

## 7. Consolidation and dreaming

Dreaming is an asynchronous proposal pipeline, not an authority:

```text
new S1 events after watermark
  → deterministic origin/scope filter
  → LLM extraction into typed candidates
  → compare with Link/Hindsight/Canon
  → emit new, duplicate, conflict, supersession, stale, and Canon-update proposals
  → gate review
  → approved promotion
```

Requirements:

- Incremental processing from an explicit committed watermark.
- Typed output with exact source event IDs.
- Temporal `valid_from`, `valid_to`, and `supersedes` when supported by evidence.
- Structural separation of data from instructions; never trust a second model as the sole injection defense.
- No direct write to `AGENTS.md`, Link durable memory, Hindsight, or Graphiti from the extractor.
- Versioned generations, replay, rollback, duplicate suppression, and destructive rebuild tests.
- Batch and retrieval-triggered review to avoid an unused ceremony.
- Track extraction precision, rejection rate, correction rate, retrieval/use rate, provenance completeness, and review burden.

## 8. Product decisions and experiments

### 8.1 Link versus Hindsight

Use one frozen synthetic corpus with stable event IDs and the same query set. Include:

- stable preferences;
- paraphrases with no keyword overlap;
- exact quotes and identifiers;
- duplicate claims;
- direct and subtle contradictions;
- three-step supersession and reversal;
- project/global scope collisions;
- malicious tool/web content;
- expired and redacted evidence;
- unavailable semantic model/server.

Measure:

- answer and retrieval precision/recall;
- correct abstention;
- current-state and historical temporal accuracy;
- evidence pointer completeness;
- correction/retraction behavior;
- p50/p95 latency and context tokens;
- offline and restart behavior;
- operator review actions and taxonomy friction;
- backup/export/rebuild/rollback success;
- operational footprint.

Use two deterministic suites with stable event IDs, identical adapters/limits/answer model/judge, and preserved per-query traces:

- **Per-change micro-suite:** 10–20 adversarial sessions covering every hard safety class below; runs on each relevant change.
- **Adoption suite:** about 40 carefully constructed sessions covering every query class and enough independent fixtures to expose regressions. This decides Link versus Hindsight.
- A generated 200-session/4,000-turn corpus is a load/growth test only, not a manually judged product-selection ritual.

Non-negotiable gates:

- 100% lossless reconstruction remains the S1 responsibility; neither semantic candidate may weaken it.
- Zero unapproved or synthetic-secret promotions and zero cross-scope leakage.
- 100% promoted-memory provenance to canonical event IDs/supporting spans or explicit user source.
- No silent loss or divergence under concurrent, timeout, restart, and replay tests.
- Both clients continue in degraded mode during semantic-backend outage, with at most two seconds added before fallback.
- Export/restore into an empty installation reproduces admitted memory, lifecycle state, and provenance.

Quality targets: evidence recall@10 ≥90% overall, ≥80% paraphrase, ≥75% multi-hop; current-truth precision@1 ≥95%; contradictory/stale exposure@3 ≤5%; historical/as-of accuracy ≥95%; unsupported derived claims ≤1%; warm recall p95 ≤500 ms; normal packet p95 ≤4,000 tokens; first bootstrap p95 ≤8,000 tokens; and median capture/review ≤2 user actions with <10% taxonomy corrections.

Disposition:

- **Replace Hindsight with Link** if Link meets or exceeds retrieval and correction gates, preserves provenance, remains available offline, and materially reduces complexity.
- Replacement requires every hard gate, no critical retrieval/temporal subset more than two percentage points worse than Hindsight, and a written dimension-by-dimension case showing material improvement in at least two of latency, token cost, operator time, or rollback/rebuild time without a new critical deficit.
- **Keep both** only if Hindsight demonstrates a distinct mental-model/experience capability with low overlap and Link remains canonical; duplicate facts across both are prohibited.
- **Keep Hindsight, limit Link to wiki/canon** if any hard gate fails or Link needs more than two candidate-specific maintained patches before quality testing.

### 8.2 Optional Graphiti

Test temporal questions over changing people, organizations, ownership, commitments, and validity intervals.

Adopt Graphiti only if it materially improves current-state and historical answers over Link's explicit supersession metadata and simple SQLite temporal views, with acceptable extraction cost and provenance. Otherwise reject it.

Start the Graphiti arm only when the base winner scores below 80% multi-hop recall or 95% temporal/entity accuracy. Adopt only for ≥10 absolute points of multi-hop gain or ≥5 points of temporal/entity gain, ≥5 weighted-score improvement after complexity penalties, ≤50% token overhead, ≤300 ms warm-p95 overhead, complete provenance, and a proven destructive rebuild from S1 plus the gate.

### 8.3 MemPalace

Build the SQLite Level 4 baseline first:

- FTS5;
- trigram/exact substring search;
- metadata/time filters;
- conversation neighbor expansion;
- verbatim spans with event IDs.

Adopt MemPalace only if it wins on measured exact/span recall or materially lowers integration cost without becoming the only evidence copy.

### 8.4 Basic Memory

Presumptively reject alongside Link due to canonical Markdown overlap. Reconsider only if a concrete capability gap survives the Link spike and comparison.

### 8.5 Multimodal evidence

Phase B retains original images, audio, video, and documents in the CAS with MIME type, dimensions/duration, source event, hashes, and producer-provided descriptions. Phase C/D builds rebuildable OCR, PDF text, image-description, and audio-transcript projections with model/version metadata and exact attachment provenance. Active recall returns the original attachment reference plus derived text and visibly degrades to exact metadata when extraction is unavailable. Multimodal embeddings are optional later experiments, not a prerequisite for exact Level 4 recovery.

## 9. Client integrations

### 9.1 Hermes

- Native event sink writes every committed Hermes message/tool event into S1 idempotently; existing `state.db` remains source-compatible during migration.
- A Link tool/provider supplies bounded brief and task recall.
- The existing `memory` tool journals capacity-sensitive writes and routes them to destination proposals rather than rejecting at the cap.
- `/z` presents natural free-form review over Link/gate records.
- Built-in `MEMORY`/`USER` remain available as bounded bootstrap projections and degraded-mode fallback.
- Build the local Hermes adapter independently of upstream acceptance; upstream contribution is a later maintenance optimization.

### 9.2 Claude Code

- Capture exact Claude transcript bytes and source coordinates before cleanup; versioned normalization is rebuildable S3 and native wrappers are never passed directly to Link.
- Normalize complete messages, tool calls/results, parent/subagent relations, attachments, and source timestamps from retained raw evidence.
- Verify `CLAUDE.md`/`AGENTS.md` behavior with an explicit canary task and record `injected=unknown` when the client exposes no trustworthy load telemetry.
- Use Link MCP or CLI skills for recall; session hooks may inject only a bounded brief.
- Measure MCP schema overhead separately from payload. Default to the CLI/skill path if the 8,000-token first-bootstrap gate cannot be met; MCP remains opt-in until then.
- Treat Claude auto-memory as disposable S3 cache.
- Claude native tool approval and durable-memory promotion are separate permissions unless one UI explicitly names and requests both effects.

### 9.3 Other clients

- Prefer the same Link MCP contract and S1 event envelope.
- Never copy canonical memory into client-private stores as the synchronization mechanism.
- Client adapters declare producer/version and preserve raw source identity.

### 9.4 Incumbent stores and non-interference

- Inventory and preserve Hermes `MEMORY`/`USER`, the pending/candidate SQLite databases, Hindsight, and `site-private/memory` before migration.
- `site-private/memory` is existing S2 Canon and remains the umbrella private Git store. Link occupies only `memory/link/`; existing one-fact-per-file material is indexed or referenced, not bulk-copied into a second canon.
- Export Hindsight into S1 as derived historical evidence with honest provenance gaps before calling it rebuildable or considering retirement.
- Codex's built-in memory consolidation owns `memory/codex/memory_summary.md` and `raw_memories.md`; this plan does not rewrite, delete, or compete with those whole-file artifacts. Any later integration consumes them read-only or uses `memory/codex/extensions/ad_hoc/` according to existing policy.

## 10. Migration plan

### Phase A — stop bootstrap capacity failures

- Create the versioned SQLite control database with `operation`/receipt tables, FULL-sync acceptance, fallback journal, and explicit states in Hermes.
- Add high-water monitoring and a bounded projection interface.
- Do not enable blind FIFO eviction.
- Add read-your-writes pending overlay, single supervised worker, Inbox alerting, and the per-change micro-suite.
- Add fault tests for queue/database/fallback failure, lock contention, disk full, crash boundaries, reset races, approval isolation, replay, and archive restoration.
- Preserve existing memory and Hindsight behavior.

**Exit gate:** a deliberately full MEMORY and USER never lose an acknowledged write; when no durable medium accepts it Hermes returns explicit not-accepted; model/provider outage leaves accepted work pending and recoverable. **Reversal:** disable the interception path and replay/inspect the journal; existing stores remain untouched.

### Phase B — lossless evidence foundation

- Add raw-object/event/conversation/gap schema and deterministic source-coordinate event IDs to the Phase A control database.
- Retain raw producer bytes first; build versioned normalized projections second.
- Backfill surviving Hermes/Claude transcripts, `MEMORY`/`USER`, candidate stores, Hindsight export, and existing memory inventory idempotently; record historical gaps.
- Add live Hermes ingestion and Claude tail/checkpoint adapter.
- Capture attachments and tool events.
- Verify backup coverage and perform restore test.
- Add exact/trigram/neighbor retrieval.

**Exit gate:** exact source spans are recoverable across clients; repeated ingestion creates no duplicates; interrupted ingestion resumes; consistent snapshot restore passes integrity/foreign-key/hash/retrieval checks. **Reversal:** stop sinks and adapters; retained producer sources and incumbent stores remain authoritative and no source is deleted.

### Phase C — staged Link integration

- Package Link in an isolated managed environment.
- Add Hermes connector and normalized candidate/source adapter.
- Keep extraction/capture proposal-only; accepted reviewed memories become canonical only through the serialized `site-private/memory/link/` commit path.
- Run Link and Hindsight on the same frozen corpus.
- Implement natural `/z` façade and retrieval-triggered review prototype.

**Exit gate:** the micro-suite and adoption comparison are published; Link canonical writes have sync/commit/push/read-back evidence and no divergent copy. **Reversal:** disable Link recall/writes and revert its memory-only commits; S1, Hindsight, and incumbent Canon remain.

### Phase D — bounded active recall

- Enable Link bounded recall in Hermes and Claude with visible provenance/confidence.
- Generate bootstrap proposals, not automatic instruction changes.
- Publish immutable Link/bootstrap generations with an atomic pointer; readers may see a complete stale generation but never a partial one.
- Measure time-to-context, tokens, latency, false recall, and user correction burden.

**Exit gate:** degraded-mode behavior, deterministic budget/drop order, multimodal metadata fallback, and CLI/MCP token gate are proven; retrieval improves real tasks without material contamination or repeated review friction. **Reversal:** disable active recall and return to incumbent bootstrap/native recall while preserving all accepted data.

### Phase E — consolidation/dreaming

- Run typed extractor in shadow mode.
- Enforce provenance, origin, scope, conflict, and injection rules.
- Enable batch/retrieval-triggered review.
- Consider narrowly reversible low-risk auto-promotion only after measured precision and explicit operator approval.

**Entry gate:** written threat model and extractor-immutable envelope fields are implemented; web/tool-origin instruction exclusion, secret handling, and injection invariants pass the micro-suite. **Reversal:** stop the worker and reject/expire unpromoted proposals; no direct authority writes exist.

### Phase F — simplify

- Decide Link versus Hindsight.
- Decide whether Graphiti or MemPalace earned deployment.
- Name each proposed removal and prove its complete contents recoverable from S1/S2 before operator approval; never use a generic bulk-removal action.
- Perform destructive rebuild and rollback drills.
- Document final authority and incident-recovery procedures.

**Exit gate:** every retained component has a distinct role; every removed component has export, recovery, and rollback evidence. **Reversal:** restore the exported component and its adapter from the preserved versioned artifact.

## 11. Acceptance and adversarial tests

Minimum test pack:

1. Fill MEMORY and USER to the boundary; enqueue add/replace/batch; crash at each commit boundary; prove recovery and no silent loss.
2. Expire a worker lease while a second claimant runs; prove fencing prevents stale overwrite.
3. Stage an approval record and an overflow record; prove automatic workers cannot apply approval records.
4. Reset a store with active operations; prove operations are cancelled/fenced and no stale replay resurrects data.
5. Delete and rebuild every S3 index from S1 + S2.
6. Ingest the same Hermes/Claude transcript twice; prove stable deduplication.
7. Recover an exact quote, neighboring rationale, tool output, and attachment reference.
8. Contradiction cascade: A → B → A; answer current and historical questions with evidence.
9. Scope collision: conflicting project/global facts do not leak across projects.
10. Prompt-injection test: instructions inside web/tool/transcript content remain data and never alter Canon or promotion policy.
11. Redact an event; cascade evidence withdrawal and re-review dependent memories.
12. Disable Link/Hindsight/semantic model; chat continues with bounded degraded behavior.
13. Natural-language memory entry succeeds without type/scope taxonomy memorization.
14. Candidate backlog test: retrieval-triggered review surfaces useful candidates and suppresses rejected repetitions.
15. Backup restore into an isolated home reproduces S1 and rebuilds S3.
16. Hold a write lock beyond `busy_timeout`; prove SQLite or fallback accepts durably, or return explicit not-accepted.
17. Exhaust durable storage; prove no false accepted acknowledgement.
18. Crash after raw acceptance, normalization, archive receipt, projection build, pointer publication, and before final receipt; prove idempotent recovery.
19. Purge/redact a distinctive literal; prove it is absent from every active retrieval surface and that backup limitations are reported honestly.
20. Inject origin/scope/sensitivity instructions through web/tool content; prove deterministic envelope fields cannot change and the claim cannot enter instruction/bootstrap classes.
21. Run multimodal recovery for an image, PDF, and audio attachment: recover original CAS object and derived text with version/provenance.
22. Export and restore Hindsight, Hermes stores, gate state, and Link Canon before any retirement decision; compare item counts/hashes and document gaps.

## 12. Metrics

- zero acknowledged-but-unrecoverable writes;
- 100% promoted claims with resolvable evidence or Git revision;
- exact and paraphrase retrieval precision/recall by query class;
- temporal current-state and historical accuracy;
- abstention accuracy;
- p50/p95 ingest and recall latency;
- context packet tokens and time-to-context;
- candidate approval/rejection/expiry/retrieval rates;
- review actions per useful promoted memory;
- contradiction and correction latency;
- rebuild and restore duration;
- provider/model cost;
- bootstrap utilization and high-water incidents;
- degraded-mode frequency and recovery time.

Do not accept vendor benchmark numbers as deployment evidence. Reproduce claims against the frozen local corpus and publish the harness/results.

## 13. Explicit non-goals

- No raw transcript Git repository.
- No automatic rewriting of `AGENTS.md` or `CLAUDE.md`.
- No requirement to run all candidate memory products permanently.
- No full transcript injection into every prompt.
- No LLM in the durability acknowledgement path.
- No silent promotion based only on model confidence.
- No attempt to synchronize lossy client-native caches bidirectionally.
- No global taxonomy the user must memorize.

## 14. Evidence and sources

Primary/product sources:

- Link repository and docs: <https://github.com/gowtham0992/link>, <https://gowtham0992.github.io/link/memory-contract.html>, <https://gowtham0992.github.io/link/why-link.html>, <https://gowtham0992.github.io/link/scale.html>, <https://gowtham0992.github.io/link/mcp.html>
- Hindsight documentation: <https://hindsight.vectorize.io/>
- Claude Code memory documentation: <https://code.claude.com/docs/en/memory>
- Karpathy LLM Wiki specification: <https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f>
- Graphiti: <https://github.com/getzep/graphiti>
- Basic Memory: <https://github.com/basicmachines-co/basic-memory>

Local evidence retained outside the repository:

- `~/tmp/hermes/link-spike/HA_SPIKE_VERDICT.md`
- `~/tmp/hermes/memory-architecture-round1-claude-opus.md`
- `~/tmp/hermes/memory-architecture-round1-gemini-pro.md`
- `~/tmp/hermes/memory-architecture-round1-evidence.md`
- `~/tmp/hermes/area-0-7-superseded-experiment/`
- `~/tmp/hermes/memory-architecture-v2-claude-opus-review.md`
- `~/tmp/hermes/memory-architecture-v2-gemini-review.md`

## 15. Review gate

This plan records the operator-approved architecture and authorizes phased implementation only through each phase's explicit entry/exit gates. It does not authorize skipping reviews, deleting incumbent stores, or silently enabling promotion.

1. Give the actual file—not a summary—to fresh-context reviewers from at least two model families.
2. Assign one adversarial reviewer to durability, security, authority, and failure modes.
3. Assign one reviewer to completeness, product overlap, benchmark design, and user friction.
4. Preserve disagreements rather than silently resolving them.
5. Discuss material findings with the operator.
6. Revise, run repository documentation checks, commit, open a PR, and update issue #139 with exact review and test evidence.

Completed review evidence:

- Claude Opus 5 adversarial review: 11 blockers and phase-by-phase corrections; report SHA-256 `8fe1c58c70254f7ab4d4dfed411766dd289da85025650c2586728cb33d8733d9`.
- Gemini 3.1 Pro High completeness review: benchmark/multimodal/concurrency corrections; report SHA-256 `3ce23f050ce34ebc0742c4b7bd9cd2aef80fb5bfb57b4380866106c79d2b79c9`.
- Operator decision: Link reviewed Markdown is canonical under `site-private/memory/link/` from Phase C, subject to the serialized memory-only commit protocol above.
- Rejected recommendation: ordinary Claude tool approval does not imply durable-memory approval.
- Resolved concurrency recommendation: publish immutable generations with an atomic pointer; readers do not take the writer lease.
