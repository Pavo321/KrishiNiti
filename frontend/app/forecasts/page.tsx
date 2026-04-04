export const dynamic = "force-dynamic";

import pool from "@/lib/db";

async function getData() {
  const [forecastsRes, currentPricesRes] = await Promise.all([
    pool.query(`
      SELECT id, forecast_date, target_date, commodity,
             direction, confidence_score, predicted_price_inr,
             model_name, actual_direction, accuracy_flag
      FROM forecasts
      WHERE forecast_date = (SELECT MAX(forecast_date) FROM forecasts)
      ORDER BY commodity, target_date
    `),
    pool.query(`
      SELECT DISTINCT ON (commodity)
        commodity, price_inr, price_date, source
      FROM commodity_prices
      WHERE source IN ('WORLDBANK', 'FERT_NIC', 'AGMARKNET', 'ENAM')
        AND price_inr IS NOT NULL
      ORDER BY commodity,
        CASE source WHEN 'AGMARKNET' THEN 1 WHEN 'ENAM' THEN 2 WHEN 'FERT_NIC' THEN 3 ELSE 4 END,
        price_date DESC
    `),
  ]);

  const currentMap: Record<string, number> = {};
  for (const r of currentPricesRes.rows) {
    currentMap[r.commodity] = parseFloat(r.price_inr);
  }

  return { forecasts: forecastsRes.rows, currentMap };
}

const DIRECTION_STYLE: Record<string, string> = {
  UP: "badge-up", DOWN: "badge-down", STABLE: "badge-stable",
};

const COMMODITY_META: Record<string, { emoji: string; name: string; use: string }> = {
  UREA:       { emoji: "🌱", name: "Urea",              use: "Nitrogen fertilizer — paddy, wheat, maize" },
  DAP:        { emoji: "🌾", name: "DAP",               use: "Phosphate fertilizer — soybean, sunflower" },
  MOP:        { emoji: "🍀", name: "MOP (Potash)",      use: "Potassium fertilizer — sugarcane, cotton" },
  SSP:        { emoji: "🪨", name: "SSP",               use: "Single Super Phosphate — oilseeds, pulses, budget alternative to DAP" },
  NPK_102626: { emoji: "🔬", name: "NPK 10:26:26",      use: "Complex fertilizer — rabi crops, soil with N deficiency" },
};

const COMMODITIES = ["UREA", "DAP", "MOP", "SSP", "NPK_102626"];

export default async function ForecastsPage() {
  const { forecasts, currentMap } = await getData();

  if (forecasts.length === 0) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold text-green-400">Forecasts</h1>
        <div className="glass p-6 text-center py-12">
          <p className="text-green-400/60">No forecasts yet.</p>
          <code className="block mt-3 text-xs bg-green-950/40 border border-green-800/40 rounded px-4 py-2 text-green-400 w-fit mx-auto">
            docker compose up forecast-service
          </code>
        </div>
      </div>
    );
  }

  const byComm: Record<string, typeof forecasts> = {};
  for (const f of forecasts) {
    if (!byComm[f.commodity]) byComm[f.commodity] = [];
    byComm[f.commodity].push(f);
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-green-400">Forecasts</h1>
        <p className="text-yellow-400/70 text-sm mt-1">
          Prophet + XGBoost + LSTM ensemble · Updated daily 3:00 AM IST · {forecasts.length} predictions
        </p>
      </div>

      {COMMODITIES.map((commodity) => {
        const rows = byComm[commodity];
        if (!rows || rows.length === 0) return null;
        const meta = COMMODITY_META[commodity];
        const current = currentMap[commodity];

        return (
          <div key={commodity} className="space-y-3">
            <div className="flex items-center gap-3">
              <span className="text-2xl">{meta.emoji}</span>
              <div>
                <h2 className="text-lg font-bold text-green-300">{meta.name}</h2>
                <p className="text-xs text-yellow-400/70">{meta.use}</p>
              </div>
              {current && (
                <div className="ml-auto text-right">
                  <div className="text-xl font-black text-green-300">₹{current.toFixed(0)}</div>
                  <div className="text-xs text-green-400/50">current / 50kg</div>
                </div>
              )}
            </div>

            <div className="glass overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-green-400 border-b border-green-800/40">
                    <th className="text-left py-3 px-4">Target Date</th>
                    <th className="text-right py-3 px-4">Current ₹</th>
                    <th className="text-right py-3 px-4">Predicted ₹</th>
                    <th className="text-left py-3 px-4">Direction</th>
                    <th className="text-right py-3 px-4">Confidence</th>
                    <th className="text-center py-3 px-4">Accuracy</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((f) => {
                    const conf = Math.round(f.confidence_score * 100);
                    const predicted = f.predicted_price_inr ? parseFloat(f.predicted_price_inr) : null;
                    const priceDiff = predicted && current ? predicted - current : null;
                    return (
                      <tr key={f.id} className="border-b border-green-900/30 hover:bg-green-900/20 transition-colors">
                        <td className="py-3 px-4 text-green-400">
                          {new Date(f.target_date).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}
                        </td>
                        <td className="py-3 px-4 text-right font-mono text-green-300">
                          {current ? `₹${current.toFixed(0)}` : "–"}
                        </td>
                        <td className="py-3 px-4 text-right font-mono">
                          {predicted ? (
                            <span className="text-green-300 font-semibold">₹{predicted.toFixed(0)}</span>
                          ) : "–"}
                          {priceDiff !== null && (
                            <span className={`block text-xs ${priceDiff > 0 ? "text-yellow-400" : "text-green-400"}`}>
                              {priceDiff > 0 ? "+" : ""}₹{priceDiff.toFixed(0)}
                            </span>
                          )}
                        </td>
                        <td className="py-3 px-4">
                          <span className={DIRECTION_STYLE[f.direction] || "badge-stable"}>{f.direction}</span>
                        </td>
                        <td className="py-3 px-4 text-right">
                          <div className="flex items-center justify-end gap-2">
                            <div className="w-12 bg-green-900/40 rounded-full h-1.5">
                              <div className={`h-1.5 rounded-full ${conf >= 70 ? "bg-green-400" : "bg-yellow-400"}`}
                                style={{ width: `${conf}%` }} />
                            </div>
                            <span className={`font-bold text-xs ${conf >= 70 ? "text-green-400" : "text-yellow-400"}`}>{conf}%</span>
                          </div>
                        </td>
                        <td className="py-3 px-4 text-center">
                          {f.accuracy_flag === null ? (
                            <span className="text-green-400/40 text-xs">Pending</span>
                          ) : f.accuracy_flag ? (
                            <span className="text-green-400 font-bold">✓</span>
                          ) : (
                            <span className="text-yellow-400 font-bold">✗</span>
                          )}
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
