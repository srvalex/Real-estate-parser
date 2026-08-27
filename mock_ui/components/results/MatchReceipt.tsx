"use client";

import { Check, ChevronDown, Minus, X } from "lucide-react";
import clsx from "clsx";
import type { ScoredListing, VibeFilterKey, VibeFilters } from "@/lib/types";
import { VIBE_FILTER_LABELS } from "@/lib/nlpFilters";

function ReceiptRow({ label, met }: { label: string; met: boolean | null }) {
  return (
    <li className="flex items-center justify-between border-b border-dashed border-concrete/30 py-1 font-mono text-xs">
      <span className={met === false ? "text-concrete line-through" : "text-ink"}>{label}</span>
      {met === null ? (
        <Minus className="h-3 w-3 text-concrete" />
      ) : met ? (
        <Check className="h-3 w-3 text-pine" />
      ) : (
        <X className="h-3 w-3 text-brick/70" />
      )}
    </li>
  );
}

export function MatchReceipt({
  listing,
  requestedFilters,
  isOpen,
  onToggle,
}: {
  listing: ScoredListing;
  requestedFilters: VibeFilters;
  isOpen: boolean;
  onToggle: () => void;
}) {
  const requestedKeys = Object.keys(requestedFilters) as VibeFilterKey[];
  const matchedSet = new Set(listing.matchedFilters);
  const hasVibeQuery = requestedKeys.length > 0 || listing.textSimilarity !== null;

  if (!hasVibeQuery && listing.priceFairnessPct === null) return null;

  return (
    <div className="border-t border-concrete/20">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={isOpen}
        className="flex w-full items-center justify-between px-4 py-2 text-left text-xs font-medium text-concrete hover:text-ink"
      >
        Bon de potrivire
        <ChevronDown className={clsx("h-3.5 w-3.5 transition-transform", isOpen && "rotate-180")} />
      </button>
      <div
        className="grid transition-[grid-template-rows] duration-200 ease-out"
        style={{ gridTemplateRows: isOpen ? "1fr" : "0fr" }}
      >
        <div className="overflow-hidden">
          <div className="mx-4 mb-4 rounded-sm border border-concrete/25 bg-paper-dim px-3 py-2">
            {requestedKeys.length > 0 && (
              <ul>
                {requestedKeys.map((key) => (
                  <ReceiptRow key={key} label={VIBE_FILTER_LABELS[key]} met={matchedSet.has(key)} />
                ))}
              </ul>
            )}

            {listing.priceFairnessPct !== null && (
              <div className="flex items-center justify-between py-1 font-mono text-xs">
                <span className="text-ink">preț vs. medie zonă</span>
                <span className={listing.priceFairnessPct < 0 ? "text-pine" : "text-brick"}>
                  {listing.priceFairnessPct > 0 ? "+" : ""}
                  {listing.priceFairnessPct}%
                </span>
              </div>
            )}

            {listing.textSimilarity !== null && (
              <div className="py-1.5">
                <div className="mb-1 flex items-center justify-between font-mono text-[0.68rem] text-concrete">
                  <span>potrivire text</span>
                  <span>{Math.round(listing.textSimilarity * 100)}%</span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-pill bg-concrete/20">
                  <div
                    className="h-full rounded-pill bg-brick"
                    style={{ width: `${Math.round(listing.textSimilarity * 100)}%` }}
                  />
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
