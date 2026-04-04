import { NextResponse } from "next/server";
import pool from "@/lib/db";

const VALID_SOURCES = ["WORLDBANK", "FERT_NIC", "AGMARKNET", "ENAM", "PPAC"];

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const commodity = searchParams.get("commodity") || "UREA";
  const months = parseInt(searchParams.get("months") || "24");
  const sourceParam = searchParams.get("source");

  const allowedSources = sourceParam && VALID_SOURCES.includes(sourceParam)
    ? [sourceParam]
    : ["WORLDBANK", "FERT_NIC", "AGMARKNET", "ENAM"];

  const placeholders = allowedSources.map((_, i) => `$${i + 2}`).join(", ");

  const result = await pool.query(
    `SELECT price_date, commodity, price_usd, price_inr, unit, source
     FROM commodity_prices
     WHERE commodity = $1
       AND source IN (${placeholders})
       AND price_inr IS NOT NULL
       AND price_date >= NOW() - INTERVAL '${months} months'
     ORDER BY price_date ASC`,
    [commodity, ...allowedSources]
  );

  return NextResponse.json(result.rows);
}
