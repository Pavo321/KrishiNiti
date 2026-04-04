export const dynamic = "force-dynamic";

import pool from "@/lib/db";
import AnimatedBackground from "@/components/AnimatedBackground";
import HeroSection from "@/components/HeroSection";
import StatCard from "@/components/StatCard";
import CommodityCard from "@/components/CommodityCard";
import { Database, CloudSun, MapPin } from "lucide-react";

async function getSummary() {
  const prices = await pool.query(`
    SELECT DISTINCT ON (commodity)
      commodity, price_date, price_usd, price_inr
    FROM commodity_prices
    WHERE source IN ('WORLDBANK', 'FERT_NIC', 'AGMARKNET', 'ENAM')
      AND price_inr IS NOT NULL
    ORDER BY commodity, price_date DESC
  `);

  const pricesYoY = await pool.query(`
    SELECT DISTINCT ON (commodity)
      commodity, price_inr
    FROM commodity_prices
    WHERE source IN ('WORLDBANK', 'FERT_NIC', 'AGMARKNET', 'ENAM')
      AND price_inr IS NOT NULL
      AND price_date BETWEEN NOW() - INTERVAL '14 months' AND NOW() - INTERVAL '10 months'
    ORDER BY commodity, price_date DESC
  `);

  const weatherCount = await pool.query(`
    SELECT COUNT(DISTINCT district) as districts, COUNT(*) as total_records
    FROM weather_data WHERE is_forecast = FALSE
  `);

  const priceCount = await pool.query(`
    SELECT COUNT(*) as total,
           COUNT(DISTINCT source) as sources,
           MIN(price_date) as from_date,
           MAX(price_date) as to_date
    FROM commodity_prices
    WHERE source IN ('WORLDBANK', 'FERT_NIC', 'AGMARKNET', 'ENAM')
  `);

  const forecasts30d = await pool.query(`
    SELECT DISTINCT ON (commodity)
      commodity, direction, confidence_score, predicted_price_inr, target_date
    FROM forecasts
    WHERE target_date BETWEEN CURRENT_DATE + 25 AND CURRENT_DATE + 35
    ORDER BY commodity, forecast_date DESC
  `);

  const yoyMap: Record<string, number> = {};
  for (const row of pricesYoY.rows) yoyMap[row.commodity] = parseFloat(row.price_inr);

  const commodities = prices.rows.map((row) => {
    const prev = yoyMap[row.commodity];
    const curr = parseFloat(row.price_inr);
    const yoy = prev ? ((curr - prev) / prev) * 100 : null;
    return { ...row, price_inr: curr, price_usd: parseFloat(row.price_usd), yoy_pct: yoy ? Math.round(yoy * 10) / 10 : null };
  });

  return {
    commodities,
    districts: weatherCount.rows[0].districts,
    weatherRecords: parseInt(weatherCount.rows[0].total_records).toLocaleString("en-IN"),
    priceRecords: parseInt(priceCount.rows[0].total).toLocaleString("en-IN"),
    priceSources: parseInt(priceCount.rows[0].sources),
    priceFromYear: new Date(priceCount.rows[0].from_date).getFullYear(),
    priceToYear: new Date(priceCount.rows[0].to_date).getFullYear(),
    forecasts30d: forecasts30d.rows,
  };
}

const COMMODITY_INFO: Record<string, { full: string; use: string; emoji: string }> = {
  UREA:       { full: "Urea",              use: "Nitrogen fertilizer",             emoji: "🌱" },
  DAP:        { full: "DAP",               use: "Phosphate fertilizer",            emoji: "🌾" },
  MOP:        { full: "MOP (Potash)",      use: "Potassium fertilizer",            emoji: "🍀" },
  SSP:        { full: "SSP",               use: "Phosphate + Sulphur fertilizer",  emoji: "🪨" },
  NPK_102626: { full: "NPK 10:26:26",      use: "Complex fertilizer",              emoji: "🔬" },
};

const ADVICE_COLOR: Record<string, string> = {
  UP:     "border-yellow-500/40 bg-yellow-900/10",
  DOWN:   "border-green-500/40 bg-green-900/10",
  STABLE: "border-green-700/30 bg-green-900/5",
};

