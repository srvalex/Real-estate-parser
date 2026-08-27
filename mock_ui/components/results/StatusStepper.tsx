"use client";

import { Check, Loader2, SlidersHorizontal } from "lucide-react";
import clsx from "clsx";

export type PipelineStage = "reading" | "searching";

const STAGES: { key: PipelineStage; label: string; icon: typeof SlidersHorizontal }[] = [
  { key: "reading", label: "Pregătim căutarea", icon: SlidersHorizontal },
  { key: "searching", label: "Interogăm baza de date și ordonăm după potrivire", icon: Loader2 },
];

export function StatusStepper({ stage }: { stage: PipelineStage }) {
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
              <span className={clsx("mt-2 max-w-[10rem] text-xs", isActive ? "font-medium text-ink" : "text-concrete")}>
                {s.label}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
