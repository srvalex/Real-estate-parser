# Presentation demo scripts

Static, scripted scenarios for showing the data pipeline live to the committee.
Every script reuses the actual production code (scrapers, `db_utils._clean_record`,
the RRF fusion formula) -- nothing here is faked or simplified.

## 1. Data extraction technique (per platform: OLX, Storia, Imobiliare)

```bash
python demo/scrape_listing.py <listing_url>      # platform auto-detected from the URL
python demo/clean_listing.py <olx|storia|imobiliare>
```

Suggested flow for the committee:
1. Open the original listing page in a browser.
2. Run `scrape_listing.py <url>` -- show `demo/output/raw/<platform>_raw.md` populating
   with the raw, platform-native JSON (exactly what the scraper parsed off the page,
   before any normalisation).
3. Run `clean_listing.py <platform>` -- show `demo/output/cleaned/<platform>_cleaned.md`:
   the same record after `db_utils._clean_record()` (the exact function every listing
   passes through before being upserted into Supabase), with a table of which raw
   fields were renamed into canonical columns, and which were dropped.

Repeat for all three platforms. All three need internet access (live scraping).

## 2. RRF score fusion demo

```bash
python demo/rrf_fusion_demo.py [top_n]     # top_n defaults to 10
```

Loads a hardcoded prompt + its two precomputed query embeddings from
`hardcoded_query_embeddings.json` (query-embedding generation is skipped live,
per the hardware limitations of the presentation machine -- see below for how
that file was produced), then:

1. Queries Supabase pgvector for **text similarity** (`match_listings` RPC,
   paraphrase-multilingual-MiniLM-L12-v2, 384-dim).
2. Queries Supabase pgvector for **image similarity** (`match_listings_by_image`
   RPC, CLIP ViT-B/32, 512-dim).
3. Fuses both ranked lists via Reciprocal Rank Fusion (`rrf.py`, the same
   formula used in `streamlit_interface/pipeline/utils.py::apply_ai_scores()`).

Output: `demo/output/fusion/rrf_demo.md` -- three tables (text-only ranking,
image-only ranking, final fused ranking with each URL's rank in both lists).

### Regenerating `hardcoded_query_embeddings.json`

Only needed if you want to change the demo prompt. Requires `sentence-transformers`
+ `transformers` + `torch` -- if those don't import locally (e.g. the Windows
torch DLL issue hit during development), run it inside a throwaway container
instead, which sidesteps that entirely:

```bash
docker run --rm -v <script_dir>:/work -v "$(pwd)/demo:/output" python:3.11-slim \
  bash -c "pip install --quiet torch --index-url https://download.pytorch.org/whl/cpu && \
           pip install --quiet sentence-transformers transformers && \
           python /work/precompute_standalone.py"
```

(the script itself just encodes the prompt with both models and dumps the two
embedding vectors to JSON -- see git history / ask for a copy if needed.)
