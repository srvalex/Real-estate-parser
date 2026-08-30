-- ============================================================
-- Supabase schema for Romanian Real Estate Parser
-- Run this once in the Supabase SQL Editor before migrating.
-- ============================================================

-- 1. Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Main listings table (canonical, normalised schema)
CREATE TABLE IF NOT EXISTS listings (

    -- Identity
    url             TEXT        PRIMARY KEY,
    platform_id     TEXT        NOT NULL,   -- 'olx' | 'storia' | 'imobiliare'
    platform        TEXT,                   -- display name
    source_id       TEXT,                   -- platform's own listing ID

    -- Core listing data
    title           TEXT,
    description     TEXT,

    -- Price  (raw string kept for display; numeric for filtering)
    price_eur       TEXT,                   -- original string e.g. "1 200 EUR/lună"
    price_numeric   FLOAT,                  -- parsed amount e.g. 1200.0
    price_currency  TEXT,                   -- 'EUR' | 'RON'

    -- Location
    district        TEXT,                   -- neighbourhood name
    location_full   TEXT,                   -- full location path

    -- Physical characteristics (normalised across all platforms)
    rooms           TEXT,                   -- '1' | '2' | '3' | '4' | '5+'
    area_sqm        FLOAT,                  -- parsed m²
    floor           TEXT,
    total_floors    TEXT,
    year_built      TEXT,
    heating         TEXT,

    -- Other
    features        TEXT,                   -- raw features string
    image_urls      JSONB,                  -- [{thumbnail,small,medium,large}, ...]
    extras          JSONB,                  -- platform-specific fields (Storia details etc.)

    -- Availability  1=live  0=expired  -1=blocked/transient
    is_available    INTEGER     DEFAULT 1,

    -- Timestamps
    scraped_at      TIMESTAMPTZ,
    first_seen_at   TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ DEFAULT NOW(),

    -- pgvector text embedding (384-dim, paraphrase-multilingual-MiniLM-L12-v2)
    -- NULL until P2.3 embedding backfill runs.
    embedding       vector(384)
);

-- 3. Indexes
CREATE INDEX IF NOT EXISTS idx_listings_district    ON listings (district);
CREATE INDEX IF NOT EXISTS idx_listings_available   ON listings (is_available);
CREATE INDEX IF NOT EXISTS idx_listings_platform    ON listings (platform_id);
CREATE INDEX IF NOT EXISTS idx_listings_price       ON listings (price_numeric);
CREATE INDEX IF NOT EXISTS idx_listings_rooms       ON listings (rooms);
CREATE INDEX IF NOT EXISTS idx_listings_scraped     ON listings (scraped_at DESC);

-- 4. IVFFlat vector index — run separately AFTER migration when row count is known.
--    Rule of thumb: lists ≈ sqrt(row_count).  E.g. for 10 000 rows use 100.
--
-- CREATE INDEX idx_listings_embedding
--     ON listings USING ivfflat (embedding vector_cosine_ops)
--     WITH (lists = 100);

-- 4b. Cover photo CLIP embedding (512-dim, openai/clip-vit-base-patch32)
--     Populated by the post-crawl backfill step in crawler.py.
ALTER TABLE listings ADD COLUMN IF NOT EXISTS image_embedding vector(512);

-- IVFFlat index — run after backfill completes.
-- CREATE INDEX idx_listings_image_embedding
--     ON listings USING ivfflat (image_embedding vector_cosine_ops)
--     WITH (lists = 100);

