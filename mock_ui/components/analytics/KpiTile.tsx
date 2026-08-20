export function KpiTile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-concrete/25 bg-white/40 p-4 text-center">
      <p className="font-mono text-[0.68rem] uppercase tracking-[0.12em] text-concrete">{label}</p>
      <p className="mt-1 font-display text-2xl text-ink">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-concrete">{hint}</p>}
    </div>
  );
}
