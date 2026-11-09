"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, ChevronRight, Loader2, RefreshCw } from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fetchCities, fetchSummary } from "@/lib/api";
import type { AnalyticsSummary } from "@/lib/types";
import { KpiTile } from "./KpiTile";
import { ChartCard, CHART_PALETTE, tooltipStyle } from "./ChartCard";

const AXIS_PROPS = { stroke: "#8C8579", fontSize: 11, tickLine: false, axisLine: { stroke: "#8C857940" } };

// Charts draw in their final state immediately. Recharts' mount animation
// is driven by requestAnimationFrame, so a chart that mounts in a
// background tab — or is screenshotted mid-flight — renders a partial
// series that reads as real data. On a dashboard whose only job is
// reporting numbers accurately, a half-drawn line is worse than no
// transition at all.
const NO_ANIM = { isAnimationActive: false };

const ALL_CITIES = "__all__";
const ALL_ROOMS = "__all__";
// Mirrors ROOM_ORDER in api/analytics.py — the service 422s on anything
// else, so these must stay in step with it.
const ROOM_OPTIONS = ["1", "2", "3", "4", "5+"];

function euro(value: number): string {
  return `€${value.toLocaleString("ro-RO")}`;
}

// 99.5% must not read as "100%" — coverage is a data-quality figure, and
// rounding the last half-percent away hides exactly the gap it exists to
// report. Only a true 100% prints without a decimal.
// The sector charts can only include listings whose district resolves to a
// sector; a blank district or an Ilfov satellite town (Voluntari, Popești
// Leordeni) has none. Saying so under the chart keeps the reader from
// reading the sector totals as the whole city.
function sectorNote(c: { attributed: number; missing: number }): string {
  const base = "Click pe o bară pentru a vedea cartierele din sector";
  if (c.missing <= 0) return base;
  return `${base} · ${c.missing.toLocaleString("ro-RO")} anunțuri fără sector nu sunt incluse`;
}

function coverage(pct: number): string {
  return pct >= 100 ? "100%" : `${pct.toFixed(1)}%`;
}

