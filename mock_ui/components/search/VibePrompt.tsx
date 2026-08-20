"use client";

import { Sparkles } from "lucide-react";
import type { VibeFilters } from "@/lib/types";
import { formatVibeFilterValue, VIBE_FILTER_LABELS } from "@/lib/nlpFilters";

export function VibePrompt({
  value,
  onChange,
  detected,
}: {
  value: string;
  onChange: (v: string) => void;
  detected: VibeFilters;
}) {
  const detectedKeys = Object.keys(detected) as (keyof VibeFilters)[];

  return (
    <div className="rounded-lg border border-brick/25 bg-brick-tint p-4 sm:p-5">
      <label htmlFor="vibe" className="mb-1 flex items-center gap-1.5 font-display text-lg italic text-ink">
        Ce fel de locuință cauți?
      </label>
      <p className="mb-3 text-xs text-concrete">
        Dotări, atmosferă, preferințe — ex. &ldquo;bucătărie mare, liniștit, aproape de metrou, renovat&rdquo;
      </p>
      <textarea
        id="vibe"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={3}
        placeholder="apartament luminos, bucătărie modernă, liniștit, parc în apropiere, renovat recent…"
        className="w-full resize-none rounded-sm border border-concrete/40 bg-paper px-3 py-2.5 text-sm text-ink placeholder:text-concrete/60 focus:border-brick"
      />
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
  );
}
