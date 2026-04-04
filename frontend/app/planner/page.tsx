export const dynamic = "force-dynamic";

import pool from "@/lib/db";
import BuyingWindowFinder from "@/components/BuyingWindowFinder";

async function getData() {
  const [forecastsRes, pricesRes] = await Promise.all([
    pool.query(`
      SELECT id, target_date, commodity, direction, confidence_score, predicted_price_inr
      FROM forecasts
      WHERE target_date >= CURRENT_DATE
      ORDER BY commodity, target_date
    `),
    pool.query(`
      SELECT DISTINCT ON (commodity)
        commodity, price_inr, source
      FROM commodity_prices
      WHERE source IN ('WORLDBANK', 'FERT_NIC', 'AGMARKNET', 'ENAM')
        AND price_inr IS NOT NULL
      ORDER BY commodity,
        CASE source WHEN 'AGMARKNET' THEN 1 WHEN 'ENAM' THEN 2 WHEN 'FERT_NIC' THEN 3 ELSE 4 END,
        price_date DESC
    `),
  ]);

  return {
    forecasts: forecastsRes.rows,
    currentPrices: pricesRes.rows.map((r) => ({
      commodity: r.commodity,
      price: parseFloat(r.price_inr),
    })),
  };
}

export default async function PlannerPage() {
  const { forecasts, currentPrices } = await getData();

  return (
    <div className="space-y-8 max-w-3xl mx-auto">
      <div>
        <h1 className="text-2xl font-bold text-green-400">Buying Planner</h1>
        <p className="text-yellow-400/70 text-sm mt-1">
          Tell us when you need fertilizer — we'll find the best 5 windows to buy before that date.
        </p>
      </div>

      <BuyingWindowFinder forecasts={forecasts} currentPrices={currentPrices} />

      <div className="glass p-5 text-xs text-green-400/60 space-y-1 border-l-4 border-green-700/40">
        <div className="font-semibold text-green-400 mb-2">How we rank windows</div>
        <div>• <span className="text-green-300">Direction DOWN</span> — price predicted to fall → best to buy at that date</div>
        <div>• <span className="text-green-300">Higher confidence</span> — model is more certain about this prediction</div>
        <div>• <span className="text-green-300">Lower predicted price</span> — bigger saving vs today's market price</div>
      </div>
    </div>
  );
}
