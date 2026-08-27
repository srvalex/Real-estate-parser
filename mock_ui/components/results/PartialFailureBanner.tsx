import { TriangleAlert } from "lucide-react";

export function PartialFailureBanner({ message }: { message: string }) {
  return (
    <div className="flex items-center gap-2 rounded-sm border border-gold/40 bg-gold/10 px-3 py-2 text-sm text-ink">
      <TriangleAlert className="h-4 w-4 shrink-0 text-gold" />
      <span>
        Ordonarea după potrivire nu este disponibilă momentan ({message}). Afișăm rezultatele neordonate.
      </span>
    </div>
  );
}
