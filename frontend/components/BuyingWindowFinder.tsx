"use client";

import { useState } from "react";

interface Forecast {
  id: string;
  target_date: string;
  commodity: string;
  direction: string;
  confidence_score: number;
  predicted_price_inr: string | null;
}

interface CurrentPrice {
  commodity: string;
  price: number;
}

interface Props {
  forecasts: Forecast[];
  currentPrices: CurrentPrice[];
}

const COMMODITY_META: Record<string, { emoji: string; name: string }> = {
  UREA: { emoji: "🌱", name: "Urea" },
  DAP:  { emoji: "🌾", name: "DAP" },
  MOP:  { emoji: "🍀", name: "MOP (Potash)" },
};

const DIRECTION_SCORE: Record<string, number> = { DOWN: 3, STABLE: 1, UP: 0 };

function scoreWindow(f: Forecast, currentPrice: number): number {
  // Higher score = better buying opportunity
  // DOWN direction is best (price dropping = buy at lower price)
  // Higher confidence = better
  // Lower predicted price relative to current = better
  const dirScore = DIRECTION_SCORE[f.direction] ?? 0;
  const confScore = f.confidence_score; // 0–1
  const predicted = f.predicted_price_inr ? parseFloat(f.predicted_price_inr) : currentPrice;
  const priceScore = currentPrice > 0 ? Math.max(0, (currentPrice - predicted) / currentPrice) : 0;
  return dirScore * 0.5 + confScore * 0.3 + priceScore * 0.2;
}

export default function BuyingWindowFinder({ forecasts, currentPrices }: Props) {
  const today = new Date().toISOString().split("T")[0];
  const [neededBy, setNeededBy] = useState("");
  const [commodity, setCommodity] = useState("ALL");

  const priceMap: Record<string, number> = {};
  for (const p of currentPrices) priceMap[p.commodity] = p.price;

  const results = (() => {
    if (!neededBy) return [];
    const deadline = new Date(neededBy);
    const todayDate = new Date(today);

    return forecasts
      .filter((f) => {
        const td = new Date(f.target_date);
        if (td < todayDate || td > deadline) return false;
        if (commodity !== "ALL" && f.commodity !== commodity) return false;
        return true;
      })
      .map((f) => ({
        ...f,
        score: scoreWindow(f, priceMap[f.commodity] ?? 0),
        currentPrice: priceMap[f.commodity] ?? null,
      }))
      .sort((a, b) => b.score - a.score)
      .slice(0, 5);
  })();

  return (
    <div className="glass p-6 space-y-6">
      <div>
        <h2 className="text-lg font-bold text-green-300">Find Best Time to Buy</h2>
        <p className="text-xs text-yellow-400/70 mt-1">
          Enter your required date — we rank every forecast window by predicted price, direction, and confidence.
        </p>
      </div>

      {/* Inputs */}
      <div className="flex flex-col sm:flex-row gap-4">
        <div className="flex-1 space-y-1">
          <label className="text-xs text-green-400 uppercase tracking-wide">I need fertilizer by</label>
          <input
            type="date"
            min={today}
            value={neededBy}
            onChange={(e) => setNeededBy(e.target.value)}
            className="w-full bg-green-950/60 border border-green-700/40 rounded-lg px-3 py-2 text-green-300 text-sm focus:outline-none focus:border-green-400"
          />
        </div>
        <div className="flex-1 space-y-1">
          <label className="text-xs text-green-400 uppercase tracking-wide">Fertilizer</label>
          <select
            value={commodity}
            onChange={(e) => setCommodity(e.target.value)}
            className="w-full bg-green-950/60 border border-green-700/40 rounded-lg px-3 py-2 text-green-300 text-sm focus:outline-none focus:border-green-400"
          >
            <option value="ALL">All Fertilizers</option>
            <option value="UREA">🌱 Urea</option>
            <option value="DAP">🌾 DAP</option>
            <option value="MOP">🍀 MOP (Potash)</option>
          </select>
        </div>
      </div>

      {/* Results */}
      {neededBy && results.length === 0 && (
        <div className="text-center py-6 text-green-400/50 text-sm">
          No forecast windows found before {new Date(neededBy).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}.
          <br />
          <span className="text-xs">Try a later date or check back after the next forecast run.</span>
        </div>
      )}

      {results.length > 0 && (
        <div className="space-y-3">
          <div className="text-xs text-green-400/60 uppercase tracking-wide">
            Top {results.length} buying window{results.length > 1 ? "s" : ""} before{" "}
            {new Date(neededBy).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}
          </div>
          {results.map((f, i) => {
            const meta = COMMODITY_META[f.commodity];
            const predicted = f.predicted_price_inr ? parseFloat(f.predicted_price_inr) : null;
            const diff = predicted && f.currentPrice ? predicted - f.currentPrice : null;
            const conf = Math.round(f.confidence_score * 100);
            const rankColors = ["text-yellow-300", "text-green-300", "text-green-400", "text-green-400/70", "text-green-400/50"];
            return (
              <div key={f.id} className="flex items-center gap-4 bg-green-900/20 border border-green-800/30 rounded-lg px-4 py-3">
                <div className={`text-2xl font-black w-6 text-center ${rankColors[i]}`}>#{i + 1}</div>
                <div className="text-xl">{meta?.emoji}</div>
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-green-300 text-sm">{meta?.name ?? f.commodity}</span>
                    <span className="text-xs text-green-400/60">
                      {new Date(f.target_date).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}
                    </span>
                    <span className={`text-xs font-semibold px-1.5 py-0.5 rounded ${
                      f.direction === "DOWN" ? "bg-green-900/60 text-green-400" :
                      f.direction === "UP"   ? "bg-yellow-900/60 text-yellow-400" :
                                              "bg-green-900/30 text-green-300"
                    }`}>{f.direction}</span>
                  </div>
                  <div className="text-xs text-green-400/60 mt-0.5">
                    Confidence: <span className={conf >= 70 ? "text-green-400 font-bold" : "text-yellow-400 font-bold"}>{conf}%</span>
                  </div>
                </div>
                <div className="text-right">
                  {predicted && (
                    <div className="text-lg font-black text-green-300">₹{predicted.toFixed(0)}</div>
                  )}
                  {diff !== null && (
                    <div className={`text-xs font-bold ${diff < 0 ? "text-green-400" : "text-yellow-400"}`}>
                      {diff < 0 ? "▼ Save ₹" : "▲ +₹"}{Math.abs(diff).toFixed(0)} vs now
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
