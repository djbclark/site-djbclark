# SIPB LLMs as an agentic-coding backend: measurements and requests

Date: 2026-10-12. Author: a SIPB LLMs user (djbclark), measurements run by an AI
coding agent (Claude Code) through a local logging proxy. No credentials, prompts
or responses are included here.

Server as observed: Open WebUI 0.6.30 in front of Ollama 0.32.13 at
`https://llms-dev-1.mit.edu/api` (OpenAI-compatible `/api/chat/completions`).
Client: Charm Crush (a terminal coding agent) driven non-interactively, one request
at a time, models run serially so we never asked the server for two models at once.

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
Open WebUI (check whether a newer release than 0.6.30 already does).

4.2 **Silent queueing.** 7 of our requests received no data at all for 2 minutes and
were aborted by the client (windows 12:35-13:03 on 2026-10-12, models qwen3.6 and
gpt-oss:20b; the same models answered in 10-19 s minutes later). We assume the
requests were waiting behind another model or user. Request: any signal while a
request is queued (an SSE comment every ~15 s, or an immediate 429/503 with
`Retry-After`), and a note on how queued requests are ordered. Our proxy now serializes
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
   Happy to share it.
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

Raw data and scripts: `~/.local/state/bigteam/sipb-bench/` on the author's machine
(`results.jsonl`, `bench.py`); the proxy and its tests are in
`tools/sipb-llms-proxy/` of the author's site-djbclark repository.
