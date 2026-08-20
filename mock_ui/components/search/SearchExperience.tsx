"use client";

import { useMemo, useRef, useState } from "react";
import Link from "next/link";
import { AnimatePresence, motion, MotionConfig } from "framer-motion";
import { BarChart3, Search } from "lucide-react";
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
import { getDistrictsBySector, ALL_LISTINGS } from "@/lib/mockData";
import { expandWithProximity } from "@/lib/zones";
import { extractVibeFilters, isExcludedByDescription } from "@/lib/nlpFilters";
import { applyHardFilters, scoreListings } from "@/lib/matching";
import type { HardFilters, Platform, ScoredListing, SourceState, VibeFilters } from "@/lib/types";

const DISTRICTS = getDistrictsBySector();
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
            <div className="mx-auto flex max-w-2xl justify-end px-4 pt-4">
              <Link
                href="/analytics"
                className="inline-flex items-center gap-1.5 text-xs font-medium text-concrete hover:text-brick"
              >
                <BarChart3 className="h-3.5 w-3.5" /> Analiză de piață
              </Link>
            </div>
            <Hero />
            <div className="mx-auto max-w-2xl space-y-4 px-4 pb-24">
              <HardFiltersPanel value={hardFilters} onChange={setHardFilters} />
              <VibePrompt value={vibe} onChange={setVibe} detected={liveVibeFilters} />

              <div className="rounded-lg border border-concrete/25 bg-white/40 p-4 sm:p-5">
                <ZoneSelector
                  districts={DISTRICTS}
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

              {stage === "idle" ? (
                <button
                  type="button"
                  onClick={handleSearch}
                  className="flex w-full items-center justify-center gap-2 rounded-sm bg-ink py-3 text-sm font-medium text-paper transition-colors hover:bg-brick"
                >
                  <Search className="h-4 w-4" /> Caută locuințe
                </button>
              ) : (
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
