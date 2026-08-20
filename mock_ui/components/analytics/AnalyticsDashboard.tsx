"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft, ChevronRight } from "lucide-react";
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
import { ALL_LISTINGS } from "@/lib/mockData";
import {
  avgPriceByNeighborhood,
  avgPriceByRooms,
  avgPriceBySector,
  CHART_PALETTE,
  computeKpis,
  dailyListingsSeries,
  platformBreakdown,
  priceHistogram,
  priceVsArea,
  propertyTypeBreakdown,
  roomsDistribution,
} from "@/lib/analytics";
import { KpiTile } from "./KpiTile";
import { ChartCard, tooltipStyle } from "./ChartCard";

const AXIS_PROPS = { stroke: "#8C8579", fontSize: 11, tickLine: false, axisLine: { stroke: "#8C857940" } };

export function AnalyticsDashboard() {
  const [sector, setSector] = useState<string | null>(null);

  const kpis = useMemo(() => computeKpis(ALL_LISTINGS), []);
  const daily = useMemo(() => dailyListingsSeries(ALL_LISTINGS), []);
  const histogram = useMemo(() => priceHistogram(ALL_LISTINGS), []);
  const bySector = useMemo(() => avgPriceBySector(ALL_LISTINGS), []);
  const byRooms = useMemo(() => avgPriceByRooms(ALL_LISTINGS), []);
  const roomsDist = useMemo(() => roomsDistribution(ALL_LISTINGS), []);
  const platforms = useMemo(() => platformBreakdown(ALL_LISTINGS), []);
  const propertyTypes = useMemo(() => propertyTypeBreakdown(ALL_LISTINGS), []);
  const scatter = useMemo(() => priceVsArea(ALL_LISTINGS), []);
  const neighborhoods = useMemo(() => (sector ? avgPriceByNeighborhood(sector, ALL_LISTINGS) : []), [sector]);

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <div className="mb-6 flex items-center justify-between">
        <Link href="/" className="inline-flex items-center gap-1.5 text-sm font-medium text-ink hover:text-brick">
          <ArrowLeft className="h-4 w-4" /> Căutare
        </Link>
        <h1 className="font-display text-xl italic text-ink">Piața chiriilor — București</h1>
        <span className="w-16" />
      </div>

      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-5">
        <KpiTile label="Anunțuri active" value={kpis.total.toLocaleString("ro-RO")} />
        <KpiTile label="Cu preț" value={`${kpis.withPricePct.toFixed(0)}%`} hint={`${kpis.withPrice} anunțuri`} />
        <KpiTile label="Chirie medie" value={`€${kpis.avgPrice.toLocaleString("ro-RO")}`} />
        <KpiTile label="Chirie mediană" value={`€${kpis.medianPrice.toLocaleString("ro-RO")}`} />
        <KpiTile label="Suprafață medie" value={`${kpis.avgArea} m²`} />
      </div>

      <div className="grid grid-cols-1 gap-4">
        <ChartCard title="Anunțuri noi pe zi">
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={daily} margin={{ left: -20, right: 8 }}>
              <CartesianGrid stroke="#8C857925" vertical={false} />
              <XAxis dataKey="day" {...AXIS_PROPS} />
              <YAxis {...AXIS_PROPS} />
              <Tooltip {...tooltipStyle} />
              <Area type="monotone" dataKey="count" stroke="#A8461F" fill="#A8461F22" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </ChartCard>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <ChartCard title="Distribuția prețurilor (EUR)">
            <ResponsiveContainer width="100%" height={240}>
              <ComposedChart data={histogram} margin={{ left: -20, right: 8 }}>
                <CartesianGrid stroke="#8C857925" vertical={false} />
                <XAxis dataKey="bucket" {...AXIS_PROPS} interval={Math.ceil(histogram.length / 8)} />
                <YAxis {...AXIS_PROPS} />
                <Tooltip {...tooltipStyle} />
                <Bar dataKey="count" fill="#3E4E3A" radius={[2, 2, 0, 0]} />
              </ComposedChart>
            </ResponsiveContainer>
          </ChartCard>

          <ChartCard title="Chirie medie pe număr de camere">
            <ResponsiveContainer width="100%" height={240}>
              <ComposedChart data={byRooms} margin={{ left: -20, right: 8 }}>
                <CartesianGrid stroke="#8C857925" vertical={false} />
                <XAxis dataKey="rooms" {...AXIS_PROPS} />
                <YAxis {...AXIS_PROPS} />
                <Tooltip {...tooltipStyle} formatter={(v: number) => `€${v}`} />
                <Bar dataKey="avg" name="Medie" fill="#A8461F" radius={[2, 2, 0, 0]} />
              </ComposedChart>
            </ResponsiveContainer>
          </ChartCard>
        </div>

        <ChartCard title="Chirie medie & mediană pe sector">
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart
              data={bySector}
              margin={{ left: -20, right: 8 }}
              onClick={(e) => e?.activePayload && setSector(e.activePayload[0].payload.sector)}
            >
              <CartesianGrid stroke="#8C857925" vertical={false} />
              <XAxis dataKey="label" {...AXIS_PROPS} />
              <YAxis {...AXIS_PROPS} />
              <Tooltip {...tooltipStyle} formatter={(v: number) => `€${v}`} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="avg" name="Medie" fill="#A8461F" radius={[2, 2, 0, 0]} cursor="pointer" />
              <Line type="monotone" dataKey="median" name="Mediană" stroke="#3E4E3A" strokeWidth={2} dot={{ r: 3 }} />
            </ComposedChart>
          </ResponsiveContainer>
          <p className="mt-1 text-center text-xs text-concrete">Click pe o bară pentru a vedea cartierele din sector ↓</p>
        </ChartCard>

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
          ) : neighborhoods.length === 0 ? (
            <p className="py-10 text-center text-sm text-concrete">Date insuficiente pentru {sector}.</p>
          ) : (
            <ResponsiveContainer width="100%" height={Math.max(220, neighborhoods.length * 32)}>
              <ComposedChart data={neighborhoods} layout="vertical" margin={{ left: 24, right: 24 }}>
                <CartesianGrid stroke="#8C857925" horizontal={false} />
                <XAxis type="number" {...AXIS_PROPS} />
                <YAxis type="category" dataKey="district" width={110} {...AXIS_PROPS} />
                <Tooltip {...tooltipStyle} formatter={(v: number) => `€${v}`} />
                <Bar dataKey="avg" fill="#B8892B" radius={[0, 2, 2, 0]} />
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </ChartCard>

        <ChartCard title="Preț vs. suprafață">
          <ResponsiveContainer width="100%" height={280}>
            <ScatterChart margin={{ left: -20, right: 8 }}>
              <CartesianGrid stroke="#8C857925" />
              <XAxis type="number" dataKey="area" name="Suprafață" unit=" m²" {...AXIS_PROPS} />
              <YAxis type="number" dataKey="price" name="Chirie" unit="€" {...AXIS_PROPS} />
              <Tooltip {...tooltipStyle} cursor={{ strokeDasharray: "3 3" }} />
              <Scatter data={scatter} fill="#A8461F99" />
            </ScatterChart>
          </ResponsiveContainer>
        </ChartCard>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <ChartCard title="Camere">
            <ResponsiveContainer width="100%" height={200}>
              <ComposedChart data={roomsDist} margin={{ left: -20, right: 8 }}>
                <XAxis dataKey="rooms" {...AXIS_PROPS} />
                <YAxis {...AXIS_PROPS} />
                <Tooltip {...tooltipStyle} />
                <Bar dataKey="count" fill="#B8892B" radius={[2, 2, 0, 0]} />
              </ComposedChart>
            </ResponsiveContainer>
          </ChartCard>

          <ChartCard title="Platformă">
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Tooltip {...tooltipStyle} />
                <Pie data={platforms} dataKey="value" nameKey="name" innerRadius={40} outerRadius={70} paddingAngle={2}>
                  {platforms.map((_, i) => (
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
                <Pie data={propertyTypes} dataKey="value" nameKey="name" innerRadius={40} outerRadius={70} paddingAngle={2}>
                  {propertyTypes.map((_, i) => (
                    <Cell key={i} fill={CHART_PALETTE[(i + 2) % CHART_PALETTE.length]} />
                  ))}
                </Pie>
                <Legend wrapperStyle={{ fontSize: 11 }} />
              </PieChart>
            </ResponsiveContainer>
          </ChartCard>
        </div>
      </div>
    </div>
  );
}
