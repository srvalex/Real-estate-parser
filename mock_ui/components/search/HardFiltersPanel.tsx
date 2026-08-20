"use client";

import type { HardFilters, PropertyType, RoomCount } from "@/lib/types";
import { ToggleChip } from "@/components/ui/Chip";
import clsx from "clsx";

const ROOM_OPTIONS: (RoomCount | "Orice")[] = ["Orice", "1", "2", "3", "4", "5+"];
const PROPERTY_TYPES: PropertyType[] = ["Apartament", "Garsoniera", "Studio", "Casa/Vila"];

export function HardFiltersPanel({
  value,
  onChange,
}: {
  value: HardFilters;
  onChange: (next: HardFilters) => void;
}) {
  return (
    <div className="rounded-lg border border-concrete/25 bg-white/40 p-4 sm:p-5">
      <p className="mb-3 font-mono text-[0.68rem] uppercase tracking-[0.14em] text-concrete">
        Filtre exacte
      </p>

      <div className="flex flex-wrap items-end gap-x-6 gap-y-4">
        <div>
          <label className="mb-1.5 block text-xs font-medium text-concrete">Camere</label>
          <div className="inline-flex overflow-hidden rounded-sm border border-concrete/40">
            {ROOM_OPTIONS.map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => onChange({ ...value, rooms: r })}
                aria-pressed={value.rooms === r}
                className={clsx(
                  "px-3 py-1.5 text-sm transition-colors",
                  value.rooms === r
                    ? "bg-brick text-paper"
                    : "bg-transparent text-ink hover:bg-brick-tint",
                  r !== ROOM_OPTIONS[0] && "border-l border-concrete/40"
                )}
              >
                {r}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label htmlFor="max-price" className="mb-1.5 block text-xs font-medium text-concrete">
            Preț maxim (€/lună)
          </label>
          <input
            id="max-price"
            type="number"
            min={0}
            step={50}
            placeholder="fără limită"
            value={value.maxPrice || ""}
            onChange={(e) => onChange({ ...value, maxPrice: Number(e.target.value) || 0 })}
            className="w-36 rounded-sm border border-concrete/40 bg-paper px-2.5 py-1.5 font-mono text-sm text-ink placeholder:text-concrete/60 focus:border-brick"
          />
        </div>

        <div className="flex items-end gap-2">
          <div>
            <label htmlFor="min-sqm" className="mb-1.5 block text-xs font-medium text-concrete">
              m² min
            </label>
            <input
              id="min-sqm"
              type="number"
              min={0}
              step={5}
              placeholder="0"
              value={value.minSqm || ""}
              onChange={(e) => onChange({ ...value, minSqm: Number(e.target.value) || 0 })}
              className="w-20 rounded-sm border border-concrete/40 bg-paper px-2.5 py-1.5 font-mono text-sm text-ink placeholder:text-concrete/60 focus:border-brick"
            />
          </div>
          <div>
            <label htmlFor="max-sqm" className="mb-1.5 block text-xs font-medium text-concrete">
              m² max
            </label>
            <input
              id="max-sqm"
              type="number"
              min={0}
              step={5}
              placeholder="∞"
              value={value.maxSqm || ""}
              onChange={(e) => onChange({ ...value, maxSqm: Number(e.target.value) || 0 })}
              className="w-20 rounded-sm border border-concrete/40 bg-paper px-2.5 py-1.5 font-mono text-sm text-ink placeholder:text-concrete/60 focus:border-brick"
            />
          </div>
        </div>

        <div>
          <label className="mb-1.5 block text-xs font-medium text-concrete">Tip proprietate</label>
          <div className="flex flex-wrap gap-1.5">
            {PROPERTY_TYPES.map((t) => (
              <ToggleChip
                key={t}
                active={value.propertyTypes.includes(t)}
                onClick={() =>
                  onChange({
                    ...value,
                    propertyTypes: value.propertyTypes.includes(t)
                      ? value.propertyTypes.filter((p) => p !== t)
                      : [...value.propertyTypes, t],
                  })
                }
              >
                {t}
              </ToggleChip>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
