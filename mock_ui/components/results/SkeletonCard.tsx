export function SkeletonCard() {
  return (
    <div className="overflow-hidden rounded-lg border border-concrete/20 bg-white/40">
      <div className="h-48 w-full animate-pulse bg-concrete/15" />
      <div className="space-y-2.5 p-4">
        <div className="h-4 w-3/4 animate-pulse rounded-sm bg-concrete/15" />
        <div className="h-5 w-1/2 animate-pulse rounded-sm bg-concrete/15" />
        <div className="h-3 w-full animate-pulse rounded-sm bg-concrete/10" />
        <div className="h-3 w-5/6 animate-pulse rounded-sm bg-concrete/10" />
      </div>
    </div>
  );
}
