# SIPB LLMs as an agentic-coding backend: measurements and requests

Date: 2026-10-12. Author: a SIPB LLMs user (djbclark), measurements run by an AI
coding agent (Claude Code) through a local logging proxy. No credentials, prompts
or responses are included here.

Server as observed: Open WebUI 0.6.30 in front of Ollama 0.32.13 at
`https://llms-dev-1.mit.edu/api` (OpenAI-compatible `/api/chat/completions`).
Client: Charm Crush (a terminal coding agent) driven non-interactively, one request
at a time, models run serially so we never asked the server for two models at once.

## TL;DR

**Results.**

1. Idle, the server is fast: a 10k-token prompt prefills in about 2 s (0.6 s repeat), decode 60-200 chunks/s, a model swap costs 7-19 s.
2. A real tool-using coding agent works on it: `qwen3.6:35b-a3b` was best (small bug-fix task 24-67 s; 5-phase task 3 of 3 with a verify loop, 198-539 s). `qwen3.5:35b`, `qwen3-coder:30b` and `gemma4:26b` are usable. `gpt-oss:20b` (0 of 9) and `devstral:24b` (0 of 4) do not work.
3. What hurt reliability: tool calls end with `finish_reason: "stop"`, silent 2+ minute queueing, two models with broken tool calls, and `null` bodies for over-long prompts. We worked around all four in a local proxy.

**Server-side improvements, most to least useful** (hardware fixed). "Human" is hands-on admin time (reading, deciding, approving, checking), not time the AI works or the server spends downloading or restarting. "AI tokens" is the estimated total an AI assistant would spend doing the work. Both are our estimates, not measurements.

| # | Change | Effect | Human | AI tokens | Details |
| --- | --- | --- | --- | --- | --- |
| 1 | Upgrade Open WebUI past 0.6.30; try per-model "Function Calling: Native"; run our conformance script | Tool calls work for every client, not just ours | 20 min | 60k | 4.1, 7.1 |
| 2 | Front proxy: SSE keepalive while queued, 429/503 + `Retry-After`, 400 instead of `null`, 1 request per key per model | No more silent 2-minute stalls, fair sharing | 15 min (review and deploy ours) | 100k | 4.2, 4.5, 7.6 |
| 3 | Keep one fast mixture-of-experts model resident (`OLLAMA_KEEP_ALIVE=-1`, e.g. `qwen3.6:35b-a3b`) | Most requests skip the 7-19 s swap | 5 min | 10k | 4.6, 7.3 |
| 4 | `OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_KV_CACHE_TYPE=q8_0`, then try a larger context | Half the KV cache, room for longer prompts | 10 min | 20k | 4.5, 7.2 |
| 5 | Hide `gpt-oss:20b` and `devstral:24b`, or fix them (re-pull tags, check templates) | Users stop picking models that cannot call tools | 5 min to hide, 20 min each to fix | 10k to hide, 60k each to fix | 4.3, 4.4, 7.1 |
| 6 | Presets per recommended model (`num_ctx`, `keep_alive`, reasoning effort) and a shorter model list | Fewer accidental swaps, thinking capped | 20 min | 40k | 7.3, 7.5 |
| 7 | Etiquette note: one model, small prompts, no parallel agents; per-key request logs | Protects web-UI users from agent traffic | 15 min | 20k | 7.7 |
| 8 | Status page: loaded model, queue length, rolling time to first token | "Down or busy?" becomes a lookup | 30 min | 100k | 7.8 |
| 9 | Q4/Q5 builds instead of the F16 `aya` models | Faster loads, more headroom | 10 min | 15k | 7.2 |

## 1. Summary

1. The server is fast enough for agentic coding when it is idle: about 10k-token
   prompts prefill in about 2 s (0.5-0.8 s when the prefix is cached), decode runs
   60-200 chunks/s depending on the model.
2. Three server-side behaviours cost us most of the reliability, listed in section 4:
   a wrong `finish_reason` on tool calls, silent queueing with no data for 2+ minutes,
   and two models whose tool calls do not come through (gpt-oss:20b, devstral:24b).
3. Of the models we could run a real tool-using task on, `qwen3.6:35b-a3b-q4_K_M`
   was the best overall; `qwen3.5:35b` and `qwen3-coder:30b` are usable; `gemma4:26b`
   works but thinks too long.

## 2. Raw server speed (direct probes, one request at a time)

