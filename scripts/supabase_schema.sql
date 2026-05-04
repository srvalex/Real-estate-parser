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

-- 5. Text similarity search function (used in P2.3 to replace ChromaDB web_archive)
CREATE OR REPLACE FUNCTION match_listings(
    query_embedding vector(384),
    match_count     INT     DEFAULT 50,
    min_available   INT     DEFAULT 1
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
    ORDER BY l.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- 6. Image similarity search function (512-dim CLIP cover photo embeddings)
CREATE OR REPLACE FUNCTION match_listings_by_image(
    query_embedding vector(512),
    match_count     INT DEFAULT 50
)
RETURNS TABLE (url TEXT, similarity FLOAT)
LANGUAGE sql STABLE AS $$
    SELECT url, 1 - (image_embedding <=> query_embedding) AS similarity
    FROM listings
    WHERE image_embedding IS NOT NULL
      AND is_available = 1
    ORDER BY image_embedding <=> query_embedding
    LIMIT match_count;
$$;
