# Frontend Redesign — Requirements Checklist

Use this to check off progress while building the mock UI and implementation. Pairs with `frontend_design_proposals.md`, which has a concrete proposal for every item below.

---

## 1. Visual identity
- [ ] Palette derived from subject (Bucharest/real-estate/urban), not a default AI gradient — 4-6 named hex values, one accent used sparingly
- [ ] Typography pairing: one characterful display face (used with restraint) + one body face + one utility/data face for numbers, prices, metadata
- [ ] Consistent, purposeful border-radius / elevation system (not uniform-everywhere)
- [ ] Light-mode-first evaluation (revisit dark-mode default given consumer real-estate norms — Zillow/Storia/Idealista are light, photo-forward)
- [ ] One signature visual element the app is recognizable by (not a stock template look)

## 2. Information architecture
- [ ] Clear separation in the search UI between **hard filters** (rooms, price, area — user-controlled, exact) and **soft preference / vibe prompt** (AI-interpreted) — matches the actual NLP/embedding split in the architecture
- [ ] Results page: filter/sort controls, result count, source/freshness indicator per listing
- [ ] Listing detail view (may not exist yet in Streamlit — worth scoping: modal vs. dedicated page)
- [ ] Analytics dashboard integrated with consistent visual language (currently Plotly — decide whether to port to a JS charting lib like Recharts/D3 for consistency)

## 3. Agentic transparency
- [ ] Extracted filter pills shown distinctly from manually-set filters
- [ ] Visible "why this ranked here" explanation per listing (matched attributes, not raw scores)
- [ ] Multi-stage status feedback during search (understanding prompt → querying sources → ranking), not a single spinner
- [ ] Progressive/streaming card rendering as results arrive, not block-until-complete
- [ ] User correction affordances (re-rank, exclude, "more like this") rather than restart-only

## 4. States
- [ ] Empty state (no results) with actionable next step, not a blank page
- [ ] Partial-failure state (e.g. one source timed out) — explicit and honest, not silently missing
- [ ] Loading/skeleton states that map to real pipeline stages
- [ ] Missing-data fallback (no photo, no embedding) styled intentionally, not a broken-image icon

## 5. Interaction & motion
- [ ] One deliberate motion moment (e.g. orchestrated card reveal on search) rather than animation on every element
- [ ] Real keyboard focus states, tab order
- [ ] Reduced-motion support (`prefers-reduced-motion`)

## 6. Responsive/technical
- [ ] Mobile layout is a first-class target, not an afterthought (explicit weak point of current Streamlit app)
- [ ] Performance budget for image-heavy listing cards (lazy loading, responsive image sizes)
- [ ] API contract defined between Next.js and FastAPI before UI build starts (so mock UI can be built against realistic data shapes)

## 7. Copy/voice
- [ ] Functional, plain-language microcopy audit (button labels, empty states, errors) — active voice, consistent verb-to-outcome mapping
- [ ] Filter pill / explanation language written in end-user terms, not internal terms (e.g. "near a metro station," never "HAS_METRO")

---

*See `frontend_design_proposals.md` for a concrete proposal against each item above.*
