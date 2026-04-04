import { NextResponse } from "next/server";
import pool from "@/lib/db";

export async function GET() {
  // Latest prices for all 3 commodities
  const prices = await pool.query(`
    SELECT DISTINCT ON (commodity)
      commodity, price_date, price_usd, price_inr, source
    FROM commodity_prices
    WHERE source IN ('WORLDBANK', 'FERT_NIC', 'AGMARKNET', 'ENAM')
      AND price_inr IS NOT NULL
    ORDER BY commodity,
      CASE source WHEN 'AGMARKNET' THEN 1 WHEN 'ENAM' THEN 2 WHEN 'FERT_NIC' THEN 3 ELSE 4 END,
      price_date DESC
  `);

  // Price 12 months ago for YoY comparison
  const pricesYoY = await pool.query(`
    SELECT DISTINCT ON (commodity)
      commodity, price_usd
    FROM commodity_prices
    WHERE source IN ('WORLDBANK', 'FERT_NIC', 'AGMARKNET', 'ENAM')
      AND price_inr IS NOT NULL
      AND price_date BETWEEN NOW() - INTERVAL '14 months' AND NOW() - INTERVAL '10 months'
    ORDER BY commodity,
      CASE source WHEN 'AGMARKNET' THEN 1 WHEN 'ENAM' THEN 2 WHEN 'FERT_NIC' THEN 3 ELSE 4 END,
      price_date DESC
  `);

  // Weather summary — latest for each district
  const weatherCount = await pool.query(`
    SELECT COUNT(DISTINCT district) as districts,
           COUNT(*) as total_records,
           MIN(observation_date) as from_date,
           MAX(observation_date) as to_date
    FROM weather_data
    WHERE is_forecast = FALSE
  `);

  const yoyMap: Record<string, number> = {};
  for (const row of pricesYoY.rows) {
    yoyMap[row.commodity] = parseFloat(row.price_usd);
  }

  const commodities = prices.rows.map((row) => {
    const prevPrice = yoyMap[row.commodity];
    const currentPrice = parseFloat(row.price_usd);
    const yoyChange = prevPrice
      ? ((currentPrice - prevPrice) / prevPrice) * 100
      : null;
    return {
      commodity: row.commodity,
      price_date: row.price_date,
      price_usd: currentPrice,
      price_inr: row.price_inr,
      yoy_change_pct: yoyChange ? Math.round(yoyChange * 10) / 10 : null,
    };
  });

  return NextResponse.json({
    commodities,
    weather: weatherCount.rows[0],
    last_updated: new Date().toISOString(),
  });
}
