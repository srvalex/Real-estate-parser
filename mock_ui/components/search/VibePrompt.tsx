"use client";

import { Search, Sparkles } from "lucide-react";
import type { VibeFilters } from "@/lib/types";
import { formatVibeFilterValue, VIBE_FILTER_LABELS } from "@/lib/nlpFilters";

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
  onSubmit,
}: {
  value: string;
  onChange: (v: string) => void;
  detected: VibeFilters;
  onSubmit?: () => void;
}) {
  const detectedKeys = Object.keys(detected) as (keyof VibeFilters)[];

  function addSuggestion(s: string) {
    onChange(value.trim() ? `${value.trim()}, ${s}` : s);
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
