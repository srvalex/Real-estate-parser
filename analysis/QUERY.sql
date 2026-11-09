-- analysis/QUERY.sql
-- ─────────────────
-- Source pull for the 1-room vs 2-room analysis.
--
-- Run in the Supabase SQL editor with **"No limit"** selected (the default
-- 100-row cap would silently truncate this), then Download CSV and feed it
-- to the normaliser:
--
--     venv/bin/python analysis/fetch_cache.py --from-csv ~/Downloads/<file>.csv
--
-- Deliberately raw: no CASE, no currency conversion, no filtering beyond the
-- date. Every derived field (price_eur, rooms_norm, property_type_norm,
-- sector, price_per_sqm) is computed in analysis/fetch_cache.py, so the
-- reclassification rules live in one place and can be changed without
-- re-exporting.
--
-- ORDER BY url is not cosmetic: it is what makes the result set stable.
-- `url` is the table's PRIMARY KEY, so it is a total order.

select
  url,
  is_available,
  city,
  district,
  property_type,
  rooms,
  price_numeric,
  price_currency,
  area_sqm,
  platform_id,
  first_seen_at,
  features
from listings
where first_seen_at >= '2026-08-01'
order by url;
