# ClinePass upstream PR — external reviews, 2026-10-03

Two non-Claude reviewers were run against the ClinePass change after it was
cherry-picked onto current `upstream/main`. **Both returned NEEDS WORK, which is
why the PR to BerriAI/litellm was NOT opened.**

- Branch: `clinepass-upstream` in the worktree `~/src/litellm-clinepass-upstream`
  (3 commits on top of `upstream/main` `d260765652`; `41/41` tests pass via
  `.venv-test/bin/python -m pytest tests/test_litellm/llms/clinepass/ -q`).
- Reviewers invoked per `skills/model-routing/SKILL.md`: `codex exec -s read-only`
  and `agy --dangerously-skip-permissions -p='<prompt>'`.
- Raw outputs were session-scratchpad only and are gone; the findings are below.

## Independently verified before trusting the reviewers

Two load-bearing claims were re-checked first-hand (this chain's rule after
agents got decisive facts wrong):

1. **The P1 credential leak is REAL, and it is not fixed.** Confirmed end to end:
   `speech()` at `litellm/main.py:8319` captures `api_base` and
   `dynamic_api_key` from `get_llm_provider`; for `clinepass`,
   `_get_openai_compatible_provider_info` (transformation.py:181-186) sets
   `api_base` to `CLINEPASS_API_BASE` and `dynamic_api_key` to
   `CLINEPASS_API_KEY`. The dispatch branch at `main.py:8389` is then entered
   because `clinepass` is in `openai_compatible_providers`
   (`litellm/constants.py:1045`) and not in `AZURE_OPENAI_AUDIO_PROVIDERS`.
   Inside that branch `api_base` is already the Cline host, but the key chain is
   `api_key or litellm.api_key or litellm.openai_key or get_secret("OPENAI_API_KEY")`
   — it **omits `dynamic_api_key`**, so the ClinePass key is discarded and the
   user's OpenAI key is used. Net effect:
   `litellm.speech(model="clinepass/...", input="hi", voice="alloy")` POSTs to
   the ClinePass host with `Authorization: Bearer <OPENAI_API_KEY>`.
2. **CI would never have run the new tests.**
   `.circleci/scripts/unit_selection.sh:62` selects provider tests with
   `find tests/unit/llms -name 'test_*.py'`, but the file is at
   `tests/test_litellm/llms/clinepass/chat/`. Both directories exist on main.

## codex findings (9; verdict NEEDS WORK)

1. **[P1] Exception registration enables credential leakage through unsupported endpoints** — [litellm/constants.py:1045](/Users/djbclark/src/litellm-clinepass-upstream/litellm/constants.py:1045)  
   `openai_compatible_providers` also controls audio dispatch. A `litellm.speech(model="clinepass/...", input="hi", voice="alloy")` call can reach the Cline host using `OPENAI_API_KEY` through `main.py:8406`, despite this provider advertising no speech support. Remove this broad registration and register ClinePass explicitly with `_map_openai_exception`, as Mistral does. Add a regression proving unsupported endpoints make no outbound request

2. **[P2] Token counts cannot prove truncation** — [transformation.py:109](/Users/djbclark/src/litellm-clinepass-upstream/litellm/llms/clinepass/chat/transformation.py:109)  
   A response can finish naturally or encounter a stop sequence exactly at the token cap. Rewriting its explicit `stop` to `length` misreports success and can trigger unnecessary continuation requests. Streaming also preserves the original reason, producing inconsistent behavior. Remove this speculative correction, or require an explicit, documented provider truncation signal

3. **[P2] Post-call callbacks execute twice, and prematurely for async calls** — [litellm/main.py:2497](/Users/djbclark/src/litellm-clinepass-upstream/litellm/main.py:2497)  
   The inherited response transformation already calls `logging_obj.post_call`. This additional call duplicates callbacks and overwrites the raw response and request metadata. On the async path, `response` is still a coroutine, so callbacks run before the HTTP request finishes. Delete this call and let the shared HTTP handler own post-call logging

