export const dynamic = "force-dynamic";

import pool from "@/lib/db";

async function getData() {
  const [forecastsRes, currentPricesRes, historyRes] = await Promise.all([
    pool.query(`
      SELECT commodity, direction, confidence_score, predicted_price_inr,
             actual_price_inr, actual_direction, accuracy_flag,
             forecast_date, target_date, model_name
      FROM forecasts
      ORDER BY forecast_date DESC, target_date
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
    pool.query(`
      SELECT commodity, price_date, price_inr
      FROM commodity_prices
      WHERE source IN ('WORLDBANK', 'FERT_NIC', 'AGMARKNET', 'ENAM')
        AND price_inr IS NOT NULL
        AND price_date >= NOW() - INTERVAL '12 months'
      ORDER BY commodity, price_date ASC
    `),
  ]);

  const forecasts = forecastsRes.rows;
  const currentMap: Record<string, { price: number; date: string }> = {};
  for (const r of currentPricesRes.rows) {
    currentMap[r.commodity] = { price: parseFloat(r.price_inr), date: r.price_date };
  }

  // Accuracy stats
  const evaluated = forecasts.filter((f) => f.accuracy_flag !== null);
  const correct = evaluated.filter((f) => f.accuracy_flag === true);
  const accPct = evaluated.length > 0 ? Math.round((correct.length / evaluated.length) * 100) : null;

  // By commodity accuracy
  const byCommodity: Record<string, { total: number; correct: number; evaluated: number }> = {};
  for (const f of forecasts) {
    if (!byCommodity[f.commodity]) byCommodity[f.commodity] = { total: 0, correct: 0, evaluated: 0 };
    byCommodity[f.commodity].total++;
    if (f.accuracy_flag !== null) {
      byCommodity[f.commodity].evaluated++;
      if (f.accuracy_flag) byCommodity[f.commodity].correct++;
    }
  }

  // Confidence breakdown
  const highConf = forecasts.filter((f) => f.confidence_score >= 0.7);
  const lowConf = forecasts.filter((f) => f.confidence_score < 0.7);

  // Predicted vs current price comparison
  const latestByComm: Record<string, typeof forecasts[0][]> = {};
  for (const f of forecasts) {
    if (!latestByComm[f.commodity]) latestByComm[f.commodity] = [];
    if (latestByComm[f.commodity].length < 3) latestByComm[f.commodity].push(f);
  }

  // 12-month price history for trend
  const history = historyRes.rows;

  return { forecasts, currentMap, accPct, byCommodity, highConf, lowConf, latestByComm, history, evaluated, correct };
}

const EMOJI: Record<string, string> = { UREA: "🌱", DAP: "🌾", MOP: "🍀", SSP: "🪨", NPK_102626: "🔬" };
const DIRECTION_STYLE: Record<string, string> = {
  UP: "badge-up", DOWN: "badge-down", STABLE: "badge-stable",
};

export default async function AnalysisPage() {
  const { forecasts, currentMap, accPct, byCommodity, highConf, lowConf, latestByComm, history, evaluated, correct } = await getData();

  // Group history by commodity for min/max/avg
  const histByComm: Record<string, number[]> = {};
  for (const r of history) {
    if (!histByComm[r.commodity]) histByComm[r.commodity] = [];
    histByComm[r.commodity].push(parseFloat(r.price_inr));
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-green-400">Model Analysis</h1>
        <p className="text-yellow-400/70 text-sm mt-1">
          Real data vs predicted data — how reliable is KrishiNiti's AI?
        </p>
      </div>

      {/* Overall Accuracy Banner */}
      <div className="glass p-6 border-l-4 border-green-400">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
          <div className="text-center">
            <div className="text-4xl font-black text-green-400">
              {accPct !== null ? `${accPct}%` : "—"}
            </div>
            <div className="text-xs text-yellow-400 mt-1 uppercase tracking-wide">Direction Accuracy</div>
            <div className="text-xs text-green-400/50 mt-0.5">
              {evaluated.length > 0 ? `${correct.length} of ${evaluated.length} evaluated` : "Accumulating data..."}
            </div>
          </div>
          <div className="text-center">
            <div className="text-4xl font-black text-green-300">{forecasts.length}</div>
            <div className="text-xs text-yellow-400 mt-1 uppercase tracking-wide">Total Predictions</div>
            <div className="text-xs text-green-400/50 mt-0.5">UREA, DAP, MOP</div>
          </div>
          <div className="text-center">
            <div className="text-4xl font-black text-green-300">{highConf.length}</div>
            <div className="text-xs text-yellow-400 mt-1 uppercase tracking-wide">High Confidence ≥70%</div>
            <div className="text-xs text-green-400/50 mt-0.5">
              {forecasts.length > 0 ? `${Math.round((highConf.length / forecasts.length) * 100)}% of all forecasts` : "—"}
            </div>
          </div>
          <div className="text-center">
            <div className="text-4xl font-black text-yellow-400">{lowConf.length}</div>
            <div className="text-xs text-yellow-400 mt-1 uppercase tracking-wide">Low Confidence &lt;70%</div>
            <div className="text-xs text-green-400/50 mt-0.5">Flagged for review</div>
          </div>
        </div>
      </div>

      {/* Real Price vs Predicted — side by side */}
      <div>
        <h2 className="text-lg font-bold text-green-300 mb-4">Current Market Price vs AI Prediction</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {Object.entries(latestByComm).map(([commodity, preds]) => {
            const current = currentMap[commodity];
            if (!current) return null;
            return (
              <div key={commodity} className="glass p-5 space-y-4">
                <div className="flex items-center gap-2">
                  <span className="text-xl">{EMOJI[commodity] || "🌾"}</span>
                  <span className="font-bold text-green-300 text-lg">{commodity}</span>
                </div>

                {/* Current real price */}
                <div className="bg-green-950/60 border border-green-700/30 rounded-lg p-3">
                  <div className="text-xs text-yellow-400 uppercase tracking-wide mb-1">📊 Real Market Price (Agmarknet + World Bank)</div>
                  <div className="text-3xl font-black text-green-300">₹{current.price.toFixed(0)}</div>
                  <div className="text-xs text-green-400/50">per 50kg bag · {new Date(current.date).toLocaleDateString("en-IN", { month: "short", year: "numeric" })}</div>
                </div>

                {/* AI predictions */}
                <div className="space-y-2">
                  <div className="text-xs text-yellow-400 uppercase tracking-wide">🤖 AI Predictions</div>
                  {preds.map((f, i) => {
                    const predicted = f.predicted_price_inr ? parseFloat(f.predicted_price_inr) : null;
                    const diff = predicted ? predicted - current.price : null;
                    const horizon = Math.round((new Date(f.target_date).getTime() - new Date(f.forecast_date).getTime()) / (1000 * 60 * 60 * 24));
                    return (
                      <div key={i} className="flex items-center justify-between bg-green-900/20 rounded-lg px-3 py-2">
                        <div>
                          <div className="text-xs text-green-400/70">{horizon}-day forecast</div>
                          <div className="text-sm font-bold text-green-300">
                            {predicted ? `₹${predicted.toFixed(0)}` : "–"}
                          </div>
                        </div>
                        <div className="text-right">
                          {diff !== null && (
                            <div className={`text-xs font-bold ${diff > 0 ? "text-yellow-400" : "text-green-400"}`}>
                              {diff > 0 ? "▲ +" : "▼ "}₹{Math.abs(diff).toFixed(0)}
                            </div>
                          )}
                          <span className={DIRECTION_STYLE[f.direction] || "badge-stable"}>{f.direction}</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* 12-month real price range vs predictions */}
      <div>
        <h2 className="text-lg font-bold text-green-300 mb-4">12-Month Real Price Range vs Model Predictions</h2>
        <div className="glass overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-green-400 border-b border-green-800/40">
                <th className="text-left py-3 px-4">Commodity</th>
                <th className="text-right py-3 px-4">12m Low ₹</th>
                <th className="text-right py-3 px-4">12m High ₹</th>
                <th className="text-right py-3 px-4">12m Avg ₹</th>
                <th className="text-right py-3 px-4">Current ₹</th>
                <th className="text-right py-3 px-4">AI Predicted ₹</th>
                <th className="text-left py-3 px-4">Within Range?</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(histByComm).map(([commodity, prices]) => {
                const lo = Math.min(...prices);
                const hi = Math.max(...prices);
                const avg = prices.reduce((a, b) => a + b, 0) / prices.length;
                const curr = currentMap[commodity]?.price;
                const preds = latestByComm[commodity];
                const pred30 = preds?.find((f) => {
                  const h = Math.round((new Date(f.target_date).getTime() - new Date(f.forecast_date).getTime()) / 86400000);
                  return h >= 25;
                });
                const predPrice = pred30?.predicted_price_inr ? parseFloat(pred30.predicted_price_inr) : null;
                const inRange = predPrice !== null ? predPrice >= lo * 0.85 && predPrice <= hi * 1.15 : null;
                return (
                  <tr key={commodity} className="border-b border-green-900/30 hover:bg-green-900/20 transition-colors">
                    <td className="py-3 px-4 font-semibold text-green-300">{EMOJI[commodity]} {commodity}</td>
                    <td className="py-3 px-4 text-right font-mono text-green-400">₹{lo.toFixed(0)}</td>
                    <td className="py-3 px-4 text-right font-mono text-yellow-400">₹{hi.toFixed(0)}</td>
                    <td className="py-3 px-4 text-right font-mono text-green-300">₹{avg.toFixed(0)}</td>
                    <td className="py-3 px-4 text-right font-mono text-green-300 font-bold">
                      {curr ? `₹${curr.toFixed(0)}` : "–"}
                    </td>
                    <td className="py-3 px-4 text-right font-mono text-green-300">
                      {predPrice ? `₹${predPrice.toFixed(0)}` : "–"}
                    </td>
                    <td className="py-3 px-4">
                      {inRange === null ? (
                        <span className="text-green-400/40 text-xs">—</span>
                      ) : inRange ? (
                        <span className="text-green-400 font-bold text-xs">✓ Yes — prediction is realistic</span>
                      ) : (
                        <span className="text-yellow-400 font-bold text-xs">⚠ Outside normal range</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Per-commodity accuracy */}
      <div>
        <h2 className="text-lg font-bold text-green-300 mb-4">Accuracy by Commodity</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {Object.entries(byCommodity).map(([commodity, stats]) => {
            const pct = stats.evaluated > 0 ? Math.round((stats.correct / stats.evaluated) * 100) : null;
            const avgConf = Math.round(
              forecasts
                .filter((f) => f.commodity === commodity)
                .reduce((s, f) => s + f.confidence_score, 0) /
                forecasts.filter((f) => f.commodity === commodity).length * 100
            );
            return (
              <div key={commodity} className="glass p-5 space-y-3">
                <div className="flex items-center gap-2">
                  <span className="text-xl">{EMOJI[commodity] || "🌾"}</span>
                  <span className="font-bold text-green-300">{commodity}</span>
                </div>
                <div className="space-y-2">
                  <div className="flex justify-between text-xs">
                    <span className="text-green-400">Direction Accuracy</span>
                    <span className={pct !== null && pct >= 70 ? "text-green-400 font-bold" : "text-yellow-400"}>
                      {pct !== null ? `${pct}%` : "Pending"}
                    </span>
                  </div>
                  <div className="flex justify-between text-xs">
                    <span className="text-green-400">Avg Confidence</span>
                    <span className={avgConf >= 70 ? "text-green-400 font-bold" : "text-yellow-400"}>{avgConf}%</span>
                  </div>
                  <div className="flex justify-between text-xs">
                    <span className="text-green-400">Total Predictions</span>
                    <span className="text-green-300">{stats.total}</span>
                  </div>
                  <div className="flex justify-between text-xs">
                    <span className="text-green-400">Evaluated</span>
                    <span className="text-green-300">{stats.evaluated} / {stats.total}</span>
                  </div>
                </div>
                {pct === null && (
                  <div className="text-xs text-green-400/40 bg-green-950/40 rounded p-2 text-center">
                    Accuracy tracked once target dates pass
                  </div>
                )}
                {pct !== null && (
                  <div className="w-full bg-green-900/40 rounded-full h-2">
                    <div className={`h-2 rounded-full ${pct >= 70 ? "bg-green-400" : "bg-yellow-400"}`}
                      style={{ width: `${pct}%` }} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Why trust us */}
      <div className="glass p-6 border-l-4 border-yellow-400">
        <h2 className="text-lg font-bold text-green-300 mb-3">Why Trust KrishiNiti?</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
          {[
            { icon: "📊", title: "Real Data Only", body: "Trained on 9 live sources: World Bank Pink Sheet (60+ years), Agmarknet mandi prices, eNAM transaction data, fert.nic.in retail prices, NCDEX futures, FAO GIEWS, APEDA state prices, Open-Meteo weather, and NASA POWER (12 years, 50+ districts). No synthetic data." },
            { icon: "🎯", title: "Confidence Scores", body: "Every prediction comes with a confidence %. We flag low-confidence predictions — we won't ask farmers to act on uncertain signals." },
            { icon: "🔁", title: "Daily Retraining", body: "Model retrains every night at 3 AM IST on the freshest data available. Predictions are never stale." },
            { icon: "✅", title: "Accuracy Tracking", body: "Every prediction is auto-evaluated once the target date passes. Right or wrong — we publish the result here." },
          ].map((item) => (
            <div key={item.title} className="flex gap-3">
              <span className="text-2xl">{item.icon}</span>
              <div>
                <div className="font-semibold text-green-300">{item.title}</div>
                <div className="text-green-400/80 text-xs mt-0.5 leading-relaxed">{item.body}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