| model | cold first token (model swap) | decode, chunks/s | 10k-token prefill, 1st / repeat |
| --- | --- | --- | --- |
| qwen3.5:35b | 7-8 s | 89-92 | 2.0 s / 0.6-0.7 s |
| qwen3.6:35b-a3b-q4_K_M | 14.5 s | 95 | 2.0 s / 0.6 s |
| qwen3-coder:30b | 11.3 s | 163 | 1.3 s / 0.5 s |
| devstral:24b | 8.5 s | 61 | 3.0 s / 0.5 s |
| gpt-oss:20b | 8.3 s | 197 | 1.3 s / 0.8 s |
| gemma4:26b | 18.1 s | 156 | 1.9 s / 1.1 s |

"Chunks/s" counts streamed deltas including reasoning, so it is an upper bound on
tokens/s. Cold = first request after another model was loaded; a later swap probe
took 10-19 s. The repeat-prefix speedup shows prefix caching works on a warm model.

## 3. Task results (real tool use, 37 valid runs, all against this server; runs that hit another provider by mistake are excluded on this server)

Task A (two runs per cell): a three-test Python repo with two bugs; fix it, run the tests, commit.
Task B: a five-phase job (build a small package with 12+ tests, run it, make one
network call, extend it with 4+ tests, write notes and commit), 600-900 s cap.

| model | task A (2 runs) | task B |
| --- | --- | --- |
| qwen3.6:35b-a3b (thinking) | 67 s / 47 s, pass (4 earlier runs failed on 2-minute no-data stalls, section 4.2) | 178 s with a hint prompt (done, 14 tests); with rules + a verify-and-retry loop 3 of 3 passed in 198-539 s |
| qwen3.6:35b-a3b (no thinking) | 31 s / 24 s, pass | hit the cap (249 tool calls) |
| qwen3.5:35b (thinking) | 45 s / 45 s, pass | 444 s, tests passed, forgot the commit |
| qwen3-coder:30b | 117 s / 37 s, pass | hit the 600 s cap |
| gemma4:26b | 133 s / 64 s, pass | hit the 600 s cap (about 2400 reasoning chunks) |
| gpt-oss:20b | failed 9 of 9 (6 aborted streams, 3 no-data stalls) | not run |
| devstral:24b | failed 4 of 4 (0 tool calls) | not run |

One run per cell unless noted; treat the B column as indicative.

## 4. Server-side problems and requests

