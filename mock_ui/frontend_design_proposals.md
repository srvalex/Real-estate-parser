# Frontend Redesign — Design Proposals

Concrete proposals against each requirement from the checklist. Use this as the brief when building the mock UI.

---

## 1. Visual identity

**Palette — grounded in Bucharest, not generic AI-SaaS**
Avoid the indigo/purple gradient (current app) and the cream+terracotta AI-default. Instead, pull from the city itself: brick facades, park greens, communist-block concrete, amber streetlight.

| Token | Hex | Use |
|---|---|---|
| `ink` | `#1E1C1A` | Primary text, warm near-black (not pure black) |
| `paper` | `#F7F4EE` | Background — warm off-white, not stark white |
| `brick` | `#A8461F` | Primary accent — deep brick red, distinct from the flagged `#D97757` terracotta |
| `pine` | `#3E4E3A` | Secondary accent — muted park green, used for "match/positive" signals |
| `concrete` | `#8C8579` | Neutral/muted text, borders, dividers |
| `gold` | `#B8892B` | Price highlights, key numbers only — used sparingly |

**Typography**
- **Display**: *Fraunces* (or *Instrument Serif*) — a serif with real character, used only for page-level headlines and the hero/search prompt label. Evokes architecture and permanence, not another SaaS grotesk.
- **Body**: *Public Sans* or *Inter* — clean, neutral, high legibility for listing descriptions and UI copy.
- **Utility/data**: *IBM Plex Mono* — for prices, square meters, coordinates, timestamps. Monospace numerals read as "precise/data-driven," which reinforces the AI-ranking premise without saying it.

**Shape & elevation**
- Sharp-ish radius (4–6px) on cards and buttons — not the bubbly 16–20px rounding that reads as a UI kit default.
- Hairline 1px borders (`concrete` at low opacity) instead of drop shadows for resting state. Reserve a soft shadow for hover/active only — elevation should mean something, not decorate everything.

**Signature element**
A **"match receipt"** component on each listing card — a compact, itemized breakdown (styled like a printed receipt, monospace numerals) showing what matched: room count ✓, near metro ✓, price fairness ↑12% under area avg. This is your one deliberate risk: it's unique to this product (nothing else in the Bucharest real-estate space does this), and it's functional, not decorative — it *is* the transparency requirement from section 3, given a visual identity.

---

## 2. Information architecture

- **Search bar split into two visually distinct zones**: a chip/field row for hard filters (rooms, price, area — exact, user-controlled) sitting above a visually separate "Describe what you're looking for" text area (soft/vibe prompt) with a subtly tinted background (`paper` → very light `brick` tint) to mark it as the AI-interpreted zone.
- **Results page**: sticky top bar showing active filter summary + result count + sort control (relevance / price / newest). Each card shows a small source badge (OLX / Storia / Imobiliare) and freshness ("updated 3h ago").
- **Listing detail**: a slide-over drawer on desktop (keeps results list state/scroll position intact), full page on mobile.
- **Analytics dashboard**: rebuild charts in Recharts (or visx) using the same design tokens as the rest of the app — currently Plotly's default styling will clash with a custom design system. Keep sector drilldown as breadcrumbs (`Sector 2 > Dristor`) rather than dropdowns, for a more "map-like" navigational feel.

---

## 3. Agentic transparency

- **Two distinct pill styles**: solid-fill pill for manually-set filters, dashed-outline pill with a small spark icon for NLP-inferred ones. The visual distinction *is* the requirement — don't rely on a tooltip alone.
- **Match receipt** (see signature element above) does double duty as your "why this ranked here" requirement — expandable per card, showing matched attributes as a checklist plus a small horizontal split bar for text-similarity vs. image-similarity contribution.
- **Status stepper** during search: "Reading your prompt → Searching 3 sources → Ranking by fit," each stage with an icon that fills in as it completes. Replaces the generic spinner and gives the pipeline visible structure.
- **Progressive rendering**: skeleton cards (shaped like the real card — image block + two text lines + price line, not generic grey bars) appear immediately; real cards fade/slide in as they arrive, staggered ~50ms apart. When re-ranking happens, animate the reorder rather than snapping.
- **Correction affordances**: on hover, each card reveals two small actions — "More like this" and "Hide" — that refine the current result set instead of forcing a full new search.

---

## 4. States

- **Empty state**: specific, actionable — "No listings match all filters. Try loosening price (currently ≤ €600) or area (currently Dristor only)" with the offending filter clickable to adjust inline, not a generic "no results" message.
- **Partial failure**: a non-blocking banner — "Storia is taking longer than usual — showing OLX and Imobiliare for now" — rather than hanging or silently dropping a source.
- **Skeleton loading**: matches the real card's exact shape and proportions, so the layout doesn't jump when data arrives.
- **Missing-photo fallback**: a simple line-art illustration keyed to property type (apartment block, studio, etc.) instead of a broken-image icon — small detail, but it's one of the fastest tells of an unfinished product.

---

## 5. Interaction & motion

- **One deliberate motion moment**: on submitting a search, the vibe-prompt text area animates/"folds" into a compact pill at the top of the results page while cards stream in below (a single Framer Motion layout transition) — this is the one orchestrated moment; everything else stays quiet.
- Elsewhere: a subtle 2px hover lift on cards and a clear focus ring in `brick` — no animation on every element, no scroll-triggered reveals for their own sake.
- Respect `prefers-reduced-motion`: fall back to opacity-only transitions, no movement.

---

## 6. Responsive/technical

- Mobile-first single-column card layout with a swipeable image carousel per card (touch-friendly, since listing photos are a core signal in your CLIP-based ranking).
- Lazy-load images with blur-up placeholders.
- **Define the API contract first**: let FastAPI auto-generate its OpenAPI schema, then generate TypeScript types for the Next.js frontend from it (`openapi-typescript`). Keeps frontend and backend in sync automatically as the pipeline evolves, and lets you build the mock UI against realistic typed data from day one.

---

## 7. Copy/voice

- Buttons named by outcome, not mechanism: "Search listings," not "Submit." "Update filters," not "Apply."
- Filter pills stay in plain language you've already started using: "Near a metro station," "2 rooms," "Parking included" — extend this consistently to every extracted field, never raw keys like `HAS_METRO`.
- Errors state what happened and what to do, in the interface's voice: "We couldn't reach Storia just now — try again in a bit," not "Error 500."
- Empty states are an invitation to act, not a dead end (see section 4).

---

*Use this alongside the earlier requirements checklist when building the mock UI — each proposal here maps 1:1 to a checklist item.*
