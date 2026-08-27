import Link from "next/link";
import { BarChart3 } from "lucide-react";

// Warm brick facade at sunset — Valentin Lacoste, via Unsplash (unsplash.com/photos/ZDtBOadvRrY).
// Free to use under the Unsplash License; sized/cropped through Unsplash's own image API.
const HERO_IMAGE_URL =
  "https://images.unsplash.com/photo-1777458522417-9c59944915aa?q=80&w=1600&auto=format&fit=crop";

export function Hero() {
  return (
    <div className="relative h-[360px] w-full overflow-hidden sm:h-[440px]">
      <img
        src={HERO_IMAGE_URL}
        alt="Fațadă de bloc în lumina serii"
        className="h-full w-full object-cover object-[center_30%]"
      />

      <Link
        href="/analytics"
        className="absolute right-4 top-4 inline-flex items-center gap-1.5 bg-ink/70 px-2.5 py-1.5 text-xs font-medium text-paper hover:bg-ink/85 sm:right-6 sm:top-6"
      >
        <BarChart3 className="h-3.5 w-3.5" /> Analiză de piață
      </Link>

      <div className="absolute inset-x-0 bottom-0 px-4 pb-14 sm:pb-16">
        <div className="mx-auto max-w-xl bg-ink/75 px-5 py-5 text-center sm:px-8 sm:py-6">
          <h1 className="font-display text-3xl italic leading-tight text-paper sm:text-5xl">
            Spune-i ce cauți la o locuință.
          </h1>
          <p className="mt-3 text-sm text-paper/80 sm:text-base">
            Descrie apartamentul cu cuvintele tale. Restul e treaba noastră.
          </p>
        </div>
      </div>
    </div>
  );
}
