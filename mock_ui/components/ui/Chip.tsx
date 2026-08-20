"use client";

import { type ReactNode } from "react";
import clsx from "clsx";

export function ToggleChip({
  active,
  onClick,
  children,
  icon,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-sm border px-3 py-1.5 text-sm transition-colors",
        active
          ? "border-brick bg-brick text-paper"
          : "border-concrete/40 bg-transparent text-ink hover:border-brick/60 hover:bg-brick-tint"
      )}
    >
      {icon}
      {children}
    </button>
  );
}

export function StaticPill({ children, tone = "brick" }: { children: ReactNode; tone?: "brick" | "pine" | "gold" | "concrete" }) {
  const toneClasses: Record<string, string> = {
    brick: "border-brick/40 bg-brick/10 text-brick",
    pine: "border-pine/40 bg-pine/10 text-pine",
    gold: "border-gold/40 bg-gold/10 text-gold",
    concrete: "border-concrete/40 bg-concrete/10 text-ink",
  };
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-sm border px-2.5 py-1 text-xs font-medium",
        toneClasses[tone]
      )}
    >
      {children}
    </span>
  );
}
