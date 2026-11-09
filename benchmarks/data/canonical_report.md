# Canonical column fill benchmark

| Model | Accuracy | Median latency | p95 latency | Avg tokens in/out | Errors | Est. hosted cost / 1k calls |
|---|---|---|---|---|---|---|
| qwen3:14b | 95.9% | 7.39s | 10.89s | 611 / 43 | 0/200 | $0.25 |
| phi4:14b | 95.8% | 6.90s | 9.94s | 597 / 43 | 0/200 | n/a |

## Per-field accuracy

**qwen3:14b**
- area_sqm: 98.0%
- floor: 96.0%
- rooms: 91.0%
- total_floors: 100.0%
- year_built: 94.5%

**phi4:14b**
- area_sqm: 98.5%
- floor: 95.0%
- rooms: 91.5%
- total_floors: 98.5%
- year_built: 95.5%
