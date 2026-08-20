import type { ReactNode } from "react";

export function ChartCard({ title, children, className = "" }: { title: string; children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-lg border border-concrete/25 bg-white/40 p-4 sm:p-5 ${className}`}>
      <h3 className="mb-3 font-display text-base text-ink">{title}</h3>
      {children}
    </div>
  );
}

export const tooltipStyle = {
  contentStyle: {
    background: "#F7F4EE",
    border: "1px solid #8C857955",
    borderRadius: 4,
    fontSize: 12,
    fontFamily: "var(--font-body)",
    color: "#1E1C1A",
  },
  labelStyle: { color: "#1E1C1A", fontWeight: 600 },
  cursor: { fill: "#8C857912" },
};