-- 4c. Multi-city support (GEO_EXPANSION_PLAN.md Phase 0). No column DEFAULT
--     on purpose — every writer (crawler.py's _scrape_and_save) must set
--     city explicitly per search URL rather than relying on an implicit
--     fallback. Existing rows are backfilled once, explicitly, below (all
--     pre-existing rows are Bucharest, since second-city crawling starts now).
ALTER TABLE listings ADD COLUMN IF NOT EXISTS city TEXT;
UPDATE listings SET city = 'Bucuresti' WHERE city IS NULL;
CREATE INDEX IF NOT EXISTS idx_listings_city_district ON listings (city, district);

-- 5. Text similarity search function (used in P2.3 to replace ChromaDB web_archive)
--
--    candidate_urls (added later): when given, scores EVERY url in that
--    list, ignoring match_count entirely (LIMIT NULL = unlimited). Without
--    it, the query only ever sees the global top-`match_count` nearest
--    neighbours across the whole table — a listing outside that cutoff
--    silently gets no score at all, even if it's the best match within a
--    caller's already-filtered candidate set (e.g. one district). That
--    silent-miss risk grows with table size, not with anything the caller
--    did wrong. The app always passes its already-filtered candidate URLs
--    now (see db_utils.search_by_text_vibe / apply_ai_scores); the
--    unscoped, match_count-limited mode is kept only for callers with no
--    pre-filtered candidate set to scope to.
CREATE OR REPLACE FUNCTION match_listings(
    query_embedding vector(384),
    match_count     INT     DEFAULT 50,
    min_available   INT     DEFAULT 1,
    candidate_urls  TEXT[]  DEFAULT NULL
)
RETURNS TABLE (
    url             TEXT,
    title           TEXT,
    price_eur       TEXT,
    price_numeric   FLOAT,
    district        TEXT,
    rooms           TEXT,
    area_sqm        FLOAT,
    description     TEXT,
    image_urls      JSONB,
    is_available    INTEGER,
    similarity      FLOAT
)
LANGUAGE plpgsql AS $$
BEGIN
    RETURN QUERY
    SELECT
        l.url, l.title, l.price_eur, l.price_numeric,
        l.district, l.rooms, l.area_sqm, l.description,
        l.image_urls, l.is_available,
        1 - (l.embedding <=> query_embedding) AS similarity
    FROM listings l
    WHERE l.embedding IS NOT NULL
      AND l.is_available >= min_available
      AND (candidate_urls IS NULL OR l.url = ANY(candidate_urls))
    ORDER BY l.embedding <=> query_embedding
    LIMIT (CASE WHEN candidate_urls IS NULL THEN match_count ELSE NULL END);
END;
$$;

-- 6. Rooms autofill trigger — OLX and Storia listings only
--    Fires BEFORE INSERT OR UPDATE; fills rooms from title/description when
--    the scraper couldn't extract it. Never overwrites an existing value.
--    Run the matching UPDATE below once to backfill historical rows.
--
--    Fixed 2026-08-23 — two bugs found via a live data audit:
--      1. The '5 cam' branches set the literal string '5', not '5+' like
--         the Python-side normalisation (db_utils._clean_record) uses for
--         any room count >= 5. Two independently-maintained copies of the
--         same "guess rooms from text" logic had drifted — get_price_stats()
--         buckets by (district, rooms) as an exact-match tuple, so a '5'
--         room listing and a '5+' one in the same district silently split
--         into two buckets instead of combining, diluting both.
--      2. The DESCRIPTION-based raw-digit branches ('%2 cam%' .. '%5 cam%')
--         are unsafe: Romanian listings commonly describe window glazing
--         quality as "geam cu N camere" (an N-chamber window profile — a
--         real, common industry spec, nothing to do with room count).
--         Confirmed live: an actual Studio listing's rooms got set to '5'
--         because its description said "geam tripan cu 5 camere de
--         izolare fonică" (a 5-chamber soundproof window). TITLE-based
--         digit matching is kept (titles are short marketing headlines —
--         no listing titles a window spec) — only the description-based
--         *digit* branches are removed. The Romanian-number-WORD branches
--         (doua/două/trei/patru cam) are kept and given a 'cinci' sibling
--         for symmetry — nobody spells out a window's chamber count in
--         words, so that class of false positive doesn't apply there.
CREATE OR REPLACE FUNCTION autofill_rooms()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.platform_id IN ('olx', 'storia') AND NEW.rooms IS NULL THEN
        NEW.rooms := CASE
            WHEN NEW.property_type = 'Garsoniera'                       THEN '1'
            WHEN lower(NEW.title)       LIKE '%2 cam%'                  THEN '2'
            WHEN lower(NEW.title)       LIKE '%3 cam%'                  THEN '3'
            WHEN lower(NEW.title)       LIKE '%4 cam%'                  THEN '4'
            WHEN lower(NEW.title)       LIKE '%5 cam%'                  THEN '5+'
            WHEN lower(trim(NEW.description)) LIKE '%doua cam%'         THEN '2'
            WHEN lower(trim(NEW.description)) LIKE '%două cam%'         THEN '2'
            WHEN lower(trim(NEW.description)) LIKE '%trei cam%'         THEN '3'
            WHEN lower(trim(NEW.description)) LIKE '%patru cam%'        THEN '4'
            WHEN lower(trim(NEW.description)) LIKE '%cinci cam%'        THEN '5+'
            ELSE NULL
        END;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_autofill_rooms
BEFORE INSERT OR UPDATE ON listings
FOR EACH ROW EXECUTE FUNCTION autofill_rooms();

-- One-time backfill for existing rows with rooms IS NULL (matches the
-- trigger logic above — description-based raw-digit branches intentionally
-- excluded, same reasoning as the trigger fix comment):
-- UPDATE listings
-- SET rooms = CASE
--     WHEN property_type = 'Garsoniera'                       THEN '1'
--     WHEN lower(title)       LIKE '%2 cam%'                  THEN '2'
--     WHEN lower(title)       LIKE '%3 cam%'                  THEN '3'
--     WHEN lower(title)       LIKE '%4 cam%'                  THEN '4'
--     WHEN lower(title)       LIKE '%5 cam%'                  THEN '5+'
--     WHEN lower(trim(description)) LIKE '%doua cam%'         THEN '2'
--     WHEN lower(trim(description)) LIKE '%două cam%'         THEN '2'
--     WHEN lower(trim(description)) LIKE '%trei cam%'         THEN '3'
--     WHEN lower(trim(description)) LIKE '%patru cam%'        THEN '4'
--     WHEN lower(trim(description)) LIKE '%cinci cam%'        THEN '5+'
--     ELSE NULL END
-- WHERE platform_id IN ('olx', 'storia') AND rooms IS NULL;

-- Historical rows already mis-set by the OLD trigger (rooms = '5') were
-- corrected by hand, not by a blanket UPDATE: most were genuinely 5-room
-- listings (title/description explicitly says so) and just needed
-- reformatting to '5+', but at least one was a false positive from the
-- exact bug this fix addresses (a Studio whose rooms got set to '5' from
-- a window-glazing spec, not an actual room count) and was reverted to
-- NULL instead — a blanket `WHERE rooms = '5'` UPDATE can't tell those
-- two cases apart without reading each description, so don't run one.


-- 7. Image similarity search function (512-dim CLIP cover photo embeddings)
--    candidate_urls: same purpose as on match_listings above — scope to an
--    exact candidate set instead of hoping it survives a global top-K cut.
CREATE OR REPLACE FUNCTION match_listings_by_image(
    query_embedding vector(512),
    match_count     INT     DEFAULT 50,
    candidate_urls  TEXT[]  DEFAULT NULL
)
RETURNS TABLE (url TEXT, similarity FLOAT)
LANGUAGE sql STABLE AS $$
    SELECT url, 1 - (image_embedding <=> query_embedding) AS similarity
    FROM listings
    WHERE image_embedding IS NOT NULL
      AND is_available = 1
      AND (candidate_urls IS NULL OR url = ANY(candidate_urls))
    ORDER BY image_embedding <=> query_embedding
    LIMIT (CASE WHEN candidate_urls IS NULL THEN match_count ELSE NULL END);
$$;

-- ============================================================
-- 8. Row Level Security — restrict the anon (public, Streamlit-facing) key
--    to read-only access on available listings.
--
--    Run this ONCE. Then, in the Streamlit deployment's env/secrets:
--      - set SUPABASE_ANON_KEY to the "anon / public" key
--        (Supabase dashboard -> Settings -> API)
--      - remove SUPABASE_KEY (service_role) entirely from that environment
--
--    The crawler / embedder-job keep using SUPABASE_KEY (service_role),
--    which bypasses RLS — this only constrains the anon key. See db_utils.py
--    (get_client() vs get_anon_client()) for which functions use which.
--
--    Before this: every Streamlit-facing read used the service_role key,
--    so a leaked Streamlit env var would have handed out full read/write/
--    delete on the whole table. The anon key is meant to be public — a
--    website's own JS bundle typically ships it — safety comes entirely
--    from the RLS policy below, not from keeping the key secret.
-- ============================================================

ALTER TABLE listings ENABLE ROW LEVEL SECURITY;

-- Baseline table-level privilege (RLS then filters which rows are visible).
GRANT SELECT ON listings TO anon;

-- Explicit belt-and-suspenders: RLS default-denies without a permissive
-- policy for a given command, but revoke these outright so the anon role
-- cannot write or delete regardless of any future policy added by mistake.
REVOKE INSERT, UPDATE, DELETE ON listings FROM anon;

-- anon may only SELECT rows that are actually live — matches every current
-- app-level filter (query_listings_by_district, fetch_analytics_data,
-- match_listings, match_listings_by_image all already filter to
-- is_available = 1; this makes it impossible to bypass that filter even
-- with direct table access via the anon key).
CREATE POLICY "anon can read available listings"
    ON listings
    FOR SELECT
    TO anon
    USING (is_available = 1);

-- match_listings / match_listings_by_image run as SECURITY INVOKER (the
-- default for a function with no SECURITY DEFINER clause) — they execute
-- with the CALLING role's own privileges, so the SELECT policy above
-- applies inside them too. Grant EXECUTE explicitly so anon can call them:
GRANT EXECUTE ON FUNCTION match_listings(vector(384), int, int, text[]) TO anon;
GRANT EXECUTE ON FUNCTION match_listings_by_image(vector(512), int, text[]) TO anon;

-- ============================================================
-- 9. Observability tables — crawl runs, availability checks, user searches.
--
--    All three are backend-only: written exclusively via the service-role
--    client (db_utils.get_client()), never get_anon_client(). RLS is
--    enabled with NO permissive policy for anon on any of them — default
--    deny for every role except service_role, which bypasses RLS
--    entirely. There is no reason for the anon key to ever read or write
--    these, so unlike `listings` there's no SELECT grant to add.
-- ============================================================

-- 9a. Crawl run logs — one row per crawler.py full/incremental invocation.
CREATE TABLE IF NOT EXISTS crawl_run_logs (
    id              BIGSERIAL   PRIMARY KEY,
    mode            TEXT        NOT NULL,   -- 'full' | 'incremental'
    platforms       JSONB       NOT NULL,   -- e.g. ["olx", "storia"]
    max_price       INT,
    max_pages       INT,
    stop_threshold  FLOAT,                  -- incremental only, NULL for full
    proxy_display   TEXT,                   -- host:port only — never log credentials
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    listings_new    INT,
    status          TEXT        NOT NULL DEFAULT 'running',  -- 'running' | 'success' | 'failed'
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_crawl_run_logs_started ON crawl_run_logs (started_at DESC);
CREATE INDEX IF NOT EXISTS idx_crawl_run_logs_status  ON crawl_run_logs (status);

ALTER TABLE crawl_run_logs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON crawl_run_logs FROM anon;

-- 9b. Availability check logs — one row per crawler.py --mode availability-check invocation.
CREATE TABLE IF NOT EXISTS availability_check_logs (
    id                BIGSERIAL   PRIMARY KEY,
    platforms         JSONB,                -- NULL/empty = all platforms
    started_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at       TIMESTAMPTZ,
    listings_checked  INT,
    listings_expired  INT,                  -- newly marked expired this run
    listings_blocked  INT,                  -- skipped due to block/transient error
    status            TEXT        NOT NULL DEFAULT 'running',
    error_message     TEXT
);

CREATE INDEX IF NOT EXISTS idx_availability_check_logs_started ON availability_check_logs (started_at DESC);

ALTER TABLE availability_check_logs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON availability_check_logs FROM anon;

-- 9c. User searches — one row per search request against the future API
--     (MIGRATION_PLAN.md Phase 1+). Not written yet — Streamlit form
--     submissions are in-process function calls, not HTTP requests, so
--     there's nothing to log until the API exists. Schema is ready now so
--     Phase 1 just calls db_utils.log_user_search() instead of designing
--     this under time pressure later.
--
--     form_fields captures BOTH the value and where it came from per
--     field — {"rooms": {"value": "2", "source": "nlp"}, "max_price":
--     {"value": null, "source": "unset"}, ...} — source is one of
--     'user' | 'nlp' | 'unset'. That per-field source is what makes this
--     table useful for catching NLP mistakes: query for source='nlp' rows
--     and cross-check the resolved value against vibe_text.
CREATE TABLE IF NOT EXISTS user_searches (
    id                BIGSERIAL   PRIMARY KEY,
    session_id        TEXT        NOT NULL,  -- groups searches within one browsing session
    visitor_id        TEXT        NOT NULL,  -- persists across sessions (anonymous, client-generated)
    searched_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Raw wire-level capture of what was actually sent to the API.
    http_method       TEXT        NOT NULL,
    http_path         TEXT        NOT NULL,
    http_query        TEXT,                  -- raw query string (GET)
    http_body         JSONB,                 -- raw JSON body (POST), if used instead

    -- Resolved/interpreted form state — see column comment above.
    form_fields       JSONB       NOT NULL,
    vibe_text         TEXT,                  -- kept separate: the raw input NLP/agent worked from

    -- What came back.
    results_count     INT         NOT NULL,
    returned_listings JSONB,                 -- [{"url": "...", "score": 0.83, "rank": 1}, ...]
    embedding_sorted  BOOLEAN,
    error_message     TEXT
);

CREATE INDEX IF NOT EXISTS idx_user_searches_searched_at ON user_searches (searched_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_searches_visitor     ON user_searches (visitor_id);
CREATE INDEX IF NOT EXISTS idx_user_searches_session     ON user_searches (session_id);

ALTER TABLE user_searches ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON user_searches FROM anon;

-- 9d. User events — minimal generic traffic tracking for the alpha release
--     (Roadmap.md Month 4.1 / alpha cost-tracking discussion). Deliberately
--     narrow: page views and listing-card clicks only, enough to measure
--     "did anyone show up and use it" during the alpha. Full interaction
--     logging (session duration, template photo selections, preference
--     learning per Roadmap 4.2) stays a later, separate build — not this
--     table's job. Search-specific detail already lives in user_searches
--     (9c); this table is for everything else.
--
--     Written exclusively via db_utils.log_user_event() (service-role),
--     called from a POST /events endpoint — the frontend never holds a
--     Supabase key, same rule as every other write path
--     (MIGRATION_PLAN.md principle #3).
CREATE TABLE IF NOT EXISTS user_events (
    id            BIGSERIAL   PRIMARY KEY,
    event_type    TEXT        NOT NULL,  -- 'page_view' | 'listing_click' (open-ended, not enforced by a CHECK — same convention as crawl_run_logs.status)
    visitor_id    TEXT        NOT NULL,  -- anonymous, client-generated, persists across sessions
    session_id    TEXT,                  -- groups events within one browsing session; nullable, not every event needs it
    occurred_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    path          TEXT,                  -- page path / context, e.g. '/' or a listing URL
    metadata      JSONB                  -- small free-form payload, e.g. {"listing_url": "..."} for a click
);

CREATE INDEX IF NOT EXISTS idx_user_events_occurred_at ON user_events (occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_events_visitor     ON user_events (visitor_id);
CREATE INDEX IF NOT EXISTS idx_user_events_type         ON user_events (event_type);

ALTER TABLE user_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON user_events FROM anon;