export default async function Dashboard() {
  const { commodities, districts, weatherRecords, priceRecords, priceSources, priceFromYear, priceToYear, forecasts30d } = await getSummary();

  return (
    <div className="min-h-screen relative font-sans">
      <AnimatedBackground />

      <main className="relative z-10 container mx-auto px-4 pb-20 max-w-6xl">
        <HeroSection />

        {/* Stats */}
        <section className="mb-16">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <StatCard label="Price Records"     value={priceRecords}   sub={`${priceSources} sources · ${priceFromYear}–${priceToYear}`} icon={<Database size={32} />} delay={0.1} />
            <StatCard label="Weather Records"   value={weatherRecords} sub="Open-Meteo · 59 districts" icon={<CloudSun size={32} />} delay={0.2} />
            <StatCard label="Districts Covered" value={districts}      sub="Across India"          icon={<MapPin size={32} />}   delay={0.3} />
          </div>
        </section>

        {/* AI Recommendations */}
        {forecasts30d.length > 0 && (
          <section className="mb-16">
            <div className="flex items-center gap-3 mb-6 px-2">
              <div className="h-10 w-2 bg-gradient-to-b from-yellow-400 to-green-400 rounded-full" />
              <div>
                <h2 className="text-2xl font-extrabold text-green-300">AI Buying Recommendations</h2>
                <p className="text-yellow-400/70 text-xs font-medium uppercase tracking-widest mt-1">30-day Prophet + XGBoost + LSTM ensemble forecast</p>
              </div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 xl:grid-cols-5 gap-4">
              {forecasts30d.map((f) => {
                const conf = Math.round(f.confidence_score * 100);
                return (
                  <div key={f.commodity} className={`glass p-5 border ${ADVICE_COLOR[f.direction] || ""} space-y-3`}>
                    <div className="flex items-center gap-2">
                      <span className="text-xl">{COMMODITY_INFO[f.commodity]?.emoji || "🌾"}</span>
                      <span className="font-bold text-green-300 text-lg">{f.commodity}</span>
                      <span className="ml-auto text-xs text-green-400/60">
                        {new Date(f.target_date).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
                      </span>
                    </div>
                    <div className="w-full bg-green-900/40 rounded-full h-2">
                      <div className={`h-2 rounded-full ${conf >= 70 ? "bg-green-400" : "bg-yellow-400"}`}
                        style={{ width: `${conf}%` }} />
                    </div>
                    <div className="flex justify-between text-xs text-green-400/60">
                      <span>AI Confidence</span>
                      <span className={conf >= 70 ? "text-green-400 font-bold" : "text-yellow-400 font-bold"}>{conf}%</span>
                    </div>
                    {f.predicted_price_inr && (
                      <div className="text-center">
                        <div className="text-2xl font-black text-green-300">₹{parseFloat(f.predicted_price_inr).toFixed(0)}</div>
                        <div className="text-xs text-yellow-400/60">predicted / 50kg bag</div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {/* Commodity Price Cards */}
        <section className="mb-16">
          <div className="flex items-center gap-3 mb-6 px-2">
            <div className="h-10 w-2 bg-gradient-to-b from-green-300 to-yellow-400 rounded-full" />
            <div>
              <h2 className="text-2xl font-extrabold text-green-300">Live Fertilizer Prices</h2>
              <p className="text-yellow-400/70 text-xs font-medium uppercase tracking-widest mt-1">Agmarknet + World Bank + eNAM + fert.nic.in</p>
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 xl:grid-cols-5 gap-8">
            {commodities.map((c, i) => {
              const info = COMMODITY_INFO[c.commodity] || { full: c.commodity, use: "Unknown", emoji: "🌾" };
              return <CommodityCard key={c.commodity} commodity={c} info={info} delay={0.1 * i} />;
            })}
          </div>
        </section>

        {/* Coverage */}
        <section className="glass p-8 mb-12">
          <div className="flex flex-col md:flex-row gap-8 items-start justify-between">
            <div className="md:w-1/3">
              <h2 className="text-xl font-bold mb-2 text-green-300">All India Coverage</h2>
              <p className="text-green-400 mb-2 text-sm leading-relaxed">
                <span className="font-bold text-yellow-400">{districts} districts</span> with daily weather data.
                Forecasts available for every major farming region.
              </p>
            </div>
            <div className="md:w-2/3 flex flex-wrap gap-2">
              {["Punjab","Haryana","Uttar Pradesh","Madhya Pradesh","Maharashtra",
                "Rajasthan","Bihar","West Bengal","Andhra Pradesh","Telangana",
                "Karnataka","Tamil Nadu","Odisha","Chhattisgarh","Jharkhand",
                "Assam","Kerala","Himachal Pradesh","Uttarakhand","Gujarat"
              ].map((state) => (
                <span key={state}
                  className="text-xs font-semibold px-3 py-1 rounded-full bg-green-950/40 border border-green-700/30 text-green-400 hover:text-green-950 hover:bg-green-400 hover:border-green-400 transition-all duration-200 cursor-default">
                  {state}
                </span>
              ))}
            </div>
          </div>
        </section>

        <footer className="text-center pb-8 pt-4 border-t border-green-800/20">
          <p className="text-xs text-green-400/40 uppercase tracking-widest font-semibold mb-2">Data Sources</p>
          <div className="flex justify-center flex-wrap gap-6 text-sm text-green-400">
            <span className="flex items-center gap-2"><span className="w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse" /> World Bank Pink Sheet</span>
            <span className="flex items-center gap-2"><span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" /> Agmarknet</span>
            <span className="flex items-center gap-2"><span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" /> eNAM</span>
            <span className="flex items-center gap-2"><span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" /> fert.nic.in</span>
            <span className="flex items-center gap-2"><span className="w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse" /> NCDEX</span>
            <span className="flex items-center gap-2"><span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" /> Open-Meteo</span>
          </div>
        </footer>
      </main>
    </div>
  );
}
