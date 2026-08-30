"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { motion, MotionConfig } from "framer-motion";
import { Hero } from "./Hero";
import { VibePrompt } from "./VibePrompt";
import { ZoneSelector } from "./ZoneSelector";
import { getLocations, toApiCity, toDisplayCity } from "@/lib/locations";
import { expandWithProximity } from "@/lib/zones";
import { extractVibeFilters } from "@/lib/nlpFilters";
import { buildQuery, hardFiltersFromQuery } from "@/lib/api";
import type { HardFilters } from "@/lib/types";

const LOCATIONS = getLocations();

const DEFAULT_HARD_FILTERS: HardFilters = {
  maxPrice: 0,
  rooms: "Orice",
  minSqm: 0,
  maxSqm: 0,
  propertyTypes: [],
};

export function SearchExperience() {
  const router = useRouter();
  const incomingParams = useSearchParams();

  // A /results search can link back here via "Căutare nouă" — rehydrate
  // the form from that URL so going back doesn't throw away what was
  // just searched. Read once, at mount, from whatever query string this
  // page was opened with; the form is uncontrolled by the URL afterwards.
  const [hardFilters, setHardFilters] = useState<HardFilters>(() =>
    incomingParams.toString() ? hardFiltersFromQuery(incomingParams) : DEFAULT_HARD_FILTERS
  );
  const [vibe, setVibe] = useState(() => incomingParams.get("vibe") ?? "");
  const [selectedPhotos, setSelectedPhotos] = useState<string[]>(() => {
    const raw = incomingParams.get("template_photos");
    return raw ? raw.split(",").filter(Boolean) : [];
  });
  const [selectedCity, setSelectedCity] = useState<string | null>(() => {
    const city = incomingParams.get("city");
    return city ? toDisplayCity(city) : null;
  });
  const [zones, setZones] = useState<string[]>(() => {
    const raw = incomingParams.get("districts");
    return raw ? raw.split(",").filter(Boolean) : [];
  });
  const [includeProximity, setIncludeProximity] = useState(() => Boolean(incomingParams.get("nearby_districts")));
  const [zoneError, setZoneError] = useState<string | null>(null);

  const [touchedHardFilters, setTouchedHardFilters] = useState<Set<string>>(new Set());

  // No separate "Tot orașul" toggle — a city selected with zero
  // neighbourhoods picked just means "search the whole city".
  const wholeCity = zones.length === 0;

  const liveVibeFilters = useMemo(() => extractVibeFilters(vibe), [vibe]);
  const proximityExtra = useMemo(() => (zones.length ? expandWithProximity(zones) : []), [zones]);

  // Tri-state auto-fill (unset / user-set / vibe-inferred), same principle
  // documented in MIGRATION_PLAN.md for the future agent backfill: only
  // fields the user hasn't touched are eligible to be filled from the
  // free-text prompt, and a field they explicitly set (including via an
  // EmptyState "relax this filter" action) never gets silently overwritten
  // again just because the vibe text still mentions it.
  function handleHardFiltersChange(next: HardFilters) {
    setTouchedHardFilters((prev) => {
      const touched = new Set(prev);
      if (next.rooms !== hardFilters.rooms) touched.add("rooms");
      if (next.maxPrice !== hardFilters.maxPrice) touched.add("maxPrice");
      if (next.minSqm !== hardFilters.minSqm) touched.add("minSqm");
      if (next.maxSqm !== hardFilters.maxSqm) touched.add("maxSqm");
      if (next.propertyTypes.join(",") !== hardFilters.propertyTypes.join(",")) touched.add("propertyTypes");
      return touched;
    });
    setHardFilters(next);
  }

  useEffect(() => {
    setHardFilters((prev) => {
      const next = { ...prev };
      let changed = false;

      if (!touchedHardFilters.has("rooms")) {
        const detected = (liveVibeFilters.ROOM_COUNT as HardFilters["rooms"]) ?? "Orice";
        if (next.rooms !== detected) {
          next.rooms = detected;
          changed = true;
        }
      }
      if (!touchedHardFilters.has("propertyTypes")) {
        const detected = liveVibeFilters.PROPERTY_TYPE ? [liveVibeFilters.PROPERTY_TYPE as HardFilters["propertyTypes"][number]] : [];
        if (next.propertyTypes.join(",") !== detected.join(",")) {
          next.propertyTypes = detected;
          changed = true;
        }
      }
      if (!touchedHardFilters.has("maxPrice")) {
        const detected = (liveVibeFilters.PRICE_MAX as number) ?? 0;
        if (next.maxPrice !== detected) {
          next.maxPrice = detected;
          changed = true;
        }
      }
      if (!touchedHardFilters.has("minSqm")) {
        const detected = (liveVibeFilters.AREA_MIN as number) ?? 0;
        if (next.minSqm !== detected) {
          next.minSqm = detected;
          changed = true;
        }
      }
      if (!touchedHardFilters.has("maxSqm")) {
        const detected = (liveVibeFilters.AREA_MAX as number) ?? 0;
        if (next.maxSqm !== detected) {
          next.maxSqm = detected;
          changed = true;
        }
      }

      return changed ? next : prev;
    });
  }, [liveVibeFilters, touchedHardFilters]);

  const autoFilledFields = useMemo(() => {
    const s = new Set<string>();
    if (!touchedHardFilters.has("rooms") && hardFilters.rooms !== "Orice") s.add("rooms");
    if (!touchedHardFilters.has("propertyTypes") && hardFilters.propertyTypes.length > 0) s.add("propertyTypes");
    if (!touchedHardFilters.has("maxPrice") && hardFilters.maxPrice > 0) s.add("maxPrice");
    if (!touchedHardFilters.has("minSqm") && hardFilters.minSqm > 0) s.add("minSqm");
    if (!touchedHardFilters.has("maxSqm") && hardFilters.maxSqm > 0) s.add("maxSqm");
    return s;
  }, [touchedHardFilters, hardFilters]);

  const hardFilterSummary = useMemo(() => {
    const parts: string[] = [];
    if (hardFilters.rooms !== "Orice") parts.push(`${hardFilters.rooms} camere`);
    if (hardFilters.maxPrice > 0) parts.push(`≤ ${hardFilters.maxPrice} €`);
    if (hardFilters.minSqm > 0 || hardFilters.maxSqm > 0) {
      parts.push(`${hardFilters.minSqm || 0}–${hardFilters.maxSqm || "∞"} m²`);
    }
    if (hardFilters.propertyTypes.length > 0) parts.push(hardFilters.propertyTypes.join(", "));
    return parts;
  }, [hardFilters]);

  function handleSearch() {
    if (!selectedCity) {
      setZoneError("Selectează un oraș sau o zonă de căutare.");
      return;
    }
    setZoneError(null);

    const qs = buildQuery({
      city: toApiCity(selectedCity),
      wholeCity,
      zones,
      nearbyZones: includeProximity ? proximityExtra : [],
      hardFilters,
      vibe,
      templatePhotos: selectedPhotos,
    });
    router.push(`/results?${qs}`);
  }

  return (
    <MotionConfig reducedMotion="user">
      <div className="min-h-screen">
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.35, ease: "easeOut" }}>
          <Hero />
          <div className="mx-auto max-w-2xl space-y-4 px-4 pb-24">
            <div className="relative z-10 mt-4 rounded-lg border border-brick/20 bg-white p-4 shadow-hover sm:mt-6 sm:p-5">
              <ZoneSelector
                locations={LOCATIONS}
                selectedCity={selectedCity}
                onChangeCity={(city) => {
                  setSelectedCity(city);
                  if (city) setZoneError(null);
                  if (city !== "București") setIncludeProximity(false);
                }}
                selectedZones={zones}
                onChangeZones={(z) => setZones(z)}
                includeProximity={includeProximity}
                onChangeIncludeProximity={setIncludeProximity}
                proximityCount={proximityExtra.length}
                proximityAvailable={selectedCity === "București" && !wholeCity}
              />
              {zoneError && <p className="mt-3 text-sm text-brick">{zoneError}</p>}
            </div>

            <VibePrompt
              value={vibe}
              onChange={setVibe}
              detected={liveVibeFilters}
              selectedPhotos={selectedPhotos}
              onChangePhotos={setSelectedPhotos}
              hardFilters={hardFilters}
              onChangeHardFilters={handleHardFiltersChange}
              autoFilledFields={autoFilledFields}
              hardFilterSummary={hardFilterSummary}
              onSubmit={handleSearch}
            />
          </div>
        </motion.div>
      </div>
    </MotionConfig>
  );
}
