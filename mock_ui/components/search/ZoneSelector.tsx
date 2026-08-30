"use client";

import { useMemo, useRef, useState } from "react";
import { ChevronRight, MapPin, Search, X } from "lucide-react";
import clsx from "clsx";
import type { LocationCity, LocationDistrict } from "@/lib/locations";

function normalize(text: string): string {
  return text
    .toLowerCase()
    .replace(/ă/g, "a")
    .replace(/â/g, "a")
    .replace(/î/g, "i")
    .replace(/ș/g, "s")
    .replace(/ş/g, "s")
    .replace(/ț/g, "t")
    .replace(/ţ/g, "t");
}

type Scope =
  | { level: "root" }
  | { level: "city"; city: LocationCity }
  | { level: "district"; city: LocationCity; district: LocationDistrict };

// Walks the comma-separated segments the user has typed, descending one
// level per segment. A segment before the last one keeps the old lenient
// exact-or-substring match (so an abbreviated "Buc, Sect 2, Stefan" still
// resolves once the user has moved on from it). The *last* segment only
// auto-descends on an EXACT (diacritic/case-insensitive) match — an exact
// match unambiguously means "fully specified", so it's safe to commit to
// it without waiting for a trailing comma the user never has to type. A
// non-exact last segment is returned as `live`, the fuzzy filter text for
// whatever the caller renders at the current scope — this is also what
// preserves the "skip-district" search (e.g. "București, Ștefan cel
// Mare"), since a district name never exactly matches a zone name.
function resolveScope(rawSegments: string[], locations: LocationCity[]): { scope: Scope; live: string } {
  let scope: Scope = { level: "root" };

  for (let i = 0; i < rawSegments.length; i++) {
    const raw = rawSegments[i];
    const norm = normalize(raw);
    const isLast = i === rawSegments.length - 1;

    if (!norm) {
      if (isLast) return { scope, live: "" };
      continue;
    }

    if (scope.level === "root") {
      const exact = locations.find((l) => normalize(l.city) === norm);
      if (exact) {
        scope = { level: "city", city: exact };
        continue;
      }
      if (isLast) return { scope, live: raw };
      const fuzzy = locations.find((l) => normalize(l.city).includes(norm));
      if (!fuzzy) return { scope, live: raw };
      scope = { level: "city", city: fuzzy };
      continue;
    }

    if (scope.level === "city") {
      const cityAtScope = scope.city;
      if (!cityAtScope.districts) {
        // Flat city: no deeper scope, but an exact zone match is still a
        // complete, unambiguous pick — clear `live` so the dropdown falls
        // back to showing every zone again instead of re-filtering by name.
        const zoneMatch = cityAtScope.zones.find((z) => normalize(z) === norm);
        if (zoneMatch && isLast) return { scope, live: "" };
        return { scope, live: raw };
      }
      const districts: LocationDistrict[] = cityAtScope.districts;
      const exact: LocationDistrict | undefined = districts.find((d: LocationDistrict) => normalize(d.name) === norm);
      if (exact) {
        scope = { level: "district", city: scope.city, district: exact };
        continue;
      }
      if (isLast) return { scope, live: raw };
      const fuzzy: LocationDistrict | undefined = districts.find((d: LocationDistrict) =>
        normalize(d.name).includes(norm)
      );
      if (!fuzzy) return { scope, live: raw };
      scope = { level: "district", city: scope.city, district: fuzzy };
      continue;
    }

    // scope.level === "district": leaf level, nothing further to descend
    // into — same exact-zone-match courtesy as the flat-city case above.
    const zoneMatch = scope.district.zones.find((z) => normalize(z) === norm);
    if (zoneMatch && isLast) return { scope, live: "" };
    return { scope, live: raw };
  }

  return { scope, live: "" };
}

type Row =
  | { kind: "city"; key: string; label: string; onDrill: () => void }
  | { kind: "district"; key: string; label: string; allSelected: boolean; onDrill: () => void; onToggleAll: () => void }
  | { kind: "zone"; key: string; label: string; sublabel: string; selected: boolean; onSelect: () => void };

