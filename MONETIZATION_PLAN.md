# Monetization Plan: Revenue Model Options

> Companion to `Roadmap.md` (Month 4 — "Monetization Foundation") — this
> document is the idea catalog behind that section: every revenue model
> discussed, with pros/cons, so the reasoning behind the decided model isn't
> lost and the deferred options are ready to revisit rather than
> re-litigated from scratch. Update as new ideas come up or a deferred
> option gets promoted/dropped.

## Why this exists

`Roadmap.md` Month 4 was originally just "data-collection groundwork"
(interaction logging, preference learning, quality scoring) with no actual
revenue mechanism named. This doc is where the *business model* question
gets worked through — what actually makes money, not just what data gets
collected.

## Decided: Credit top-up, gating AI-ranked search

Full mechanics live in `Roadmap.md` §4.0 — summary here for context against
the alternatives below:

- **Unit:** filtered search (district/price/rooms/type — same as OLX's own
  free filters) stays free and unlimited, forever. Only AI-ranked
  (vibe/image) search costs a credit — the one thing competitors don't have.
- **Trial:** new accounts get 1 free AI-ranked search + 3 free filtered
  searches, one time, not renewing.
- **Expiry:** none, or years — not months.
- **Why not subscription:** usage is a short burst (2–8 weeks hunting) then
  zero need until the next move — annual at best for students. A monthly
  subscription gets cancelled the moment a lease is signed, or signup gets
  delayed to dodge paying for unused weeks either way. Full reasoning +
  rejection of subscription is option 2 below.
- **Shared infra need:** requires minimal user accounts (email-only MVP),
  same prerequisite as Price Drop Alerts (Roadmap 3.4) — build once for both.

---

## Options considered

### 1. Credit top-up — **DECIDED**, see above.

### 2. Freemium subscription — rejected

**Pros:**
- Predictable, recurring revenue (MRR) — easier to forecast and raise
  against than one-off purchases.
- Simple to build and explain: one price, one gate.
- Works well for products with continuous, ongoing usage.

**Cons:**
- **Fundamental mismatch with usage pattern.** A renter needs this app for
  2–8 weeks, then not again until their next move — annually at best for
  students. Subscription value only makes sense for continuous use.
- Users cancel the moment they sign a lease → captures ~1 month of revenue
  per user regardless of the subscription price.
- Adverse selection: rational users delay signing up until deep into the
  hunt, to minimize paid weeks with no benefit — works against you exactly
  when you want early adoption.
- **Verdict:** wrong shape for this product. Not revisiting unless the
  usage pattern itself changes (e.g. if the app expands into an
  always-on rental-market-tracking product rather than a search tool).

### 3. B2B lead-gen to landlords/agencies — deferred

**Pros:**
- Landlords/agencies are a more willing payer than end users — they have
  clear ROI (filled vacancy = revenue) and are used to paying for
  visibility (OLX/Storia already sell "promoted listing" placements).
- Doesn't compete with the free-user-search value prop at all — orthogonal
  revenue axis, could run alongside the credit model rather than instead
  of it.
- Higher revenue-per-transaction than consumer credits.

**Cons:**
- **Bigger pivot than it looks.** Right now this app has no
  direct-listing-ingestion path — everything comes from scraping OLX/
  Storia/Imobiliare. Selling "featured placement" on a listing this app
  doesn't own the relationship for is awkward at best (whose listing is it
  to feature?) and needs a real supply-side product (landlords submitting
  listings directly) to work cleanly.
- Two-sided marketplace dynamics are genuinely harder to bootstrap than a
  single-sided consumer product — needs enough demand-side traffic first
  to be worth a landlord's money, which the credit model needs to prove
  out first anyway.
- **Verdict:** worth revisiting once user volume is real and/or a direct
  listing-submission flow exists — not a v1 candidate.

### 4. Affiliate/referral (movers, insurance, furniture, utilities setup) — deferred

**Pros:**
- Very low product/build cost — a link or a partner API call at the
  "you found your place" moment, no core feature changes.
- No conflict with the free-search value prop — purely additive.
- Natural fit for the exact moment a user is most receptive: right after
  finding a place, they need movers/insurance/furniture/utilities anyway.

**Cons:**
- Revenue per conversion is small, and conversion rate off a link is
  typically low — needs real traffic volume to matter, which doesn't exist
  yet.
