"use client";

import { useState } from "react";
import { ArrowUpRight, BedDouble, EyeOff, MapPin, Ruler, Sparkles, Wand2 } from "lucide-react";
import clsx from "clsx";
import type { ScoredListing, VibeFilters } from "@/lib/types";
import { formatFreshness, formatPrice } from "@/lib/format";
import { ImageCarousel } from "./ImageCarousel";
import { MatchReceipt } from "./MatchReceipt";
import { StaticPill } from "@/components/ui/Chip";

export function ListingCard({
  listing,
  requestedFilters,
  onHide,
  onMoreLikeThis,
}: {
  listing: ScoredListing;
  requestedFilters: VibeFilters;
  onHide: (url: string) => void;
  onMoreLikeThis: (listing: ScoredListing) => void;
}) {
  const [receiptOpen, setReceiptOpen] = useState(false);
  const matchPct = listing.matchScore !== null ? Math.round(listing.matchScore * 100) : null;
  const scoreTone = matchPct === null ? "concrete" : matchPct >= 70 ? "pine" : matchPct >= 40 ? "gold" : "concrete";

  return (
    <article className="group relative flex flex-col overflow-hidden rounded-lg border border-concrete/25 bg-white/60 transition-all hover:-translate-y-0.5 hover:shadow-hover">
      <div className="relative">
        <ImageCarousel images={listing.image_urls} alt={listing.title} propertyType={listing.property_type} />

        <div className="pointer-events-none absolute left-2 top-2 flex flex-wrap gap-1">
          <StaticPill tone="concrete">{listing.platform}</StaticPill>
          {listing.isNearbyZone && <StaticPill tone="brick">în apropiere</StaticPill>}
        </div>

        {matchPct !== null && (
          <div className="pointer-events-none absolute right-2 top-2">
            <StaticPill tone={scoreTone as "pine" | "gold" | "concrete"}>
              <Sparkles className="h-3 w-3" strokeWidth={2.25} />
              {matchPct}% potrivire
            </StaticPill>
          </div>
        )}

        <div className="absolute inset-x-2 bottom-2 flex justify-end gap-1.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
          <button
            type="button"
            onClick={() => onMoreLikeThis(listing)}
            className="inline-flex items-center gap-1 rounded-sm bg-ink/85 px-2 py-1 text-xs text-paper backdrop-blur-sm hover:bg-brick"
          >
            <Wand2 className="h-3 w-3" /> Mai multe ca acesta
          </button>
          <button
            type="button"
            onClick={() => onHide(listing.url)}
            className="inline-flex items-center gap-1 rounded-sm bg-ink/85 px-2 py-1 text-xs text-paper backdrop-blur-sm hover:bg-brick"
          >
            <EyeOff className="h-3 w-3" /> Ascunde
          </button>
        </div>
      </div>

      <div className="flex flex-1 flex-col p-4">
        <h3 className="font-display text-base leading-snug text-ink">{listing.title}</h3>

        <div className="mt-1.5 flex items-baseline justify-between">
          <span className="font-mono text-lg font-semibold text-ink">
            {formatPrice(listing.price_numeric, listing.price_currency)}
          </span>
          <span className="text-xs text-concrete">{formatFreshness(listing.scraped_at)}</span>
        </div>

        <div className="mt-2 flex flex-wrap gap-1.5 text-xs text-concrete">
          <span className="inline-flex items-center gap-1">
            <BedDouble className="h-3.5 w-3.5" /> {listing.rooms} camere
          </span>
          <span className="inline-flex items-center gap-1">
            <Ruler className="h-3.5 w-3.5" /> {listing.area_sqm} m²
          </span>
          <span className="inline-flex items-center gap-1">
            <MapPin className="h-3.5 w-3.5" /> {listing.district}
          </span>
        </div>

        <p className="mt-3 line-clamp-2 text-sm text-concrete">{listing.description}</p>

        <a
          href={listing.url}
          target="_blank"
          rel="noreferrer"
          className={clsx(
            "mt-3 inline-flex w-fit items-center gap-1 text-sm font-medium text-brick",
            "underline decoration-brick/40 underline-offset-4 hover:decoration-brick"
          )}
        >
          Vezi anunțul
          <ArrowUpRight className="h-3.5 w-3.5" />
        </a>
      </div>

      <MatchReceipt
        listing={listing}
        requestedFilters={requestedFilters}
        isOpen={receiptOpen}
        onToggle={() => setReceiptOpen((o) => !o)}
      />
    </article>
  );
}
