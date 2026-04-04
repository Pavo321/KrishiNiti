"use client";

import { useEffect, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine, Legend,
} from "recharts";

type PriceRow = { price_date: string; price_inr: string; source: string };

const SOURCE_COLORS: Record<string, string> = {
  WORLDBANK: "#facc15",
  FERT_NIC:  "#4ade80",
  AGMARKNET: "#60a5fa",
  ENAM:      "#f472b6",
  PPAC:      "#fb923c",
};

const SOURCE_LABELS: Record<string, string> = {
  WORLDBANK: "World Bank",
  FERT_NIC:  "DoF MRP",
  AGMARKNET: "Agmarknet",
  ENAM:      "eNAM",
  PPAC:      "PPAC",
};

export type SourceFilter = "ALL" | "WORLDBANK" | "FERT_NIC" | "AGMARKNET" | "ENAM";

export default function PriceChart({
  commodity,
  source = "ALL",
  months = 36,
}: {
  commodity: string;
  source?: SourceFilter;
  months?: number;
}) {
  const [data, setData] = useState<PriceRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    const params = new URLSearchParams({ commodity, months: String(months) });
    if (source !== "ALL") params.set("source", source);
    fetch(`/api/prices?${params}`)
      .then((r) => r.json())
      .then((rows) => { setData(rows); setLoading(false); })
      .catch(() => setLoading(false));
  }, [commodity, source, months]);

  if (loading) return (
    <div className="h-48 flex items-center justify-center text-green-400/50 text-sm animate-pulse">
      Loading price data...
    </div>
  );

  if (!data.length) return (
    <div className="h-48 flex items-center justify-center text-green-400/30 text-xs">
      No data for selected source
    </div>
  );

  // Group by source for multi-line chart
  const sources = [...new Set(data.map((d) => d.source))];
  const allDates = [...new Set(data.map((d) => d.price_date))].sort();

  const formatted = allDates.map((date) => {
    const entry: Record<string, string | number> = {
      date: new Date(date).toLocaleDateString("en-IN", { month: "short", year: "2-digit" }),
    };
    for (const src of sources) {
      const row = data.find((d) => d.price_date === date && d.source === src);
      if (row) entry[src] = parseFloat(parseFloat(row.price_inr).toFixed(0));
    }
    return entry;
  });

  const allPrices = data.map((d) => parseFloat(d.price_inr));
  const avg = allPrices.reduce((s, v) => s + v, 0) / allPrices.length;

  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={formatted} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1a3a1a" />
        <XAxis dataKey="date" tick={{ fill: "#4ade80", fontSize: 10 }} tickLine={false} />
        <YAxis tick={{ fill: "#4ade80", fontSize: 10 }} tickLine={false} axisLine={false}
          tickFormatter={(v) => `₹${v}`} />
        <Tooltip
          contentStyle={{ background: "#0a1f0a", border: "1px solid #2d4a2d", borderRadius: 8 }}
          labelStyle={{ color: "#4ade80", fontSize: 12 }}
          formatter={(v, name) => [`₹${v}/50kg`, SOURCE_LABELS[name as string] || name]}
        />
        {sources.length > 1 && (
          <Legend
            formatter={(value) => (
              <span style={{ color: SOURCE_COLORS[value] || "#4ade80", fontSize: 10 }}>
                {SOURCE_LABELS[value] || value}
              </span>
            )}
          />
        )}
        <ReferenceLine y={avg} stroke="#facc1566" strokeDasharray="4 4"
          label={{ value: `Avg ₹${avg.toFixed(0)}`, fill: "#facc15", fontSize: 9 }} />
        {sources.map((src) => (
          <Line
            key={src}
            type="monotone"
            dataKey={src}
            stroke={SOURCE_COLORS[src] || "#4ade80"}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
            connectNulls
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
