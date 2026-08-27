import { SearchX } from "lucide-react";

export function EmptyState({
  suggestion,
}: {
  suggestion: { message: string; actionLabel: string; onRelax: () => void } | null;
}) {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-3 rounded-lg border border-dashed border-concrete/40 px-6 py-16 text-center">
      <SearchX className="h-8 w-8 text-concrete" strokeWidth={1.5} />
      <p className="text-sm text-concrete">
        {suggestion ? suggestion.message : "Niciun anunț nu se potrivește criteriilor tale."}
      </p>
      {suggestion && (
        <button
          type="button"
          onClick={suggestion.onRelax}
          className="rounded-sm border border-brick px-3 py-1.5 text-sm font-medium text-brick hover:bg-brick-tint"
        >
          {suggestion.actionLabel}
        </button>
      )}
    </div>
  );
}