- Depends on finding Romanian (or city-local) partners for each vertical —
  more partner-sourcing work than engineering work.
- **Verdict:** cheap enough to add opportunistically later (e.g. once
  Phase 3 city rollout brings real traffic), but not worth prioritizing
  build time on now — low effort, so revisit any time, not gated on
  anything else.

### 5. Ads — deferred

**Pros:**
- Simplest possible model, no product changes to the core search
  experience needed.
- No dependency on user accounts or payment infra.

**Cons:**
- Weakest fit for current scale — ad revenue is a function of traffic
  volume, and this app doesn't have it yet.
- Actively working against the AI-ranking value prop — ads on a page whose
  pitch is "better, cleaner search than OLX" is a weird look.
- Lowest revenue ceiling of all options here relative to the effort of
  building a decent ad experience.
- **Verdict:** last resort, not a real candidate while the credit model
  and lead-gen paths are both more aligned with what this app actually is.

### 6. Data/research licensing — parked for later

**Pros:**
- Genuine differentiated asset once it exists: longitudinal price/
  availability history (crawling since May 2026), cross-platform
  deduplicated panel (post-`Roadmap.md` P5), LLM-enriched attributes
  (`ENRICHMENT_PLAN.md`), and — most uniquely — demand-side signal from
  `user_events` (what people search for vs. what's actually listed, which
  no competitor's independent scrape could replicate).
- Multiple buyer segments plausible: PropTech/analytics firms, investment
  funds (rental yield data for site selection), municipal/urban-planning
  bodies (especially relevant given the student-city expansion angle),
  academic researchers, journalists.
- Doesn't require touching the core consumer product at all — orthogonal
  revenue stream once built.

**Cons:**
- **Current scale is thin.** ~7–10k rows, one city — not yet a
  hard-to-replicate dataset on its own. Gets much stronger post-geo-
  expansion (multi-city) and after enough time has passed to have a real
  longitudinal panel, not a snapshot.
- Raw listing rows aren't defensible as a product — anyone can scrape
  OLX/Storia/Imobiliare themselves. The moat is the *maintained,
  aggregated, enriched, demand-annotated* version, which takes time to
  accumulate, not something sellable today.
- **Legal risk is real, not hypothetical:** internal use (powering this
  app's own search) and reselling scraped data to third parties are very
  different risk levels. Source platforms' ToS almost certainly prohibit
  both scraping and redistribution; EU *sui generis* database rights can
  protect a platform's compiled listings independent of copyright, making
  resale riskier than scraping-for-own-use. Listing descriptions can
  contain personal data (landlord contact info); resold `user_events` data
  is unambiguously personal data under GDPR. **Needs real legal review
  before any deal, not an engineering judgment call.**
- **Verdict:** keep for later, per explicit decision this session. Not
  pursued until (a) geo-expansion + dedup give real multi-city longitudinal
  breadth, and (b) actual legal counsel has reviewed the redistribution
  question. If it does move forward, the lower-risk entry point is a
  **free aggregate public index/report** (PR value, no row-level data
  exposed) with **custom one-off research engagements** (selling analysis,
  not raw scraped rows) as the actual revenue — sidesteps most of the
  redistribution risk.

---

## Quick comparison

| Option | Status | Fits usage pattern? | Build cost | Legal/dependency risk |
|---|---|---|---|---|
| Credit top-up (AI ranking) | **Decided** | Yes — burst usage, pay-per-hunt | Low-medium (needs accounts + ledger) | Low |
| Freemium subscription | Rejected | No — burst usage, poor MRR fit | Low | Low |
| B2B lead-gen | Deferred | N/A (supply-side) | High (needs listing-submission flow) | Medium (marketplace bootstrap) |
| Affiliate/referral | Deferred | Additive, doesn't conflict | Very low | Low |
| Ads | Deferred | Additive but conflicts with brand | Low | Low |
| Data/research licensing | Parked | N/A (separate business line) | Medium-high (needs scale first) | **High** — ToS + database rights + GDPR |

## Related

- `Roadmap.md` §4.0 — the decided credit-model mechanics this doc summarizes.
- `GEO_EXPANSION_PLAN.md` — multi-city breadth is a prerequisite for the
  data-licensing option to be realistic.
- `Roadmap.md` P5 (dedup) — cross-platform deduplication is part of what
  makes the eventual data-licensing panel actually differentiated.
