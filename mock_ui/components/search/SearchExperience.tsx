"use client";

import { useMemo, useRef, useState } from "react";
import { AnimatePresence, motion, MotionConfig } from "framer-motion";
import { ChevronDown, SlidersHorizontal } from "lucide-react";
import clsx from "clsx";
import { Hero } from "./Hero";
import { HardFiltersPanel } from "./HardFiltersPanel";
import { VibePrompt } from "./VibePrompt";
import { ZoneSelector } from "./ZoneSelector";
import { StatusStepper, type PipelineStage } from "@/components/results/StatusStepper";
import { ResultsToolbar, type SortMode } from "@/components/results/ResultsToolbar";
import { ListingCard } from "@/components/results/ListingCard";
import { SkeletonCard } from "@/components/results/SkeletonCard";
import { EmptyState } from "@/components/results/EmptyState";
import { PartialFailureBanner } from "@/components/results/PartialFailureBanner";
import { ALL_LISTINGS } from "@/lib/mockData";
import { getLocations } from "@/lib/locations";
import { expandWithProximity } from "@/lib/zones";
import { extractVibeFilters, isExcludedByDescription } from "@/lib/nlpFilters";
import { applyHardFilters, scoreListings } from "@/lib/matching";
import type { HardFilters, Platform, ScoredListing, SourceState, VibeFilters } from "@/lib/types";

const LOCATIONS = getLocations();
const PLATFORMS: Platform[] = ["OLX", "Storia", "Imobiliare"];

const DEFAULT_HARD_FILTERS: HardFilters = {
  maxPrice: 0,
  rooms: "Orice",
  minSqm: 0,
  maxSqm: 0,
  propertyTypes: [],
};

