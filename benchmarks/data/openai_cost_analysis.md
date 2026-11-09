# OpenAI cost analysis

Token counts measured with tiktoken (`o200k_base`) over the real corpora — the 200-listing validation set and the filter-benchmark prompt set. Prices are the 2026-09-06 snapshot in `benchmarks/llm/cost_estimates.py`; re-check before committing spend.

## 1. Offline backfill of the active dataset

Two calls per listing (enrichment + canonical fill), matching how the benchmark actually ran.

| task | static input (prompt+schema) | mean listing text | mean input | mean output |
|---|---:|---:|---:|---:|
| enrichment | 510 | 219 | 729 | 38 |
| canonical | 646 | 219 | 865 | 35 |
| **per listing (both)** | | | **1593** | **73** |

Both prompts sit under the 1024-token cache minimum, so no cached-input discount applies. Batch API (50% of standard) does — the backfill is offline by definition.

| model | 10,000 listings | 12,500 listings | 15,000 listings | batch (12,500) |
|---|---:|---:|---:|---:|
| gpt-5-nano | $1.09 | $1.36 | $1.64 | $0.68 |
| gpt-5-mini | $5.45 | $6.81 | $8.18 | $3.41 |
| gpt-5 | $27.25 | $34.06 | $40.88 | $17.03 |
| gpt-4.1-mini | $7.55 | $9.43 | $11.32 | $4.72 |
| gpt-5.6-luna | $4.07 | $5.08 | $6.10 | $2.54 |

## 2. Per user prompt (interactive text-to-SQL)

One call per search. Mean input 1367 tokens (1351 of them the fixed system prompt + schema, 16 the user's own words), mean output 86 tokens, measured over 18 real sample prompts.

This prompt *does* clear the 1024-token cache minimum, so the cached column below assumes the fixed prefix is served from cache — true only under sustained traffic, since the cache expires after minutes of inactivity. Batch pricing does not apply: the user is waiting.

| model | per search | per 1k searches | 1,000/mo | 10,000/mo | 100,000/mo | per 1k (cached prefix) |
|---|---:|---:|---:|---:|---:|---:|
| gpt-5-nano | $0.000103 | $0.10 | $0.10 | $1.03 | $10.27 | $0.04 |
| gpt-5-mini | $0.000513 | $0.51 | $0.51 | $5.13 | $51.35 | $0.21 |
| gpt-5 | $0.002567 | $2.57 | $2.57 | $25.67 | $256.74 | $1.05 |
| gpt-4.1-mini | $0.000684 | $0.68 | $0.68 | $6.84 | $68.42 | $0.28 |
| gpt-5.6-luna | $0.000376 | $0.38 | $0.38 | $3.76 | $37.64 | $0.13 |
