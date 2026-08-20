"use client";

import { useState } from "react";
import { ChevronDown, MapPin } from "lucide-react";
import clsx from "clsx";

export function ZoneSelector({
  districts,
  selectedZones,
  onChangeZones,
  includeProximity,
  onChangeIncludeProximity,
  proximityCount,
}: {
  districts: Record<string, string[]>;
  selectedZones: string[];
  onChangeZones: (zones: string[]) => void;
  includeProximity: boolean;
  onChangeIncludeProximity: (v: boolean) => void;
  proximityCount: number;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const selectedSet = new Set(selectedZones);

  function toggleExpanded(sector: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(sector) ? next.delete(sector) : next.add(sector);
      return next;
    });
  }

  function toggleNeighborhood(name: string) {
    onChangeZones(
      selectedSet.has(name) ? selectedZones.filter((z) => z !== name) : [...selectedZones, name]
    );
  }

  function toggleSector(sector: string, neighborhoods: string[]) {
    const allSelected = neighborhoods.every((n) => selectedSet.has(n));
    if (allSelected) {
      onChangeZones(selectedZones.filter((z) => !neighborhoods.includes(z)));
    } else {
      const merged = new Set([...selectedZones, ...neighborhoods]);
      onChangeZones([...merged]);
    }
  }

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <p className="font-mono text-[0.68rem] uppercase tracking-[0.14em] text-concrete">
          Zonă de căutare
        </p>
        {selectedZones.length > 0 && (
          <span className="font-mono text-xs text-brick">{selectedZones.length} cartiere selectate</span>
        )}
      </div>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {Object.entries(districts).map(([sector, neighborhoods]) => {
          const selectedInSector = neighborhoods.filter((n) => selectedSet.has(n)).length;
          const isOpen = expanded.has(sector);
          const allSelected = selectedInSector === neighborhoods.length;

          return (
            <div key={sector} className="overflow-hidden rounded-sm border border-concrete/30">
              <div className="flex items-center gap-2 bg-white/40 px-3 py-2">
                <button
                  type="button"
                  onClick={() => toggleExpanded(sector)}
                  className="flex flex-1 items-center gap-2 text-left"
                  aria-expanded={isOpen}
                >
                  <ChevronDown
                    className={clsx("h-4 w-4 text-concrete transition-transform", isOpen && "rotate-180")}
                  />
                  <span className="text-sm font-medium text-ink">{sector}</span>
                  {selectedInSector > 0 && (
                    <span className="font-mono text-xs text-brick">({selectedInSector})</span>
                  )}
                </button>
                <label className="flex cursor-pointer items-center gap-1.5 text-xs text-concrete">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={() => toggleSector(sector, neighborhoods)}
                    className="h-3.5 w-3.5 accent-brick"
                  />
                  tot
                </label>
              </div>

              {isOpen && (
                <div className="flex flex-wrap gap-1.5 border-t border-concrete/20 p-3">
                  {neighborhoods.map((n) => (
                    <button
                      key={n}
                      type="button"
                      onClick={() => toggleNeighborhood(n)}
                      aria-pressed={selectedSet.has(n)}
                      className={clsx(
                        "rounded-sm border px-2 py-1 text-xs transition-colors",
                        selectedSet.has(n)
                          ? "border-brick bg-brick text-paper"
                          : "border-concrete/35 text-ink hover:border-brick/50 hover:bg-brick-tint"
                      )}
                    >
                      {n}
                    </button>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <label className="mt-4 flex cursor-pointer items-center gap-2 text-sm text-ink">
        <input
          type="checkbox"
          checked={includeProximity}
          onChange={(e) => onChangeIncludeProximity(e.target.checked)}
          className="h-4 w-4 accent-brick"
        />
        <MapPin className="h-4 w-4 text-concrete" />
        Include cartiere vecine
        {includeProximity && proximityCount > 0 && (
          <span className="font-mono text-xs text-concrete">(+{proximityCount})</span>
        )}
      </label>
    </div>
  );
}