export function AnalyticsDashboard() {
  const [city, setCity] = useState<string>(ALL_CITIES);
  const [cities, setCities] = useState<string[]>([]);
  const [rooms, setRooms] = useState<string>(ALL_ROOMS);
  const [sector, setSector] = useState<string | null>(null);
  const [data, setData] = useState<AnalyticsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (refresh: boolean) => {
      refresh ? setRefreshing(true) : setLoading(true);
      setError(null);
      try {
        const summary = await fetchSummary(
          city === ALL_CITIES ? null : city,
          rooms === ALL_ROOMS ? [] : [rooms],
          refresh,
        );
        setData(summary);
        // A sector selected under one city may not exist under the next —
        // drop the drilldown rather than render an empty panel.
        setSector((current) =>
          current && summary.by_sector.some((s) => s.sector === current) ? current : null,
        );
      } catch (err) {
        setError((err as Error).message);
        setData(null);
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [city, rooms],
  );

  useEffect(() => {
    void load(false);
  }, [load]);

  useEffect(() => {
    // Best-effort: the city picker is a convenience, so a failure here must
    // not take down a dashboard whose data loaded fine.
    fetchCities()
      .then((res) => setCities(res.cities))
      .catch(() => setCities([]));
  }, []);

  const neighbourhoods = (sector && data?.by_neighbourhood[sector]) || [];

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-xl italic text-ink">Piața chiriilor — analiză internă</h1>
          <p className="mt-0.5 font-mono text-[0.68rem] uppercase tracking-[0.12em] text-concrete">
            {data
              ? `Actualizat ${new Date(data.generated_at).toLocaleString("ro-RO")}`
              : "Se încarcă…"}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <select
            value={city}
            onChange={(e) => setCity(e.target.value)}
            className="rounded border border-concrete/30 bg-white/60 px-2.5 py-1.5 text-sm text-ink"
          >
            <option value={ALL_CITIES}>Toate orașele</option>
            {cities.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <select
            value={rooms}
            onChange={(e) => setRooms(e.target.value)}
            aria-label="Filtrează după numărul de camere"
            className="rounded border border-concrete/30 bg-white/60 px-2.5 py-1.5 text-sm text-ink"
          >
            <option value={ALL_ROOMS}>Toate camerele</option>
            {ROOM_OPTIONS.map((r) => (
              <option key={r} value={r}>
                {r === "5+" ? "5+ camere" : `${r} ${r === "1" ? "cameră" : "camere"}`}
              </option>
            ))}
          </select>
          <button
            onClick={() => void load(true)}
            disabled={loading || refreshing}
            className="inline-flex items-center gap-1.5 rounded border border-concrete/30 bg-white/60 px-2.5 py-1.5 text-sm text-ink hover:border-brick hover:text-brick disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
            Reîmprospătează
          </button>
        </div>
      </header>

      {error && (
        <div className="mb-6 flex items-start gap-2 rounded-lg border border-brick/40 bg-brick-tint p-4 text-sm text-ink">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-brick" />
          <div>
            <p className="font-medium">Datele nu au putut fi încărcate.</p>
            <p className="mt-1 font-mono text-xs text-concrete">{error}</p>
          </div>
        </div>
      )}

      {loading && !data && (
        <div className="flex items-center justify-center gap-2 py-24 text-sm text-concrete">
          <Loader2 className="h-4 w-4 animate-spin" /> Se agregă datele din baza de date…
        </div>
      )}

      {data && data.kpis.total === 0 && !error && (
        <p className="py-24 text-center text-sm text-concrete">
          Nu există anunțuri disponibile pentru selecția curentă.
        </p>
      )}

      {data && data.kpis.total > 0 && (
        <>
          <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-5">
            <KpiTile label="Anunțuri active" value={data.kpis.total.toLocaleString("ro-RO")} />
            <KpiTile
              label="Cu preț"
              value={coverage(data.kpis.with_price_pct)}
              hint={`${data.kpis.with_price.toLocaleString("ro-RO")} anunțuri`}
            />
            <KpiTile label="Chirie medie" value={euro(data.kpis.avg_price)} />
            <KpiTile label="Chirie mediană" value={euro(data.kpis.median_price)} />
            <KpiTile label="Suprafață medie" value={`${data.kpis.avg_area} m²`} />
          </div>

          <div className="grid grid-cols-1 gap-4">
            <ChartCard title="Anunțuri noi pe zi">
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={data.daily_listings} margin={{ left: -20, right: 8 }}>
                  <CartesianGrid stroke="#8C857925" vertical={false} />
                  <XAxis
                    dataKey="day"
                    tickFormatter={(d: string) => d.slice(5)}
                    minTickGap={24}
                    {...AXIS_PROPS}
                  />
                  <YAxis {...AXIS_PROPS} />
                  <Tooltip {...tooltipStyle} />
                  <Area {...NO_ANIM} type="monotone" dataKey="count" name="Anunțuri" stroke="#A8461F" fill="#A8461F22" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </ChartCard>

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <ChartCard title="Distribuția prețurilor (EUR)">
                <ResponsiveContainer width="100%" height={240}>
                  <ComposedChart data={data.price_histogram} margin={{ left: -20, right: 8 }}>
                    <CartesianGrid stroke="#8C857925" vertical={false} />
                    <XAxis dataKey="label" minTickGap={28} {...AXIS_PROPS} />
                    <YAxis {...AXIS_PROPS} />
                    <Tooltip {...tooltipStyle} />
                    <Bar {...NO_ANIM} dataKey="count" name="Anunțuri" fill="#3E4E3A" radius={[2, 2, 0, 0]} />
                  </ComposedChart>
                </ResponsiveContainer>
              </ChartCard>

              {data.by_rooms.length > 0 && (
              <ChartCard title="Chirie medie & mediană pe număr de camere">
                <ResponsiveContainer width="100%" height={240}>
                  <ComposedChart data={data.by_rooms} margin={{ left: -20, right: 8 }}>
                    <CartesianGrid stroke="#8C857925" vertical={false} />
                    <XAxis dataKey="rooms" {...AXIS_PROPS} />
                    <YAxis {...AXIS_PROPS} />
                    <Tooltip {...tooltipStyle} formatter={(v: number) => euro(v)} />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Bar {...NO_ANIM} dataKey="avg" name="Medie" fill="#A8461F" radius={[2, 2, 0, 0]} />
                    <Line {...NO_ANIM} type="monotone" dataKey="median" name="Mediană" stroke="#3E4E3A" strokeWidth={2} dot={{ r: 3 }} />
                  </ComposedChart>
                </ResponsiveContainer>
              </ChartCard>
              )}
            </div>

            {data.by_sector.length > 0 && (
              <ChartCard
                title="Chirie medie & mediană pe sector"
                subtitle={sectorNote(data.sector_coverage)}
              >
                <ResponsiveContainer width="100%" height={260}>
                  <ComposedChart
                    data={data.by_sector}
                    margin={{ left: -20, right: 8 }}
                    onClick={(e) => e?.activePayload && setSector(e.activePayload[0].payload.sector)}
                  >
                    <CartesianGrid stroke="#8C857925" vertical={false} />
                    <XAxis dataKey="label" {...AXIS_PROPS} />
                    <YAxis {...AXIS_PROPS} />
                    <Tooltip {...tooltipStyle} formatter={(v: number) => euro(v)} />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Bar {...NO_ANIM} dataKey="avg" name="Medie" fill="#A8461F" radius={[2, 2, 0, 0]} cursor="pointer" />
                    <Line {...NO_ANIM} type="monotone" dataKey="median" name="Mediană" stroke="#3E4E3A" strokeWidth={2} dot={{ r: 3 }} />
                  </ComposedChart>
                </ResponsiveContainer>
              </ChartCard>
            )}

            {data.by_sector.length > 0 && (
              <ChartCard title="Detaliu pe cartiere">
                <div className="mb-3 flex items-center gap-1.5 font-mono text-xs text-concrete">
                  <button onClick={() => setSector(null)} className="hover:text-brick">
                    Toate sectoarele
                  </button>
                  {sector && (
                    <>
                      <ChevronRight className="h-3 w-3" />
                      <span className="text-ink">{sector}</span>
                    </>
                  )}
                </div>
                {!sector ? (
                  <p className="py-10 text-center text-sm text-concrete">
                    Selectează un sector din graficul de mai sus pentru a vedea cartierele.
                  </p>
                ) : neighbourhoods.length === 0 ? (
                  <p className="py-10 text-center text-sm text-concrete">
                    Date insuficiente pentru {sector} — cartierele cu sub 3 anunțuri nu sunt raportate.
                  </p>
                ) : (
                  <ResponsiveContainer width="100%" height={Math.max(220, neighbourhoods.length * 32)}>
                    <ComposedChart data={neighbourhoods} layout="vertical" margin={{ left: 24, right: 24 }}>
                      <CartesianGrid stroke="#8C857925" horizontal={false} />
                      <XAxis type="number" {...AXIS_PROPS} />
                      <YAxis type="category" dataKey="district" width={110} {...AXIS_PROPS} />
                      <Tooltip {...tooltipStyle} formatter={(v: number) => euro(v)} />
                      <Bar {...NO_ANIM} dataKey="avg" name="Medie" fill="#B8892B" radius={[0, 2, 2, 0]} />
                    </ComposedChart>
                  </ResponsiveContainer>
                )}
              </ChartCard>
            )}

            <ChartCard
              title="Preț vs. suprafață"
              subtitle={`${data.price_vs_area.length.toLocaleString("ro-RO")} puncte`}
            >
              <ResponsiveContainer width="100%" height={280}>
                <ScatterChart margin={{ left: -20, right: 8 }}>
                  <CartesianGrid stroke="#8C857925" />
                  <XAxis type="number" dataKey="area" name="Suprafață" unit=" m²" {...AXIS_PROPS} />
                  <YAxis type="number" dataKey="price" name="Chirie" unit="€" {...AXIS_PROPS} />
                  <Tooltip {...tooltipStyle} cursor={{ strokeDasharray: "3 3" }} />
                  <Scatter {...NO_ANIM} data={data.price_vs_area} fill="#A8461F99" />
                </ScatterChart>
              </ResponsiveContainer>
            </ChartCard>

            <div
              className={`grid grid-cols-1 gap-4 ${
                data.rooms_distribution.length > 0 ? "sm:grid-cols-3" : "sm:grid-cols-2"
              }`}
            >
              {data.rooms_distribution.length > 0 && (
              <ChartCard title="Camere">
                <ResponsiveContainer width="100%" height={200}>
                  <ComposedChart data={data.rooms_distribution} margin={{ left: -20, right: 8 }}>
                    <XAxis dataKey="rooms" {...AXIS_PROPS} />
                    <YAxis {...AXIS_PROPS} />
                    <Tooltip {...tooltipStyle} />
                    <Bar {...NO_ANIM} dataKey="count" name="Anunțuri" fill="#B8892B" radius={[2, 2, 0, 0]} />
                  </ComposedChart>
                </ResponsiveContainer>
              </ChartCard>
              )}

              <ChartCard title="Platformă">
                <ResponsiveContainer width="100%" height={200}>
                  <PieChart>
                    <Tooltip {...tooltipStyle} />
                    <Pie {...NO_ANIM} data={data.platforms} dataKey="value" nameKey="name" innerRadius={40} outerRadius={70} paddingAngle={2}>
                      {data.platforms.map((_, i) => (
                        <Cell key={i} fill={CHART_PALETTE[i % CHART_PALETTE.length]} />
                      ))}
                    </Pie>
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                  </PieChart>
                </ResponsiveContainer>
              </ChartCard>

              <ChartCard title="Tip proprietate">
                <ResponsiveContainer width="100%" height={200}>
                  <PieChart>
                    <Tooltip {...tooltipStyle} />
                    <Pie {...NO_ANIM} data={data.property_types} dataKey="value" nameKey="name" innerRadius={40} outerRadius={70} paddingAngle={2}>
                      {data.property_types.map((_, i) => (
                        <Cell key={i} fill={CHART_PALETTE[(i + 2) % CHART_PALETTE.length]} />
                      ))}
                    </Pie>
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                  </PieChart>
                </ResponsiveContainer>
              </ChartCard>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