export function ZoneSelector({
  locations,
  selectedCity,
  onChangeCity,
  selectedZones,
  onChangeZones,
  includeProximity,
  onChangeIncludeProximity,
  proximityCount,
  proximityAvailable = true,
}: {
  locations: LocationCity[];
  selectedCity: string | null;
  onChangeCity: (city: string | null) => void;
  selectedZones: string[];
  onChangeZones: (zones: string[]) => void;
  includeProximity: boolean;
  onChangeIncludeProximity: (v: boolean) => void;
  proximityCount: number;
  proximityAvailable?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const selectedSet = new Set(selectedZones);

  // A search can only span one city at a time — neighbourhood names collide
  // across cities (e.g. "Centru" in both Cluj-Napoca and Iași), so a bare
  // zone-name array is meaningless without knowing which city it belongs to.
  // Picking a zone in a different city than the one already active replaces
  // the whole selection instead of merging into it.
  function commitZones(city: string, zones: string[]) {
    onChangeZones(zones);
    onChangeCity(zones.length > 0 ? city : null);
  }

  function toggleZone(city: string, name: string) {
    if (city !== selectedCity) {
      commitZones(city, [name]);
      return;
    }
    commitZones(city, selectedSet.has(name) ? selectedZones.filter((z) => z !== name) : [...selectedZones, name]);
  }

  function toggleDistrictZones(city: string, zones: string[]) {
    if (city !== selectedCity) {
      commitZones(city, [...zones]);
      return;
    }
    const allSelected = zones.every((n) => selectedSet.has(n));
    commitZones(
      city,
      allSelected ? selectedZones.filter((z) => !zones.includes(z)) : [...new Set([...selectedZones, ...zones])]
    );
  }

  const { scope, rows, live } = useMemo(() => {
    const rawSegments = query.split(",").map((s) => s.trim());
    const { scope: currentScope, live: liveRaw } = resolveScope(rawSegments, locations);
    const live = normalize(liveRaw);

    function districtRow(city: LocationCity, d: LocationDistrict): Row {
      const allSelected =
        city.city === selectedCity && d.zones.length > 0 && d.zones.every((n) => selectedSet.has(n));
      return {
        kind: "district",
        key: `district:${city.city}:${d.name}`,
        label: d.name,
        allSelected,
        onDrill: () => setQuery(`${city.city}, ${d.name}`),
        onToggleAll: () => toggleDistrictZones(city.city, d.zones),
      };
    }

    function zoneRow(city: LocationCity, d: LocationDistrict | null, z: string): Row {
      return {
        kind: "zone",
        key: `zone:${city.city}:${d?.name ?? ""}:${z}`,
        label: z,
        sublabel: d ? `${d.name}, ${city.city}` : city.city,
        selected: city.city === selectedCity && selectedSet.has(z),
        onSelect: () => {
          toggleZone(city.city, z);
          setQuery(d ? `${city.city}, ${d.name}` : city.city);
        },
      };
    }

    const out: Row[] = [];

    if (currentScope.level === "root") {
      if (!live) return { scope: currentScope, rows: out, live };

      // Cities are the primary action at this level, so they're always
      // their own group at the top — a city name matching never also
      // dumps every one of its districts into the list below it (that
      // only happens once the user actually drills into that city).
      for (const loc of locations) {
        if (normalize(loc.city).includes(live)) {
          out.push({ kind: "city", key: `city:${loc.city}`, label: loc.city, onDrill: () => setQuery(loc.city) });
        }
      }

      for (const loc of locations) {
        if (loc.districts) {
          for (const d of loc.districts) {
            if (normalize(d.name).includes(live)) out.push(districtRow(loc, d));
          }
          for (const d of loc.districts) {
            for (const z of d.zones) {
              if (normalize(z).includes(live)) out.push(zoneRow(loc, d, z));
            }
          }
        } else {
          for (const z of loc.zones) {
            if (normalize(z).includes(live)) out.push(zoneRow(loc, null, z));
          }
        }
      }
    } else if (currentScope.level === "city") {
      const loc = currentScope.city;
      if (loc.districts) {
        for (const d of loc.districts) {
          if (!live || normalize(d.name).includes(live)) out.push(districtRow(loc, d));
        }
        if (live) {
          for (const d of loc.districts) {
            for (const z of d.zones) {
              if (normalize(z).includes(live)) out.push(zoneRow(loc, d, z));
            }
          }
        }
      } else {
        for (const z of loc.zones) {
          if (!live || normalize(z).includes(live)) out.push(zoneRow(loc, null, z));
        }
      }
    } else {
      const { city, district } = currentScope;
      for (const z of district.zones) {
        if (!live || normalize(z).includes(live)) out.push(zoneRow(city, district, z));
      }
    }

    return { scope: currentScope, rows: out.slice(0, 30), live };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, locations, selectedZones, selectedCity]);

  const chips = useMemo(() => {
    const items: { key: string; label: string; remove: () => void }[] = [];
    const consumed = new Set<string>();
    // Chips are always read against the single active city — with
    // colliding neighbourhood names across cities, matching selectedZones
    // against every city's districts (rather than just selectedCity's)
    // could label a chip with the wrong city's district name.
    const activeCity = selectedCity ? locations.find((l) => l.city === selectedCity) : undefined;

    if (activeCity?.districts) {
      for (const d of activeCity.districts) {
        const allSelected = d.zones.length > 0 && d.zones.every((n) => selectedSet.has(n));
        if (allSelected) {
          d.zones.forEach((n) => consumed.add(n));
          items.push({
            key: `${activeCity.city}:${d.name}`,
            label: d.name,
            remove: () => commitZones(activeCity.city, selectedZones.filter((z) => !d.zones.includes(z))),
          });
        }
      }
    }
    for (const z of selectedZones) {
      if (consumed.has(z)) continue;
      items.push({
        key: z,
        label: z,
        remove: () => commitZones(selectedCity ?? "", selectedZones.filter((x) => x !== z)),
      });
    }
    return items;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locations, selectedZones, selectedCity]);

  const breadcrumb =
    scope.level === "city" ? scope.city.city : scope.level === "district" ? `${scope.city.city} › ${scope.district.name}` : null;

  return (
    <div>
      <p className="mb-3 font-mono text-[0.68rem] uppercase tracking-[0.14em] text-concrete">Zonă de căutare</p>

      <div className="relative rounded-sm border border-concrete/40 bg-paper focus-within:border-brick">
        <div className="flex items-center gap-2 px-3 py-2.5">
          <Search className="h-4 w-4 shrink-0 text-concrete" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => setOpen(true)}
            onBlur={() => {
              setOpen(false);
              // Leaving the box with a fully-typed city and no
              // neighbourhood picked implies "search the whole city" —
              // there's no separate "Tot orașul" option to click.
              if (scope.level === "city" && !live && scope.city.city !== selectedCity) {
                onChangeCity(scope.city.city);
                onChangeZones([]);
              }
            }}
            placeholder="Oraș, sector sau cartier (ex. București, Sector 2, Ștefan cel Mare)"
            className="w-full bg-transparent text-sm text-ink placeholder:text-concrete/60 focus:outline-none"
          />
        </div>

        {chips.length > 0 && (
          <div className="flex flex-wrap gap-1.5 border-t border-concrete/20 px-3 py-2.5">
            {chips.map((chip) => (
              <span
                key={chip.key}
                className="inline-flex items-center gap-1 rounded-sm border border-brick/40 bg-brick-tint px-2 py-1 text-xs text-brick"
              >
                {chip.label}
                <button
                  type="button"
                  onMouseDown={(e) => {
                    e.preventDefault();
                    chip.remove();
                  }}
                  aria-label={`Elimină ${chip.label}`}
                  className="text-brick/70 hover:text-brick"
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
        )}

        {open && query.trim() && (
          <div className="absolute inset-x-0 top-full z-20 mt-1 max-h-80 overflow-y-auto rounded-sm border border-concrete/30 bg-white py-1 shadow-hover">
            {breadcrumb && (
              <p className="px-3 pb-1.5 pt-1 font-mono text-[0.68rem] uppercase tracking-[0.1em] text-concrete">
                {breadcrumb}
              </p>
            )}
            {rows.length === 0 ? (
              <p className="px-3 py-3 text-sm text-concrete">Niciun rezultat pentru &ldquo;{query}&rdquo;.</p>
            ) : (
              rows.map((row) => {
                if (row.kind === "city") {
                  return (
                    <button
                      key={row.key}
                      type="button"
                      onMouseDown={(e) => {
                        e.preventDefault();
                        row.onDrill();
                      }}
                      className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm font-semibold text-ink hover:bg-brick-tint"
                    >
                      <span>
                        {row.label}
                        <span className="ml-2 font-mono text-xs font-normal text-concrete">oraș</span>
                      </span>
                      <ChevronRight className="h-4 w-4 text-concrete" />
                    </button>
                  );
                }
                if (row.kind === "district") {
                  return (
                    <div key={row.key} className="flex items-center gap-1 pl-5 pr-2">
                      <button
                        type="button"
                        onMouseDown={(e) => {
                          e.preventDefault();
                          row.onDrill();
                        }}
                        className="flex flex-1 items-center justify-between gap-2 rounded-sm px-2 py-1.5 text-left text-sm text-ink hover:bg-brick-tint"
                      >
                        <span>{row.label}</span>
                        <span className="flex items-center gap-1.5 font-mono text-xs text-concrete">
                          sector
                          <ChevronRight className="h-3.5 w-3.5" />
                        </span>
                      </button>
                      <label
                        className="flex cursor-pointer items-center gap-1 px-1.5 py-1.5 text-xs text-concrete"
                        onMouseDown={(e) => e.preventDefault()}
                      >
                        <input
                          type="checkbox"
                          checked={row.allSelected}
                          onChange={row.onToggleAll}
                          className="h-3.5 w-3.5 accent-brick"
                        />
                        tot
                      </label>
                    </div>
                  );
                }
                return (
                  <button
                    key={row.key}
                    type="button"
                    onMouseDown={(e) => {
                      e.preventDefault();
                      row.onSelect();
                    }}
                    className={clsx(
                      "flex w-full items-center justify-between gap-2 py-1.5 pl-9 pr-3 text-left text-sm hover:bg-brick-tint",
                      row.selected ? "text-brick" : "text-ink"
                    )}
                  >
                    <span>{row.label}</span>
                    <span className="font-mono text-xs text-concrete">{row.sublabel}</span>
                  </button>
                );
              })
            )}
          </div>
        )}
      </div>

      {proximityAvailable && (
        <label className="mt-4 flex cursor-pointer items-center gap-2 text-sm text-ink">
          <input
            type="checkbox"
            checked={includeProximity}
            onChange={(e) => onChangeIncludeProximity(e.target.checked)}
            className="h-4 w-4 accent-brick"
          />
          <MapPin className="h-4 w-4 text-concrete" />
          Include cartiere vecine
          {includeProximity && proximityCount > 0 && (
            <span className="font-mono text-xs text-concrete">(+{proximityCount})</span>
          )}
        </label>
      )}
    </div>
  );
}
