# Batch processing across the five providers

Checked against vendor documentation on 21 September 2026, and against the live
APIs on 23 September 2026 once keys were in hand. Where the two disagreed, the
live API won — see the xAI row. Re-check before the paid run.

## Summary table

| Provider | 1. Batch via API/SDK | 2. Delete batch + files after upload | 3. Continue if credits run out |
|---|---|---|---|
| **OpenAI** | **Yes.** Upload JSONL via Files API (`purpose="batch"`), then `POST /v1/batches`. Only a `24h` window. Max 50,000 requests / 200 MB per batch; 2,000 batch creations per hour. Map results by `custom_id` — output line order is not input order. 50% discount. [1] | **Files yes, batch object no.** `DELETE /v1/files/{file_id}` removes input, output and error files. Batch endpoints are create / retrieve / list / cancel only — there is no delete. Output files auto-delete 30 days after completion. [1][2][3] | **Not documented.** In practice exhaustion returns `429` with `error.type: insufficient_quota`; OpenAI's own guidance is that retrying a billing or quota error does not restore access — fix billing first. Treat as fatal, not retryable. [4] |
| **Anthropic** | **Yes.** Message Batches API — requests inline with `custom_id`, no file upload. Max 100,000 requests or 256 MB. Most finish in under an hour; results readable when all complete or at 24h; batches expire at 24h. 50% discount. [5] | **Yes, cleanest of the five.** `DELETE /v1/messages/batches/{batch_id}` any time after processing; cancel first to delete an in-progress batch. No input files to clean up. Results retained 29 days from `created_at`. [5] | **Documented error codes.** `400 invalid_request_error` when an org or workspace spend limit is hit, `402 billing_error` for payment problems, `429 rate_limit_error` at a tier spend cap (no `retry-after`, keeps failing until access resumes). Note: batches can go slightly over a configured spend limit. [5][6] |
| **Google Gemini** | **Yes.** Batch Mode: inline requests (max 20 MB) or an input JSONL via the Files API (max 2 GB). Target turnaround 24h; jobs expire after 48h pending or running. 50% discount. Webhooks (`batch.succeeded`, `batch.failed`) instead of polling. [7][8] | **Yes, both.** `batches.delete` (`DELETE /v1beta/{name=batches/*}`) removes the job; `batches.cancel` stops it. Uploaded files are separate, via `files.delete`; the Files API auto-deletes after 48h (20 GB per project). Results downloadable for 6 weeks, then permanently deleted. [7][8][9] | **Not documented.** Quota or credit exhaustion surfaces as `429 RESOURCE_EXHAUSTED`, reported by users even on paid tiers. Same handling as OpenAI: stop, fix billing, resume from saved ids. [10] |
| **xAI** | **Yes, but not for any current model — and not in OpenAI's dialect.** Verified against the live API on 2026-09-23, not just the docs. `POST /v1/batches` takes **only** `{"name": ...}` — there is no `input_file_id`, so the OpenAI file-upload flow does not apply. Requests are then added with `POST /v1/batches/{id}/requests`, body `{"batch_requests": [{"batch_request_id": ..., "batch_request": {"chat_get_completion": {...}}}]}`; the accepted variants are `chat_get_completion`, `responses`, `image_generation`, `image_edit`. Paginated `GET /v1/batches/{id}/results`. **`grok-4.5`, `grok-4.6` and `grok-4.7` are all rejected with "Model X is not supported for batch processing"**; only `grok-4.3` and the `grok-4.20-*` line are accepted. [11][12] | **No delete.** Endpoints are create, list, get, list/add requests, results, and `:cancel` — no DELETE for a batch, its requests, or its results. Results become inaccessible after `expire_time`, observed to be 30 days after creation. Image and video result URLs expire after 1 hour. [11][12] | **Not documented.** A separate Management API (`https://management-api.x.ai`, management-scoped keys) covers API keys, teams and billing, so a pre-flight credit check is possible — but nothing documents mid-run resumption. [13] |
| **Meta** | **No batch API — and the plan's assumption is out of date.** The Llama API wound down on **6 July 2026**; its deprecation page now redirects into Meta's new platform. The current product is the **Meta Model API** (`https://api.meta.ai/v1`, public preview, bearer `MODEL_API_KEY`, drop-in compatible with the OpenAI *and* Anthropic SDKs), serving the **Muse** family — `muse-spark-1.3` / `1.2` / `1.1`, Muse Image, Muse Voice Transcribe, and Muse Glimmer (open weights). Its API reference lists responses, chat completions, messages, files, models, status. **No `/v1/batches`.** [14][15][16] | **Files yes, no batch to delete.** `DELETE /v1/files/{file_id}` exists. [16] | **Not documented.** Pay-as-you-go; the reference says nothing about credits or spend limits. [15] |

