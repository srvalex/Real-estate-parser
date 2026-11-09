# Description enrichment benchmark

| Model | Accuracy | Median latency | p95 latency | Avg tokens in/out | Errors | Est. hosted cost / 1k calls |
|---|---|---|---|---|---|---|
| qwen3:14b | 95.9% | 7.54s | 13.21s | 892 / 35 | 0/200 | $0.33 |
| phi4:14b | 95.9% | 7.96s | 11.86s | 883 / 38 | 0/200 | n/a |

## Per-field accuracy

**qwen3:14b**
- own_heating: 93.5%
- parking_available: 97.5%
- pets_allowed: 99.0%
- renovation_status: 93.5%

**phi4:14b**
- own_heating: 93.5%
- parking_available: 96.0%
- pets_allowed: 99.5%
- renovation_status: 94.5%