4. **[P2] ClinePass has no model metadata or pricing registration** — [transformation.py:206](/Users/djbclark/src/litellm-clinepass-upstream/litellm/llms/clinepass/chat/transformation.py:206)  
   `get_models()` returns nothing, and `model_prices_and_context_window.json` contains no ClinePass entries. Existing DeepSeek entries do not substitute: `_check_provider_match` rejects them when the requested provider is `clinepass`. Consequently, provider-specific model information and built-in cost calculation cannot resolve the tested model. Add verified ClinePass model entries with capabilities, limits, and its actual pricing semantics

5. **[P2] The new tests miss the current provider CI shard** — [test_clinepass_transformation.py:1](/Users/djbclark/src/litellm-clinepass-upstream/tests/test_litellm/llms/clinepass/chat/test_clinepass_transformation.py:1)  
   `.circleci/scripts/unit_selection.sh:62`, also consumed by GitHub Actions, selects provider tests exclusively from `tests/unit/llms`. Move this file to `tests/unit/llms/clinepass/chat/test_clinepass_transformation.py`, following the current mirrored layout

6. **[P2] The implementation retains typing conventions rejected by current lint rules** — [transformation.py:18](/Users/djbclark/src/litellm-clinepass-upstream/litellm/llms/clinepass/chat/transformation.py:18)  
   `List`, `Tuple`, `Optional`, and `Union` conflict with enabled UP006/UP007/UP035/UP045 rules. The new code also adds explicit `Any`, unparameterized dictionaries, and assignments without `Final`. Replace legacy aliases, use the existing logging/tokenizer types as current CometAPI and Perplexity transformations do, and type the new helpers without expanding lint budgets

7. **[P2] The credential registration does not reach the saved-credential selector** — [provider_create_fields.json:833](/Users/djbclark/src/litellm-clinepass-upstream/litellm/proxy/public_endpoints/provider_create_fields.json:833)  
   `CredentialModal.tsx:23` builds its options from the frontend `Providers` enum, which lacks ClinePass. Adding backend metadata alone leaves ClinePass unavailable there. Add `CLINEPASS` to `Providers` and `provider_map` in `provider_info_helpers.tsx`, and verify selecting it renders and submits the API-key field

