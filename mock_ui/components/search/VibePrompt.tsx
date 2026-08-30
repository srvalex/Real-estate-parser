"use client";

import { useState } from "react";
import { Check, ChevronDown, Search, SlidersHorizontal, Sparkles } from "lucide-react";
import clsx from "clsx";
import type { HardFilters, VibeFilters } from "@/lib/types";
import { formatVibeFilterValue, VIBE_FILTER_LABELS } from "@/lib/nlpFilters";
import { TEMPLATE_PHOTOS } from "@/lib/templatePhotos";
import { HardFiltersPanel } from "./HardFiltersPanel";

const SUGGESTIONS = [
  "luminos, aproape de metrou",
  "bucătărie mare, renovat recent",
  "liniștit, parc în apropiere",
  "mobilat, parcare inclusă",
];

export function VibePrompt({
  value,
  onChange,
  detected,
  selectedPhotos,
  onChangePhotos,
  hardFilters,
  onChangeHardFilters,
  autoFilledFields,
  hardFilterSummary,
  onSubmit,
}: {
  value: string;
  onChange: (v: string) => void;
  detected: VibeFilters;
  selectedPhotos: string[];
  onChangePhotos: (ids: string[]) => void;
  hardFilters: HardFilters;
  onChangeHardFilters: (next: HardFilters) => void;
  autoFilledFields: Set<string>;
  hardFilterSummary: string[];
  onSubmit?: () => void;
}) {
  const detectedKeys = Object.keys(detected) as (keyof VibeFilters)[];
  const [photosOpen, setPhotosOpen] = useState(true);
  const [filtersOpen, setFiltersOpen] = useState(true);

  function addSuggestion(s: string) {
    onChange(value.trim() ? `${value.trim()}, ${s}` : s);
  }

  function togglePhoto(id: string) {
    onChangePhotos(selectedPhotos.includes(id) ? selectedPhotos.filter((p) => p !== id) : [...selectedPhotos, id]);
  }

  return (
    <div className="rounded-lg border border-brick/20 bg-white shadow-hover">
      <div className="p-5 sm:p-7">
        <label htmlFor="vibe" className="mb-1.5 block font-display text-xl italic text-ink sm:text-2xl">
          Ce fel de locuință cauți?
        </label>
        <p className="mb-4 text-sm text-concrete">
          Scrie liber: dotări, atmosferă, preferințe. Restul îl deducem noi.
        </p>
        <textarea
          id="vibe"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) onSubmit?.();
          }}
          rows={4}
          placeholder="apartament luminos, bucătărie modernă, liniștit, parc în apropiere, renovat recent…"
          className="w-full resize-none rounded-sm border border-concrete/40 bg-paper px-4 py-3.5 text-base text-ink placeholder:text-concrete/50 focus:border-brick"
        />

        {!value.trim() && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => addSuggestion(s)}
                className="rounded-pill border border-concrete/30 bg-paper px-3 py-1 text-xs text-concrete transition-colors hover:border-brick/50 hover:text-brick"
              >
                {s}
              </button>
            ))}
          </div>
        )}

        {detectedKeys.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <span className="mr-0.5 text-xs text-concrete">Am înțeles:</span>
            {detectedKeys.map((key) => (
              <span
                key={key}
                className="inline-flex items-center gap-1 rounded-pill border border-dashed border-brick/50 px-2.5 py-1 text-xs text-brick"
                title={VIBE_FILTER_LABELS[key]}
              >
                <Sparkles className="h-3 w-3" strokeWidth={2.25} />
                {formatVibeFilterValue(key, detected[key]!)}
              </span>
            ))}
          </div>
        )}

        <div className="mt-4 border-t border-concrete/15 pt-4">
          <button
            type="button"
            onClick={() => setFiltersOpen((o) => !o)}
            aria-expanded={filtersOpen}
            className="flex w-full items-center justify-between gap-2 text-left"
          >
            <span className="flex items-center gap-1.5 text-xs font-medium text-ink">
              <SlidersHorizontal className="h-3.5 w-3.5 text-concrete" />
              Filtre exacte
              <span className="font-mono text-[0.65rem] font-normal text-concrete">(cameră, preț, suprafață)</span>
            </span>
            <span className="flex items-center gap-2">
              {!filtersOpen &&
                hardFilterSummary.map((s) => (
                  <span key={s} className="hidden font-mono text-[0.65rem] text-brick sm:inline">
                    {s}
                  </span>
                ))}
              <ChevronDown
                className={clsx("h-4 w-4 shrink-0 text-concrete transition-transform", filtersOpen && "rotate-180")}
              />
            </span>
          </button>
          {filtersOpen && (
            <div className="mt-3">
              <HardFiltersPanel value={hardFilters} onChange={onChangeHardFilters} autoFilledFields={autoFilledFields} bare />
            </div>
          )}
        </div>

        <div className="mt-4 border-t border-concrete/15 pt-4">
          <button
            type="button"
            onClick={() => setPhotosOpen((o) => !o)}
            aria-expanded={photosOpen}
            className="flex w-full items-center justify-between gap-2 text-left"
          >
            <span>
              <p className="text-xs font-medium text-ink">
                Aspect vizual (opțional)
                {selectedPhotos.length > 0 && (
                  <span className="ml-1.5 font-mono text-[0.65rem] font-normal text-brick">
                    {selectedPhotos.length} selectate
                  </span>
                )}
              </p>
              <p className="mt-0.5 text-xs text-concrete">
                Alege una sau mai multe fotografii de referință — ordonăm și după similaritate vizuală.
              </p>
            </span>
            <ChevronDown
              className={clsx("h-4 w-4 shrink-0 text-concrete transition-transform", photosOpen && "rotate-180")}
            />
          </button>
          {photosOpen && (
            <div className="mt-2.5 grid grid-cols-4 gap-2">
              {TEMPLATE_PHOTOS.map((photo) => {
                const isSelected = selectedPhotos.includes(photo.id);
                return (
                  <button
                    key={photo.id}
                    type="button"
                    onClick={() => togglePhoto(photo.id)}
                    aria-pressed={isSelected}
                    className={clsx(
                      "group relative overflow-hidden rounded-sm border-2 transition-colors",
                      isSelected ? "border-brick" : "border-transparent hover:border-concrete/40"
                    )}
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={`/template-photos/${photo.file}`}
                      alt={photo.label}
                      className="aspect-square w-full object-cover"
                    />
                    {isSelected && (
                      <span className="absolute right-1 top-1 flex h-4 w-4 items-center justify-center rounded-full bg-brick text-paper">
                        <Check className="h-2.5 w-2.5" strokeWidth={3} />
                      </span>
                    )}
                    <span className="absolute inset-x-0 bottom-0 bg-ink/70 px-1 py-0.5 text-center text-[0.62rem] leading-tight text-paper">
                      {photo.label}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {onSubmit && (
        <button
          type="button"
          onClick={onSubmit}
          className="flex w-full items-center justify-center gap-2 rounded-b-lg border-t border-brick/15 bg-ink py-3.5 text-sm font-medium text-paper transition-colors hover:bg-brick"
        >
          <Search className="h-4 w-4" /> Caută locuințe
        </button>
      )}
    </div>
  );
}
