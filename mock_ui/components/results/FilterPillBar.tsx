import { MapPin, Sparkles } from "lucide-react";
import type { HardFilters, VibeFilters } from "@/lib/types";
import { formatVibeFilterValue } from "@/lib/nlpFilters";

function hardFilterLabels(filters: HardFilters, zonesCount: number): string[] {
  const labels: string[] = [];
  if (zonesCount > 0) labels.push(`${zonesCount} cartiere`);
  if (filters.rooms !== "Orice") labels.push(`${filters.rooms} camere`);
  if (filters.maxPrice > 0) labels.push(`≤ ${filters.maxPrice} €`);
  if (filters.minSqm > 0) labels.push(`≥ ${filters.minSqm} m²`);
  if (filters.maxSqm > 0) labels.push(`≤ ${filters.maxSqm} m²`);
  if (filters.propertyTypes.length > 0 && filters.propertyTypes.length < 4) {
    labels.push(filters.propertyTypes.join(" / "));
  }
  return labels;
}

export function FilterPillBar({
  hardFilters,
  zonesCount,
  vibeFilters,
}: {
  hardFilters: HardFilters;
  zonesCount: number;
  vibeFilters: VibeFilters;
}) {
  const hard = hardFilterLabels(hardFilters, zonesCount);
  const vibeKeys = Object.keys(vibeFilters) as (keyof VibeFilters)[];

  if (hard.length === 0 && vibeKeys.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {hard.map((label) => (
        <span
          key={label}
          className="inline-flex items-center gap-1 rounded-pill border border-ink/25 bg-ink/5 px-2.5 py-1 text-xs font-medium text-ink"
        >
          <MapPin className="h-3 w-3" strokeWidth={2.25} />
          {label}
        </span>
      ))}
      {vibeKeys.map((key) => (
        <span
          key={key}
          className="inline-flex items-center gap-1 rounded-pill border border-dashed border-brick/50 px-2.5 py-1 text-xs text-brick"
        >
          <Sparkles className="h-3 w-3" strokeWidth={2.25} />
          {formatVibeFilterValue(key, vibeFilters[key]!)}
        </span>
      ))}
    </div>
  );
}
