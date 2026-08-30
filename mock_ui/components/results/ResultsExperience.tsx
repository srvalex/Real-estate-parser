"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowLeft } from "lucide-react";
import { ResultsToolbar, type SortMode } from "./ResultsToolbar";
import { ListingCard } from "./ListingCard";
import { SkeletonCard } from "./SkeletonCard";
import { EmptyState } from "./EmptyState";
import { PartialFailureBanner } from "./PartialFailureBanner";
import { StatusStepper } from "./StatusStepper";
import { searchListingsByQueryString, hardFiltersFromQuery, vibeFiltersFromQuery } from "@/lib/api";
import { expandWithProximity } from "@/lib/zones";
import { matchedVibeFilters } from "@/lib/matching";
import type { ScoredListing } from "@/lib/types";

// This page's entire query — city/districts/filters/vibe — lives in the
// URL (built by the search form via lib/api.ts's buildQuery), not in
// state handed down from another component. That's what makes a results
// page a real, shareable, refreshable route instead of just a second
// "screen" of the search form.
export function ResultsExperience() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const qs = searchParams.toString();

  const [loading, setLoading] = useState(true);
  const [results, setResults] = useState<ScoredListing[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [embedError, setEmbedError] = useState<string | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [hiddenUrls, setHiddenUrls] = useState<Set<string>>(new Set());
  const [boostDistricts, setBoostDistricts] = useState<Set<string>>(new Set());
  const [sort, setSort] = useState<SortMode>("newest");

  const hardFilters = useMemo(() => hardFiltersFromQuery(searchParams), [searchParams]);
  const vibeFiltersUsed = useMemo(() => vibeFiltersFromQuery(searchParams), [searchParams]);
  const zones = useMemo(() => (searchParams.get("districts") ?? "").split(",").filter(Boolean), [searchParams]);
  const wholeCity = searchParams.get("all_districts") === "true";
  const vibeText = searchParams.get("vibe") ?? "";
  const templatePhotoCount = (searchParams.get("template_photos") ?? "").split(",").filter(Boolean).length;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setSearchError(null);
    setHiddenUrls(new Set());
    setBoostDistricts(new Set());

    searchListingsByQueryString(qs)
      .then((data) => {
        if (cancelled) return;
        const scored: ScoredListing[] = data.results.map((listing) => ({
          ...listing,
          matchedFilters: matchedVibeFilters(listing, vibeFiltersUsed),
        }));
        setResults(scored);
        setTotalCount(data.total_count);
        setEmbedError(data.embed_error);
        setSort(data.embedding_sorted ? "relevance" : "newest");
      })
      .catch((e) => {
        if (cancelled) return;
        setResults([]);
        setTotalCount(0);
        setSearchError(e instanceof Error ? e.message : "Căutarea a eșuat.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
    // vibeFiltersUsed is derived from `qs` itself (via searchParams), so
    // re-running only on `qs` avoids re-fetching on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qs]);

  function handleBack() {
    router.push(`/home?${qs}`);
  }

  function handleHide(url: string) {
    setHiddenUrls((prev) => new Set(prev).add(url));
  }

  function handleMoreLikeThis(listing: ScoredListing) {
    setBoostDistricts((prev) => new Set(prev).add(listing.district));
  }

  function relax(mutate: (sp: URLSearchParams) => void) {
    const next = new URLSearchParams(qs);
    mutate(next);
    router.push(`/results?${next.toString()}`);
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
    if (loading || displayList.length > 0 || searchError) return null;
    if (hardFilters.maxPrice > 0) {
      return {
        message: `Niciun anunț sub ${hardFilters.maxPrice} €. Încearcă să ridici pragul de preț.`,
        actionLabel: "Elimină pragul de preț",
        onRelax: () => relax((sp) => sp.delete("max_price")),
      };
    }
    if (hardFilters.minSqm > 0 || hardFilters.maxSqm > 0) {
      return {
        message: "Niciun anunț nu se încadrează în intervalul de suprafață cerut.",
        actionLabel: "Elimină filtrul de suprafață",
        onRelax: () =>
          relax((sp) => {
            sp.delete("min_sqm");
            sp.delete("max_sqm");
          }),
      };
    }
    if (hardFilters.propertyTypes.length > 0) {
      return {
        message: "Niciun anunț de acest tip în zona selectată.",
        actionLabel: "Include toate tipurile",
        onRelax: () => relax((sp) => sp.delete("property_types")),
      };
    }
    if (wholeCity) return null;
    return {
      message: `Niciun anunț disponibil în cele ${zones.length} cartiere selectate.`,
      actionLabel: "Include cartiere vecine",
      onRelax: () => relax((sp) => sp.set("nearby_districts", expandWithProximity(zones).join(","))),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, displayList.length, hardFilters, zones, wholeCity, searchError, qs]);

  if (loading) {
    return (
      <div className="min-h-screen">
        <div className="sticky top-0 z-10 border-b border-concrete/25 bg-paper/90 backdrop-blur-sm">
          <div className="mx-auto max-w-6xl px-4 py-3">
            <button
              type="button"
              onClick={handleBack}
              className="inline-flex items-center gap-1.5 text-sm font-medium text-ink hover:text-brick"
            >
              <ArrowLeft className="h-4 w-4" /> Căutare nouă
            </button>
          </div>
        </div>
        <div className="mx-auto max-w-6xl space-y-4 px-4 py-5">
          <StatusStepper stage="searching" />
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <SkeletonCard key={i} />
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      <ResultsToolbar
        onBack={handleBack}
        hardFilters={hardFilters}
        zonesCount={zones.length}
        vibeFilters={vibeFiltersUsed}
        shownCount={displayList.length}
        totalCount={totalCount}
        sort={sort}
        onSortChange={setSort}
        relevanceAvailable={vibeText.trim().length > 0 || templatePhotoCount > 0}
      />

      <div className="mx-auto max-w-6xl space-y-4 px-4 py-5">
        {searchError && <PartialFailureBanner message={searchError} />}
        {embedError && !searchError && <PartialFailureBanner message={embedError} />}

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
    </div>
  );
}