## What this means for the study

**1. "Meta = Llama" no longer holds, and it is a design decision, not a detail.**
The Meta row can be either *Muse Spark via the Meta Model API* (a proprietary
Meta model, direct from the vendor, no batch) or *a Llama open-weight model
served by a third party or locally* (still Llama, but the serving stack is no
longer Meta's). Those support different claims in a write-up. This needs
Dr. Aryal's call before any run.

**2. Three of five can actually be batched, in three incompatible dialects.**
Corrected 2026-09-23 after running against the live APIs: OpenAI and xAI do
**not** share a dialect. OpenAI uploads a file and references it; xAI creates a
named batch and posts requests into it under a `chat_get_completion` variant.
And xAI's batch endpoint refuses every current Grok, so the flagship has to run
live regardless. That leaves OpenAI, Anthropic and Google on batch — one script
each — with xAI and Meta on the sequential script.

**3. Read the docs, then try them.** Every error above was found by calling the
API, not by reading. The docs describe an xAI file-upload flow that the API
rejects, and say nothing about which models batch. Budget an hour of probing per
provider before trusting a dialect.

**4. The grid is the cost, not the transport.**
At the law school's 17 identities plus a control: 400 prompts x 2 polarities x
18 x 5 providers x 3 runs = **216,000 generation calls**, and as many judge
calls. Batch halves the token price on the three providers that support it,
which matters, but the multiplier that actually decides the bill is the identity
count. Trim that before trimming anything else.

**5. "Continue if credits run out" is not a provider feature anywhere.**
No provider documents resuming a run after a billing stop. The property that
actually saves the run is ours: a stable id per cell, appended to disk as each
answer arrives, and a rerun that skips ids already present. `sequential.py`
treats billing and quota errors as fatal — it stops rather than burning retries
on an error that retrying cannot fix — and the same command resumes the run once
billing is sorted. The batch scripts need no such handling: a failed request
comes back in the results and is resubmitted on the next pass.

## Sources

1. OpenAI, Batch API guide — https://developers.openai.com/api/docs/guides/batch
2. OpenAI, Files delete — https://developers.openai.com/api/docs/api-reference/files/delete
3. OpenAI, Batch API reference — https://developers.openai.com/api/docs/api-reference/batch
4. OpenAI Help Center, 429 and `insufficient_quota` — https://help.openai.com/en/articles/5955604-how-can-i-solve-429-too-many-requests-errors
5. Anthropic, Batch processing — https://platform.claude.com/docs/en/build-with-claude/batch-processing
6. Anthropic, API errors — https://platform.claude.com/docs/en/api/errors
7. Google, Gemini Batch Mode — https://ai.google.dev/gemini-api/docs/batch-api
8. Google, Batch Mode API reference — https://ai.google.dev/api/batch-mode
9. Google, Files API — https://ai.google.dev/gemini-api/docs/files
10. Google AI Developers Forum, batch quota reports — https://discuss.ai.google.dev/t/i-am-trying-to-use-the-batch-api-despite-having-credits-in-account-i-get-quota-exhuasted/114376
11. xAI, Batch API guide — https://docs.x.ai/developers/advanced-api-usage/batch-api
12. xAI, Batches REST reference — https://docs.x.ai/developers/rest-api-reference/inference/batches
13. xAI, API reference overview (Management API) — https://docs.x.ai/developers/api-reference
14. Meta, Llama API deprecation notice (redirects to the new platform) — https://llama.developer.meta.com/docs/llama-api-deprecation/
15. Meta, Meta Model API docs — https://ai.developer.meta.com/docs/
16. Meta, Meta Model API reference — https://dev.meta.ai/docs/api-reference
