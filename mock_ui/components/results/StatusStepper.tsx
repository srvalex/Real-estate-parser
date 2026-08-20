"use client";

import { Check, FileSearch, Loader2, SlidersHorizontal, TriangleAlert } from "lucide-react";
import clsx from "clsx";
import type { SourceState } from "@/lib/types";

export type PipelineStage = "reading" | "searching" | "ranking";

const STAGES: { key: PipelineStage; label: string; icon: typeof FileSearch }[] = [
  { key: "reading", label: "Citim promptul tău", icon: FileSearch },
  { key: "searching", label: "Căutăm în surse", icon: Loader2 },
  { key: "ranking", label: "Ordonăm după potrivire", icon: SlidersHorizontal },
];

export function StatusStepper({ stage, sources }: { stage: PipelineStage; sources: SourceState[] }) {
  const activeIndex = STAGES.findIndex((s) => s.key === stage);

  return (
    <div className="mx-auto max-w-lg py-10">
      <ol className="flex items-center justify-between">
        {STAGES.map((s, i) => {
          const isDone = i < activeIndex;
          const isActive = i === activeIndex;
          const Icon = s.icon;
          return (
            <li key={s.key} className="flex flex-1 flex-col items-center text-center">
              <div className="flex w-full items-center">
                <span
                  className={clsx(
                    "h-px flex-1",
                    i === 0 ? "invisible" : isDone || isActive ? "bg-brick" : "bg-concrete/30"
                  )}
                />
                <span
                  className={clsx(
                    "flex h-9 w-9 shrink-0 items-center justify-center rounded-full border-2 transition-colors",
                    isDone && "border-pine bg-pine text-paper",
                    isActive && "border-brick bg-brick text-paper",
                    !isDone && !isActive && "border-concrete/40 text-concrete"
                  )}
                >
                  {isDone ? (
                    <Check className="h-4 w-4" />
                  ) : (
                    <Icon className={clsx("h-4 w-4", isActive && s.key === "searching" && "animate-spin")} />
                  )}
                </span>
                <span
                  className={clsx(
                    "h-px flex-1",
                    i === STAGES.length - 1 ? "invisible" : isDone ? "bg-brick" : "bg-concrete/30"
                  )}
                />
              </div>
              <span className={clsx("mt-2 text-xs", isActive ? "font-medium text-ink" : "text-concrete")}>
                {s.label}
              </span>
            </li>
          );
        })}
      </ol>

      {stage === "searching" && (
        <ul className="mt-6 flex justify-center gap-4 font-mono text-xs text-concrete">
          {sources.map((s) => (
            <li key={s.platform} className="flex items-center gap-1.5">
              {s.status === "done" && <Check className="h-3.5 w-3.5 text-pine" />}
              {s.status === "slow" && <TriangleAlert className="h-3.5 w-3.5 text-gold" />}
              {(s.status === "loading" || s.status === "pending") && (
                <Loader2 className="h-3.5 w-3.5 animate-spin text-brick" />
              )}
              {s.platform}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