8. **[P2] Provider listing and setup documentation are incomplete** — [provider_endpoints_support.json:551](/Users/djbclark/src/litellm-clinepass-upstream/provider_endpoints_support.json:551)  
   The change advertises a documentation URL but supplies no setup documentation, and ClinePass is absent from the README provider table. Add the README row and a companion page in [BerriAI/litellm-docs](https://github.com/BerriAI/litellm-docs), covering credentials, proxy configuration, supported endpoints, and the distinction between `clinepass/` routing and `cline-pass/` outbound namespaces

9. **[P2] Streaming, usage, and authentication behavior remain insufficiently tested** — [test_clinepass_transformation.py:245](/Users/djbclark/src/litellm-clinepass-upstream/tests/test_litellm/llms/clinepass/chat/test_clinepass_transformation.py:245)  
   The only streaming test checks concatenated text and provides neither a terminal finish-reason chunk nor usage. There is no async-stream test, tool-call-fragment test, usage-preservation assertion, or outgoing Authorization-header assertion. Add those through injected transports, including explicit-key precedence and 429 handling. Replace the registry-membership and `__dict__` assertions at lines 88 and 478 with public behavior checks

NEEDS WORK
codex exit=0

## agy findings (5; verdict NEEDS WORK)

Here is a review of the ClinePass provider addition, prioritized by importance:

1. **COMPLETENESS: Missing Model Pricing & Documentation**
   - **Files:** `model_prices_and_context_window.json`, `docs/my-website/docs/providers/clinepass.md`
   - **Finding:** The PR modifies `provider_endpoints_support.json` to point to `https://docs.litellm.ai/docs/providers/clinepass`, but no such markdown file exists in the PR. Additionally, `model_prices_and_context_window.json` was entirely untouched. Without catalog entries for `cline-pass/*` models, crucial LiteLLM features like token cost tracking, spend calculations, and context window limit enforcement will fail silently or fallback to defaults.
   - **Fix:** Add a documentation file to `docs/` and add the respective models to `model_prices_and_context_window.json`.

2. **CORRECTNESS / OBSERVABILITY: Unicode Mangling in Raw Response Logging**
   - **File:** `litellm/llms/clinepass/chat/transformation.py:114`
   - **Finding:** In `_unwrap_response_envelope`, the rebuilt payload uses `content=json.dumps(inner).encode("utf-8")`. Because Python's `json.dumps()` defaults to `ensure_ascii=True`, any non-ASCII characters (like emojis or Chinese characters) are converted into `\uXXXX` escape sequences. `OpenAIGPTConfig.transform_response` passes `raw_response.text` directly to `logging.post_call`. This means downstream observability tools (Langfuse, DataDog, etc.) will receive permanently mangled, double-escaped strings instead of the original unicode text. 
   - **Fix:** Change it to `content=json.dumps(inner, ensure_ascii=False).encode("utf-8")`.

3. **TEST QUALITY: Untested Dead Code in Envelope Unwrapping**
   - **File:** `litellm/llms/clinepass/chat/transformation.py:96` 
   - **Finding:** The `except (ValueError, httpx.StreamError):` block tries to catch `httpx.StreamError` specifically to pass streaming responses through unchanged. However, this is dead code and untested. LiteLLM's `base_llm_http_handler.completion` purposefully bypasses `transform_response()` altogether when `stream=True` (delegating directly to `get_model_response_iterator()`). Thus, a streaming `httpx.Response` is never handed to `_unwrap_response_envelope()`.
   - **Fix:** Remove `httpx.StreamError` from the catch block; it is unreachable.

4. **TEST QUALITY: Untested Dead Code in Truncation Fallback**
   - **File:** `litellm/llms/clinepass/chat/transformation.py:73`
   - **Finding:** In `_correct_truncated_finish_reason`, there is a fallback: `if max_tokens is None: max_tokens = _as_positive_number(request_data.get("max_completion_tokens"))`. This branch is unreachable. `request_data` holds the API payload *after* `map_openai_params()` has run. Because the provider explicitly pops `"max_completion_tokens"` and replaces it with `"max_tokens"` in its mapping, the key `"max_completion_tokens"` will never exist in `request_data`. `test_max_completion_tokens_also_detects_truncation` passes only because it successfully hits the standard `max_tokens` variable instead.
   - **Fix:** Remove the redundant fallback branch for `max_completion_tokens`.

5. **CONVENTION DRIFT: Legacy Client Dispatch in `main.py`**
   - **File:** `litellm/main.py:2452`
   - **Finding:** In `_complete_clinepass`, local context attributes are destructured without `Final` type hints (e.g., `api_key = ctx.api_key`), and the HTTP client is assigned directly via `client = ctx.client`. Modern `_complete_*` blocks (like `cometapi`, `minimax`, `hosted_vllm`) explicitly use `Final` type annotations and route through the dispatcher function: `client: Final = _dispatch_client_http(ctx)`. While functionally identical right now (as the dispatcher just returns `ctx.client`), this drifts from current upstream conventions.
   - **Fix:** Annotate the destructured variables with `: Final` and use `_dispatch_client_http(ctx)` to retrieve the client.

NEEDS WORK

## Overlap worth noting

Both reviewers independently flagged the missing
`model_prices_and_context_window.json` entries and the missing provider
documentation, and both flagged the duplicate `logging_obj.post_call`
(agy via the UI/convention angle, codex as its P2 #3). Treat those three as
confirmed rather than one-reviewer opinions.
