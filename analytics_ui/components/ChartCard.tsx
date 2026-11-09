import type { ReactNode } from "react";

export function ChartCard({ title, subtitle, children, className = "" }: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`rounded-lg border border-concrete/25 bg-white/40 p-4 sm:p-5 ${className}`}>
      <h3 className="font-display text-base text-ink">{title}</h3>
      {subtitle && <p className="mb-3 mt-0.5 text-xs text-concrete">{subtitle}</p>}
      <div className={subtitle ? "" : "mt-3"}>{children}</div>
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

export const CHART_PALETTE = ["#A8461F", "#3E4E3A", "#B8892B", "#8C8579", "#C97247", "#647A5E", "#D4AF63"];
