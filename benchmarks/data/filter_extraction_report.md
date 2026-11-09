# Filter extraction benchmark

| Model | Accuracy | Median latency | p95 latency | Avg tokens in/out | Errors | Est. hosted cost / 1k calls |
|---|---|---|---|---|---|---|
| qwen3:4b | 93.8% | 3.55s | 5.34s | 633 / 119 | 2/18 | $0.35 |
| llama3.2:3b | 84.6% | 4.80s | 22.56s | 641 / 216 | 2/18 | $0.08 |

## Per-field accuracy

**qwen3:4b**
- area_max: 100.0%
- area_min: 100.0%
- district: 93.8%
- extras: 62.5%
- floor_max: 100.0%
- floor_min: 100.0%
- is_available: 100.0%
- price_max: 100.0%
- price_min: 100.0%
- property_type: 93.8%
- rooms: 81.2%
- vibe_text: 87.5%
- year_built_min: 100.0%

**llama3.2:3b**
- area_max: 100.0%
- area_min: 100.0%
- district: 81.2%
- extras: 50.0%
- floor_max: 93.8%
- floor_min: 100.0%
- is_available: 100.0%
- price_max: 68.8%
- price_min: 68.8%
- property_type: 87.5%
- rooms: 68.8%
- vibe_text: 81.2%
- year_built_min: 100.0%
