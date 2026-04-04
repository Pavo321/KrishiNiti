export const dynamic = "force-dynamic";

import pool from "@/lib/db";

async function getPriceHistory() {
  const result = await pool.query(`
    SELECT price_date, commodity, price_inr, source
    FROM commodity_prices
    WHERE source IN ('WORLDBANK', 'FERT_NIC', 'AGMARKNET', 'ENAM')
      AND price_date >= NOW() - INTERVAL '5 years'
    ORDER BY commodity, price_date DESC
  `);
  return result.rows;
}

const COMMODITY_LABELS: Record<string, { name: string; use: string; emoji: string }> = {
  UREA:       { name: "Urea (यूरिया / યૂरिया)",    use: "Nitrogen — paddy, wheat, maize",                 emoji: "🌱" },
  DAP:        { name: "DAP",                          use: "Phosphate — soybean, sunflower",                 emoji: "🌾" },
  MOP:        { name: "MOP (Potash / পোটাশ)",         use: "Potassium — sugarcane, cotton, veg",             emoji: "🍀" },
  SSP:        { name: "SSP (Single Super Phosphate)", use: "Phosphate + Sulphur — oilseeds, pulses, cotton", emoji: "🪨" },
  NPK_102626: { name: "NPK 10:26:26",                 use: "Complex — rabi wheat, potato, vegetables",       emoji: "🔬" },
};

export default async function PricesPage() {
  const rows = await getPriceHistory();

  const byComm: Record<string, typeof rows> = {};
  for (const r of rows) {
    if (!byComm[r.commodity]) byComm[r.commodity] = [];
    byComm[r.commodity].push(r);
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-green-400">Fertilizer Price History</h1>
        <p className="text-yellow-400/80 text-sm mt-1">
          Real data from Agmarknet + World Bank + eNAM + fert.nic.in. ₹/50kg bag. Last 5 years.
        </p>
      </div>

      {Object.entries(byComm).map(([commodity, data]) => {
        const label = COMMODITY_LABELS[commodity] || { name: commodity, use: "", emoji: "🌾" };
        return (
          <div key={commodity} className="glass p-6">
            <div className="flex items-center gap-3 mb-4">
              <span className="text-2xl">{label.emoji}</span>
              <div>
                <h2 className="font-bold text-green-300 text-lg">{label.name}</h2>
                <p className="text-yellow-400/70 text-xs">{label.use} — {data.length} monthly records</p>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-green-400 border-b border-green-800/40">
                    <th className="text-left py-2 pr-6">Month</th>
                    <th className="text-left py-2 pr-6">Source</th>
                    <th className="text-right py-2 pr-6">₹ / 50kg bag</th>
                    <th className="text-right py-2">Month-on-Month</th>
                  </tr>
                </thead>
                <tbody>
                  {data.slice(0, 24).map((row, i) => {
                    const prev = data[i + 1];
                    const mom = prev
                      ? ((parseFloat(row.price_inr) - parseFloat(prev.price_inr)) / parseFloat(prev.price_inr)) * 100
                      : null;
                    return (
                      <tr key={`${row.price_date}_${row.source}`} className="border-b border-green-900/30 hover:bg-green-900/20 transition-colors">
                        <td className="py-2 pr-6 text-green-400">
                          {new Date(row.price_date).toLocaleDateString("en-IN", { month: "short", year: "numeric" })}
                        </td>
                        <td className="py-2 pr-6">
                          <span className="text-xs px-2 py-0.5 rounded-full border border-green-700/40 text-green-400/70">
                            {row.source === "WORLDBANK" ? "World Bank" : row.source === "FERT_NIC" ? "DoF MRP" : row.source}
                          </span>
                        </td>
                        <td className="py-2 pr-6 text-right font-mono text-green-300 font-semibold">
                          ₹{parseFloat(row.price_inr).toFixed(0)}
                        </td>
                        <td className="py-2 text-right">
                          {mom !== null ? (
                            <span className={mom > 0 ? "text-yellow-400 font-semibold" : mom < 0 ? "text-green-400 font-semibold" : "text-green-600"}>
                              {mom > 0 ? "▲" : mom < 0 ? "▼" : "–"} {Math.abs(mom).toFixed(1)}%
                            </span>
                          ) : "–"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}
    </div>
  );
}
