"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import PriceChart, { type SourceFilter } from "./PriceChart";

interface Commodity {
  commodity: string;
  price_date: Date;
  price_usd: number;
  price_inr: string | number;
  yoy_pct: number | null;
}

interface CommodityCardProps {
  commodity: Commodity;
  info: { full: string; use: string; emoji: string };
  delay?: number;
}

const SOURCES: { key: SourceFilter; label: string }[] = [
  { key: "ALL",       label: "All" },
  { key: "WORLDBANK", label: "World Bank" },
  { key: "FERT_NIC",  label: "DoF MRP" },
];

export default function CommodityCard({ commodity: c, info, delay = 0 }: CommodityCardProps) {
  const [source, setSource] = useState<SourceFilter>("ALL");
  const isUp = c.yoy_pct && c.yoy_pct > 0;
  const isDown = c.yoy_pct && c.yoy_pct < 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 30 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-50px" }}
      transition={{ duration: 0.6, delay, type: "spring", stiffness: 60 }}
      whileHover={{ scale: 1.03, y: -8 }}
      className="glass p-6 space-y-5 relative group overflow-hidden border-t border-t-green-400/20"
    >
      <div className="absolute -inset-2 bg-gradient-to-r from-green-400/0 via-green-400/5 to-yellow-400/0 opacity-0 group-hover:opacity-100 transition duration-700 blur-xl z-0" />

      <div className="relative z-10 flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3">
            <motion.span
              whileHover={{ rotate: 15, scale: 1.2 }}
              className="text-2xl drop-shadow-md origin-bottom-right inline-block"
            >
              {info.emoji}
            </motion.span>
            <span className="font-bold text-lg text-green-300">{info.full}</span>
          </div>
          <div className="text-xs text-yellow-400/80 mt-1 uppercase tracking-wider font-semibold">{info.use}</div>
        </div>

        {c.yoy_pct !== null && (
          <motion.span
            initial={{ scale: 0.8 }}
            animate={{ scale: 1 }}
            className={isUp ? "badge-up" : isDown ? "badge-down" : "badge-stable"}
          >
            {isUp ? "▲" : isDown ? "▼" : "–"} {Math.abs(c.yoy_pct)}% YoY
          </motion.span>
        )}
      </div>

      <div className="relative z-10 flex flex-col gap-1">
        <div className="flex items-baseline gap-2">
          <span className="text-3xl font-black text-green-300">₹{parseFloat(c.price_inr.toString()).toFixed(0)}</span>
          <span className="text-sm font-medium text-green-400">/ 50kg bag</span>
        </div>
        <div className="text-xs text-yellow-400 font-medium">
          {new Date(c.price_date).toLocaleDateString("en-IN", { month: "long", year: "numeric" })}
        </div>
      </div>

      {/* Source selector */}
      <div className="relative z-10 flex gap-1.5 flex-wrap">
        {SOURCES.map((s) => (
          <button
            key={s.key}
            onClick={() => setSource(s.key)}
            className={`text-xs px-2.5 py-1 rounded-full border transition-all duration-150 font-medium ${
              source === s.key
                ? "bg-green-400 text-green-950 border-green-400"
                : "bg-transparent text-green-400/70 border-green-700/40 hover:border-green-500 hover:text-green-300"
            }`}
          >
            {s.label}
          </button>
        ))}
      </div>

      <div className="relative z-10 mt-2 pt-2 border-t border-green-800/30">
        <PriceChart commodity={c.commodity} source={source} />
      </div>
    </motion.div>
  );
}
