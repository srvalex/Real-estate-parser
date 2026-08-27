import type { PropertyType } from "@/lib/types";

// Small line-art keyed to property type — stands in for a photo instead of a
// broken-image icon, which is one of the fastest tells of an unfinished product.
export function MissingPhotoFallback({ type }: { type: PropertyType }) {
  const common = {
    className: "h-10 w-10 text-concrete/70",
    strokeWidth: 1.4,
    fill: "none",
    stroke: "currentColor",
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };

  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-2 bg-paper-dim">
      {type === "Casa/Vila" ? (
        <svg viewBox="0 0 48 48" {...common}>
          <path d="M6 24 24 8l18 16" />
          <path d="M10 22v18h28V22" />
          <path d="M20 40V28h8v12" />
        </svg>
      ) : type === "Garsoniera" || type === "Studio" ? (
        <svg viewBox="0 0 48 48" {...common}>
          <rect x="9" y="9" width="30" height="30" rx="1.5" />
          <path d="M17 9v30M31 9v30M9 22h30" />
        </svg>
      ) : (
        <svg viewBox="0 0 48 48" {...common}>
          <rect x="8" y="6" width="32" height="36" rx="1.5" />
          <path d="M15 14h4v4h-4zM23 14h4v4h-4zM31 14h4v4h-4z" />
          <path d="M15 23h4v4h-4zM23 23h4v4h-4zM31 23h4v4h-4z" />
          <path d="M21 42V33h6v9" />
        </svg>
      )}
      <span className="font-mono text-[0.65rem] uppercase tracking-wide text-concrete/70">Fără fotografii</span>
    </div>
  );
}