4.1 **Tool-call streams end with `finish_reason: "stop"`.** A streamed response that
contains a complete `tool_calls` delta finishes with `"stop"`, not `"tool_calls"`. OpenAI-
style clients that continue the loop only on `tool_calls` (Crush, and others) end the
turn after the first tool call without running it. We worked around it in the proxy
(rewrite `stop` to `tool_calls` when the stream had tool calls); our log shows
`finish_reason_raw: "stop"` with `finish_reason_sent: "tool_calls"`. Request: fix in
Open WebUI. The latest release is v0.12.0 (2026-10-10), well past the 0.6.30 we see. We searched open-webui/open-webui issues on 2026-10-12 (terms: `finish_reason tool_calls`, `tool_calls finish_reason stop`, `streaming tool call finish reason`) and found no report of exactly this behaviour; the nearest threads are [#28492](https://github.com/open-webui/open-webui/issues/28492) and [#27363](https://github.com/open-webui/open-webui/issues/27363). We did not test v0.12.0, so check it first and file an issue if it still happens.

4.2 **Silent queueing.** 7 of our requests received no data at all for 2 minutes and
were aborted by the client (windows 12:35-13:03 on 2026-10-12, models qwen3.6 and
gpt-oss:20b; the same models answered in 10-19 s minutes later). We assume the
requests were waiting behind another model or user. Request: any signal while a
request is queued (an SSE comment every ~15 s, or an immediate 429/503 with
`Retry-After`), and a note on how queued requests are ordered. Open WebUI has an open feature request for exactly this, [#31408](https://github.com/open-webui/open-webui/issues/31408) (early SSE and heartbeat across streaming APIs for reverse-proxy compatibility). Our proxy now serializes
our own requests per model and retries 502/503/504; we raised the client timeout to 10 min.

4.3 **gpt-oss:20b tool calls fail.** The model's tool call arrives with empty
arguments (`{}`), then the stream aborts with `unexpected EOF` (6 of 9 runs; the other 3 were no-data stalls). Request:
check the Ollama/Open WebUI tool-call parsing for this model.

4.4 **devstral:24b tool calls come back as plain text** (the end of a function-call block
appears in the message content, no `tool_calls` delta). Request: check the model template
and tool parser; this model is built for agentic coding and would be useful.

4.5 **An over-long prompt returns HTTP 200 with the body `null`.** The effective context
is about 32768 tokens; larger requests return `null` instead of an error. A 400 with a
message would let clients trim and retry. (Our proxy converts it.) Please also publish the
effective context length per model; if memory allows, raising `OLLAMA_CONTEXT_LENGTH`
(with `OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_KV_CACHE_TYPE=q8_0` to keep the cache small)
would let coding agents carry more tool output.

4.6 **One model at a time.** Each model swap costs 10-19 s and, under contention, can
trigger 4.2. Requests: a longer `OLLAMA_KEEP_ALIVE` for the shared default model, and
if one model could stay permanently resident, a mixture-of-experts coding model such as
`qwen3.6:35b-a3b-q4_K_M` (about 3B active parameters) is the cheapest for the hardware.

## 5. What we changed on our side

1. Loopback proxy (about 500 lines, stdlib Python): finish_reason fix, `null` to 400,
   per-model request serialization, retries, and a latency log (model, prompt size,
   queue wait, time to first token, total, status, raw and sent finish_reason; no content).
   Source, tests and the launchd plist: <https://github.com/djbclark/site-djbclark/tree/master/tools/sipb-llms-proxy>; its README documents the log fields.
2. Client settings: 10-minute idle timeout, unused tools and skills disabled to keep
   prompts small (the default tool/skill prompt was about 28k tokens of a 32k window).
3. One model for all requests from our agents (no title/summary calls to a second model),
   to avoid forcing swaps for other users.
4. A short persistent rules file for the agent and an optional "verify the work and try
   again" loop; the rules alone gave 0 of 3 passes on task B (the final test command failed), adding the verify loop gave 3 of 3 (1-2 verify rounds each).

## 6. Questions for the admins

1. Is there a concurrency or rate policy we should respect (requests in flight, hours)?
2. Which model do you want agent traffic on, if you can pin one?
3. Is an Open WebUI upgrade planned? 0.6.30 is behind Ollama 0.32.13.

## 7. Suggestions for the admins (hardware treated as fixed)

Everything below is a software or configuration change; none needs new hardware. We cannot see
the server, so treat them as hypotheses to check, cheapest first.

7.1 **Fix the tool-call path (the biggest win for coding agents).** Upgrade Open WebUI past
0.6.30 and check whether the `finish_reason` mapping is fixed; try the per-model "Function Calling:
Native" setting so Open WebUI passes Ollama's own tool calls through instead of re-parsing them.
For `gpt-oss:20b` and `devstral:24b`, re-pull the model tags (templates and tool parsers are updated
in Ollama releases) and check `ollama show --modelfile <model>` for a template that handles tools.
A 30-line conformance script (one tool, expect a `tool_calls` delta and `finish_reason: "tool_calls"`)
run after each upgrade would catch regressions. Ours is [bench/toolcall_conformance.py](bench/toolcall_conformance.py) (stdlib Python, `SIPB_API_KEY=... toolcall_conformance.py MODEL...`, `--long` also checks the over-long-prompt case). On 2026-10-12 it failed against the server directly (`finish_reason 'stop'`, streamed and not) and passed through our proxy.

7.2 **Make memory go further without new hardware.** `OLLAMA_FLASH_ATTENTION=1` plus
`OLLAMA_KV_CACHE_TYPE=q8_0` roughly halves the KV cache, which either gives headroom at 32768 tokens
or lets `OLLAMA_CONTEXT_LENGTH` rise for the mixture-of-experts models whose weights are small
(qwen3.6:35b-a3b, qwen3-coder:30b, gpt-oss:20b). Check `ollama ps` for the real split between
GPU and CPU after each change. `aya:35b` and `aya:8b` are stored unquantized (F16): a Q4/Q5 build
would load faster and leave room, and they are the likeliest cause of a slow swap.

7.3 **Fewer, cheaper model swaps.** (a) Pin one fast general model with `OLLAMA_KEEP_ALIVE=-1`
(or a day) so most requests find it loaded; our data says a mixture-of-experts model with about
3B active parameters is the best fit (7.4). (b) Tag a short "recommended" set in Open WebUI and
hide or group the rest: 48 entries, many of them niche, push users into swaps that cost everyone
10-19 s. (c) Keep `OLLAMA_NUM_PARALLEL=1` for dense models (our prefix cache hit: 2.0 s first,
0.6 s repeat for a 10k-token prompt), and try 2 only for small mixture-of-experts models.

7.4 **Prefer mixture-of-experts models for shared GPUs.** On the same memory they decoded 1.5-3x
faster than the dense models in our probes (qwen3-coder:30b 163 and gpt-oss:20b 197 chunks/s vs
devstral:24b 61) and `qwen3.6:35b-a3b` was the most reliable agent model. Retiring or demoting dense
models of similar quality (and the F16 ones) frees the single GPU slot for models that finish sooner.

7.5 **Pin the settings that matter in Open WebUI model presets.** A preset per recommended model
with `num_ctx`, `keep_alive` and a sane default reasoning effort removes per-client guesswork;
agent clients then get the same behaviour as the web UI. Thinking models should have their
thinking budget capped (`gemma4:26b` produced ~2400 reasoning chunks on one task).

7.6 **Tell clients what is happening while they wait.** A small reverse proxy (nginx, Caddy, or the
Python [proxy](https://github.com/djbclark/site-djbclark/tree/master/tools/sipb-llms-proxy/sipb-llms-proxy) we use) in front of Open WebUI can (a) send an SSE comment every 15 s while
a request is queued so idle timeouts do not fire, (b) cap in-flight requests per API key (1 per model
is enough for an interactive agent), (c) answer 429 or 503 with `Retry-After` when the queue is
longer than N instead of holding the connection, and (d) return a 400 with token counts for an
over-long prompt instead of `null`. Open WebUI itself has no queue visibility.

7.7 **Fair use between interactive and agent traffic.** Agent clients send 10-30 requests per task
with 20k+ token prompts; one agent can hold the only model for minutes. Per-key concurrency of 1,
a published etiquette note (keep prompts small, one model, no parallel agents), and optionally
off-peak guidance for long jobs would protect web-UI users. Per-key request logs (model, prompt
size, time to first token, queue wait) would show who needs what; our log schema is in the [proxy README](https://github.com/djbclark/site-djbclark/tree/master/tools/sipb-llms-proxy/README.md).

7.8 **Observe and publish.** A status page with `ollama ps` (loaded model, memory), queue length and
a rolling time-to-first-token would turn "is it down or busy?" (FAQ) into a lookup. Alert when
time to first token exceeds ~60 s. Publish a per-model capability matrix (context, tool calling,
vision, thinking) and the Friday maintenance window next to the model list; ours is in section 3
and [api.md](api.md).

7.9 **What we cannot judge from outside:** GPU model and memory, whether CPU offload is in play,
other users' load, and what Open WebUI features are enabled. If you share the GPU class and
`ollama ps` output we can narrow the list.

## 8. Everything we used, with links

Nothing is held back. Files in this directory (all public, `site-djbclark` repository):

1. Raw measurements: [bench/results.jsonl](bench/results.jsonl), one JSON object per probe or task run
   (runs marked INVALID were contaminated by a mistake on our side and are excluded from section 3).
2. Benchmark harness: [bench/bench.py](bench/bench.py) (probes, then tasks A and B through an agent).
3. Tool-call conformance check: [bench/toolcall_conformance.py](bench/toolcall_conformance.py).
4. Agent rules file: [bench/rules.md](bench/rules.md). Crush configuration (key removed): [bench/crushrc.example](bench/crushrc.example).
5. Server reference as we see it: [api.md](api.md), [openapi.json](openapi.json), [faq.md](faq.md), and how we set up clients: [setup.md](setup.md).

Code in other repositories:

6. The loopback proxy (finish_reason fix, `null` to 400, per-model queue, retries, latency log, tests, launchd plist):
   <https://github.com/djbclark/site-djbclark/tree/master/tools/sipb-llms-proxy>.
7. `acp-run`, the agent runner with the verify-and-retry loop (`--verify CMD`):
   <https://github.com/djbclark/djbclark-ade/tree/master/tools/acp-run>.
8. Our Crush build with the ACP bridge and an auto-approve mode (upstream pull requests):
   <https://github.com/charmbracelet/crush/pull/2450> and <https://github.com/charmbracelet/crush/pull/3909>.
9. Index of all our SIPB-related material, including the quota collector: [README.md](README.md).