type Stage = "idle" | "pipeline" | "results";

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function SearchExperience() {
  const [hardFilters, setHardFilters] = useState<HardFilters>(DEFAULT_HARD_FILTERS);
  const [vibe, setVibe] = useState("");
  const [zones, setZones] = useState<string[]>([]);
  const [includeProximity, setIncludeProximity] = useState(false);
  const [zoneError, setZoneError] = useState<string | null>(null);

  const [filtersOpen, setFiltersOpen] = useState(false);
  const [stage, setStage] = useState<Stage>("idle");
  const [pipelineStage, setPipelineStage] = useState<PipelineStage>("reading");
  const [sources, setSources] = useState<SourceState[]>(PLATFORMS.map((p) => ({ platform: p, status: "pending" })));
  const [failedPlatform, setFailedPlatform] = useState<Platform | null>(null);

  const [results, setResults] = useState<ScoredListing[]>([]);
  const [vibeFiltersUsed, setVibeFiltersUsed] = useState<VibeFilters>({});
  const [hiddenUrls, setHiddenUrls] = useState<Set<string>>(new Set());
  const [boostDistricts, setBoostDistricts] = useState<Set<string>>(new Set());
  const [sort, setSort] = useState<SortMode>("newest");

  const searchCountRef = useRef(0);
  const liveVibeFilters = useMemo(() => extractVibeFilters(vibe), [vibe]);
  const proximityExtra = useMemo(() => (zones.length ? expandWithProximity(zones) : []), [zones]);
  const effectiveZones = useMemo(
    () => new Set([...zones, ...(includeProximity ? proximityExtra : [])]),
    [zones, includeProximity, proximityExtra]
  );

  async function handleSearch() {
    if (zones.length === 0) {
      setZoneError("Selectează cel puțin o zonă de căutare.");
      return;
    }
    setZoneError(null);
    setHiddenUrls(new Set());
    setBoostDistricts(new Set());

    setStage("pipeline");
    setPipelineStage("reading");
    setSources(PLATFORMS.map((p) => ({ platform: p, status: "pending" })));
    await wait(400);

    searchCountRef.current += 1;
    const isSlowSearch = searchCountRef.current % 3 === 0;
    const slowPlatform: Platform = "Storia";

    setPipelineStage("searching");
    setSources(PLATFORMS.map((p) => ({ platform: p, status: "loading" })));
    for (const p of PLATFORMS) {
      await wait(260);
      setSources((prev) =>
        prev.map((s) => (s.platform === p ? { ...s, status: isSlowSearch && p === slowPlatform ? "slow" : "done" } : s))
      );
    }

    setPipelineStage("ranking");
    await wait(450);

    // ── "Query the DB" then apply hard + soft filters, same order as the Python pipeline ──
    const vibeFilters = extractVibeFilters(vibe);
    const zoneMatches = ALL_LISTINGS.filter((l) => l.is_available === 1 && effectiveZones.has(l.district));
    const hardFiltered = applyHardFilters(zoneMatches, hardFilters);
    const descriptionFiltered = hardFiltered.filter(
      (l) => isExcludedByDescription(l.description, vibeFilters).length === 0
    );
    const sourceFiltered = isSlowSearch
      ? descriptionFiltered.filter((l) => l.platform !== slowPlatform)
      : descriptionFiltered;
    const scored = scoreListings(sourceFiltered, vibe, vibeFilters, new Set(includeProximity ? proximityExtra : []));

    setResults(scored);
    setVibeFiltersUsed(vibeFilters);
    setFailedPlatform(isSlowSearch ? slowPlatform : null);
    setSort(vibe.trim() ? "relevance" : "newest");
    setStage("results");
  }

  function handleBack() {
    setStage("idle");
  }

  function handleHide(url: string) {
    setHiddenUrls((prev) => new Set(prev).add(url));
  }

  function handleMoreLikeThis(listing: ScoredListing) {
    setBoostDistricts((prev) => new Set(prev).add(listing.district));
  }

  const displayList = useMemo(() => {
    let list = results.filter((r) => !hiddenUrls.has(r.url));
    if (boostDistricts.size > 0) {
      list = list.map((r) =>
        boostDistricts.has(r.district) && r.matchScore !== null
          ? { ...r, matchScore: Math.min(1, r.matchScore + 0.12) }
          : r
      );
    }
    const sorted = [...list];
    if (sort === "relevance") {
      sorted.sort((a, b) => (b.matchScore ?? -1) - (a.matchScore ?? -1));
    } else if (sort === "price") {
      sorted.sort((a, b) => a.price_numeric - b.price_numeric);
    } else {
      sorted.sort((a, b) => Date.parse(b.scraped_at) - Date.parse(a.scraped_at));
    }
    return sorted;
  }, [results, hiddenUrls, boostDistricts, sort]);

  const hardFilterSummary = useMemo(() => {
    const parts: string[] = [];
    if (hardFilters.rooms !== "Orice") parts.push(`${hardFilters.rooms} camere`);
    if (hardFilters.maxPrice > 0) parts.push(`≤ ${hardFilters.maxPrice} €`);
    if (hardFilters.minSqm > 0 || hardFilters.maxSqm > 0) {
      parts.push(`${hardFilters.minSqm || 0}–${hardFilters.maxSqm || "∞"} m²`);
    }
    if (hardFilters.propertyTypes.length > 0) parts.push(hardFilters.propertyTypes.join(", "));
    return parts;
  }, [hardFilters]);

  const emptySuggestion = useMemo(() => {
    if (displayList.length > 0) return null;
    if (hardFilters.maxPrice > 0) {
      return {
        message: `Niciun anunț sub ${hardFilters.maxPrice} €. Încearcă să ridici pragul de preț.`,
        actionLabel: "Elimină pragul de preț",
        onRelax: () => setHardFilters((f) => ({ ...f, maxPrice: 0 })),
      };
    }
    if (hardFilters.minSqm > 0 || hardFilters.maxSqm > 0) {
      return {
        message: "Niciun anunț nu se încadrează în intervalul de suprafață cerut.",
        actionLabel: "Elimină filtrul de suprafață",
        onRelax: () => setHardFilters((f) => ({ ...f, minSqm: 0, maxSqm: 0 })),
      };
    }
    if (hardFilters.propertyTypes.length > 0) {
      return {
        message: "Niciun anunț de acest tip în zona selectată.",
        actionLabel: "Include toate tipurile",
        onRelax: () => setHardFilters((f) => ({ ...f, propertyTypes: [] })),
      };
    }
    return {
      message: `Niciun anunț disponibil în cele ${zones.length} cartiere selectate.`,
      actionLabel: "Include cartiere vecine",
      onRelax: () => setIncludeProximity(true),
    };
  }, [displayList.length, hardFilters, zones.length]);

  return (
    <MotionConfig reducedMotion="user">
    <div className="min-h-screen">
      <AnimatePresence mode="wait">
        {stage !== "results" ? (
          <motion.div
            key="search"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ duration: 0.35, ease: "easeOut" }}
          >
            <Hero />
            <div className="mx-auto max-w-2xl space-y-4 px-4 pb-24">
              <div className="relative z-10 -mt-10 sm:-mt-14">
                <VibePrompt
                  value={vibe}
                  onChange={setVibe}
                  detected={liveVibeFilters}
                  onSubmit={stage === "idle" ? handleSearch : undefined}
                />
              </div>

              <div className="rounded-lg border border-concrete/25 bg-white/40 p-4 sm:p-5">
                <ZoneSelector
                  locations={LOCATIONS}
                  selectedZones={zones}
                  onChangeZones={(z) => {
                    setZones(z);
                    if (z.length > 0) setZoneError(null);
                  }}
                  includeProximity={includeProximity}
                  onChangeIncludeProximity={setIncludeProximity}
                  proximityCount={proximityExtra.length}
                />
                {zoneError && <p className="mt-3 text-sm text-brick">{zoneError}</p>}
              </div>

              <div className="rounded-lg border border-concrete/25 bg-white/40">
                <button
                  type="button"
                  onClick={() => setFiltersOpen((o) => !o)}
                  aria-expanded={filtersOpen}
                  className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left sm:px-5"
                >
                  <span className="flex items-center gap-2 text-sm font-medium text-ink">
                    <SlidersHorizontal className="h-4 w-4 text-concrete" />
                    Filtre exacte
                    <span className="font-mono text-xs font-normal text-concrete">(cameră, preț, suprafață)</span>
                  </span>
                  <span className="flex items-center gap-2">
                    {!filtersOpen &&
                      hardFilterSummary.map((s) => (
                        <span key={s} className="hidden font-mono text-xs text-brick sm:inline">
                          {s}
                        </span>
                      ))}
                    <ChevronDown
                      className={clsx("h-4 w-4 text-concrete transition-transform", filtersOpen && "rotate-180")}
                    />
                  </span>
                </button>
                {filtersOpen && (
                  <div className="border-t border-concrete/20 p-4 pt-3 sm:p-5 sm:pt-3">
                    <HardFiltersPanel value={hardFilters} onChange={setHardFilters} bare />
                  </div>
                )}
              </div>

              {stage !== "idle" && (
                <div>
                  <StatusStepper stage={pipelineStage} sources={sources} />
                  {pipelineStage !== "reading" && (
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                      {Array.from({ length: 4 }).map((_, i) => (
                        <SkeletonCard key={i} />
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </motion.div>
        ) : (
          <motion.div
            key="results"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, ease: "easeOut" }}
          >
            <ResultsToolbar
              onBack={handleBack}
              hardFilters={hardFilters}
              zonesCount={zones.length}
              vibeFilters={vibeFiltersUsed}
              shownCount={displayList.length}
              totalCount={results.length + hiddenUrls.size}
              sort={sort}
              onSortChange={setSort}
              relevanceAvailable={vibe.trim().length > 0}
            />

            <div className="mx-auto max-w-6xl space-y-4 px-4 py-5">
              {failedPlatform && <PartialFailureBanner platform={failedPlatform} />}

              {displayList.length === 0 ? (
                <EmptyState suggestion={emptySuggestion} />
              ) : (
                <motion.div layout className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  <AnimatePresence initial={false}>
                    {displayList.map((listing, i) => (
                      <motion.div
                        key={listing.url}
                        layout
                        initial={{ opacity: 0, y: 12 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, scale: 0.96 }}
                        transition={{ duration: 0.3, delay: Math.min(i, 9) * 0.04 }}
                      >
                        <ListingCard
                          listing={listing}
                          requestedFilters={vibeFiltersUsed}
                          onHide={handleHide}
                          onMoreLikeThis={handleMoreLikeThis}
                        />
                      </motion.div>
                    ))}
                  </AnimatePresence>
                </motion.div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
    </MotionConfig>
  );
}
