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

function resolveScope(confirmedSegments: string[], locations: LocationCity[]): Scope {
  let scope: Scope = { level: "root" };

  for (const raw of confirmedSegments) {
    const norm = normalize(raw);
    if (!norm) continue;

    if (scope.level === "root") {
      const city =
        locations.find((l) => normalize(l.city) === norm) ??
        locations.find((l) => normalize(l.city).includes(norm));
      if (!city) return scope;
      scope = { level: "city", city };
    } else if (scope.level === "city") {
      const districts = scope.city.districts;
      const district = districts
        ? districts.find((d) => normalize(d.name) === norm) ?? districts.find((d) => normalize(d.name).includes(norm))
        : undefined;
      if (!district) return scope;
      scope = { level: "district", city: scope.city, district };
    } else {
      return scope;
    }
  }

  return scope;
}

type Row =
  | { kind: "city"; key: string; label: string; onDrill: () => void }
  | { kind: "district"; key: string; label: string; allSelected: boolean; onDrill: () => void; onToggleAll: () => void }
  | { kind: "zone"; key: string; label: string; sublabel: string; selected: boolean; onSelect: () => void };

export function ZoneSelector({
  locations,
  selectedZones,
  onChangeZones,
  includeProximity,
  onChangeIncludeProximity,
  proximityCount,
}: {
  locations: LocationCity[];
  selectedZones: string[];
  onChangeZones: (zones: string[]) => void;
  includeProximity: boolean;
  onChangeIncludeProximity: (v: boolean) => void;
  proximityCount: number;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const selectedSet = new Set(selectedZones);

  function toggleZone(name: string) {
    onChangeZones(selectedSet.has(name) ? selectedZones.filter((z) => z !== name) : [...selectedZones, name]);
  }

  function toggleDistrictZones(zones: string[]) {
    const allSelected = zones.every((n) => selectedSet.has(n));
    onChangeZones(
      allSelected ? selectedZones.filter((z) => !zones.includes(z)) : [...new Set([...selectedZones, ...zones])]
    );
  }

  const { scope, rows } = useMemo(() => {
    const rawSegments = query.split(",").map((s) => s.trim());
    const liveRaw = rawSegments[rawSegments.length - 1];
    const live = normalize(liveRaw);
    const confirmed = rawSegments.slice(0, -1).filter(Boolean);
    const currentScope = resolveScope(confirmed, locations);

    function districtRow(city: LocationCity, d: LocationDistrict): Row {
      const allSelected = d.zones.length > 0 && d.zones.every((n) => selectedSet.has(n));
      return {
        kind: "district",
        key: `district:${city.city}:${d.name}`,
        label: d.name,
        allSelected,
        onDrill: () => setQuery(`${city.city}, ${d.name}, `),
        onToggleAll: () => toggleDistrictZones(d.zones),
      };
    }

    function zoneRow(city: LocationCity, d: LocationDistrict | null, z: string): Row {
      return {
        kind: "zone",
        key: `zone:${city.city}:${d?.name ?? ""}:${z}`,
        label: z,
        sublabel: d ? `${d.name}, ${city.city}` : city.city,
        selected: selectedSet.has(z),
        onSelect: () => {
          toggleZone(z);
          setQuery(d ? `${city.city}, ${d.name}, ` : `${city.city}, `);
        },
      };
    }

    const out: Row[] = [];

    if (currentScope.level === "root") {
      if (!live) return { scope: currentScope, rows: out };
      for (const loc of locations) {
        const cityMatches = normalize(loc.city).includes(live);
        if (loc.districts) {
          if (cityMatches) {
            out.push({ kind: "city", key: `city:${loc.city}`, label: loc.city, onDrill: () => setQuery(`${loc.city}, `) });
            for (const d of loc.districts) out.push(districtRow(loc, d));
          } else {
            for (const d of loc.districts) {
              if (normalize(d.name).includes(live)) out.push(districtRow(loc, d));
            }
          }
          for (const d of loc.districts) {
            for (const z of d.zones) {
              if (normalize(z).includes(live)) out.push(zoneRow(loc, d, z));
            }
          }
        } else {
          if (cityMatches) out.push({ kind: "city", key: `city:${loc.city}`, label: loc.city, onDrill: () => setQuery(`${loc.city}, `) });
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

    return { scope: currentScope, rows: out.slice(0, 30) };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, locations, selectedZones]);

  const chips = useMemo(() => {
    const items: { key: string; label: string; remove: () => void }[] = [];
    const consumed = new Set<string>();

    for (const loc of locations) {
      if (!loc.districts) continue;
      for (const d of loc.districts) {
        const allSelected = d.zones.length > 0 && d.zones.every((n) => selectedSet.has(n));
        if (allSelected) {
          d.zones.forEach((n) => consumed.add(n));
          items.push({
            key: `${loc.city}:${d.name}`,
            label: d.name,
            remove: () => onChangeZones(selectedZones.filter((z) => !d.zones.includes(z))),
          });
        }
      }
    }
    for (const z of selectedZones) {
      if (consumed.has(z)) continue;
      items.push({ key: z, label: z, remove: () => onChangeZones(selectedZones.filter((x) => x !== z)) });
    }
    return items;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locations, selectedZones]);

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
            onBlur={() => setOpen(false)}
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
    </div>
  );
}
