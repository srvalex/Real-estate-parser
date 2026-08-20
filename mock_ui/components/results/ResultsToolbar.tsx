"use client";

import { ArrowLeft } from "lucide-react";
import clsx from "clsx";
import type { HardFilters, VibeFilters } from "@/lib/types";
import { FilterPillBar } from "./FilterPillBar";

export type SortMode = "relevance" | "price" | "newest";

export function ResultsToolbar({
  onBack,
  hardFilters,
  zonesCount,
  vibeFilters,
  shownCount,
  totalCount,
  sort,
  onSortChange,
  relevanceAvailable,
}: {
  onBack: () => void;
  hardFilters: HardFilters;
  zonesCount: number;
  vibeFilters: VibeFilters;
  shownCount: number;
  totalCount: number;
  sort: SortMode;
  onSortChange: (s: SortMode) => void;
  relevanceAvailable: boolean;
}) {
  return (
    <div className="sticky top-0 z-10 border-b border-concrete/25 bg-paper/90 backdrop-blur-sm">
      <div className="mx-auto max-w-6xl px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <button
            type="button"
            onClick={onBack}
            className="inline-flex items-center gap-1.5 text-sm font-medium text-ink hover:text-brick"
          >
            <ArrowLeft className="h-4 w-4" /> Căutare nouă
          </button>

          <div className="flex items-center gap-3">
            <span className="hidden font-mono text-xs text-concrete sm:inline">
              <strong className="text-ink">{shownCount}</strong> din {totalCount}
            </span>
            <div className="inline-flex overflow-hidden rounded-sm border border-concrete/40 text-xs">
              {(
                [
                  ["relevance", "Relevanță"],
                  ["price", "Preț"],
                  ["newest", "Noutate"],
                ] as [SortMode, string][]
              ).map(([mode, label]) => (
                <button
                  key={mode}
                  type="button"
                  disabled={mode === "relevance" && !relevanceAvailable}
                  onClick={() => onSortChange(mode)}
                  className={clsx(
                    "border-l border-concrete/40 px-2.5 py-1.5 first:border-l-0 transition-colors",
                    sort === mode ? "bg-ink text-paper" : "bg-transparent text-ink hover:bg-brick-tint",
                    mode === "relevance" && !relevanceAvailable && "cursor-not-allowed opacity-40"
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="mt-2.5">
          <FilterPillBar hardFilters={hardFilters} zonesCount={zonesCount} vibeFilters={vibeFilters} />
        </div>
      </div>
    </div>
  );
}
