"use client";

import { motion } from "framer-motion";
import { ReactNode } from "react";

interface StatCardProps {
  label: string;
  value: string | number;
  sub: string;
  icon?: ReactNode;
  delay?: number;
}

export default function StatCard({ label, value, sub, icon, delay = 0 }: StatCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.9, y: 20 }}
      whileInView={{ opacity: 1, scale: 1, y: 0 }}
      viewport={{ once: true }}
      transition={{ duration: 0.5, delay, type: "spring", bounce: 0.4 }}
      whileHover={{ scale: 1.05, y: -5 }}
      style={{ transformStyle: "preserve-3d" }}
      className="glass p-6 relative group cursor-default overflow-hidden"
    >
      {/* Dynamic light reflection on hover */}
      <div className="absolute inset-0 bg-gradient-to-tr from-transparent via-white/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500 ease-in-out pointer-events-none translate-x-[-100%] group-hover:translate-x-[100%] z-10 skew-x-12" />
      
      <div className="flex justify-between items-start mb-2 relative z-20">
        <div className="text-3xl font-black text-green-400 text-glow tracking-tight">{value}</div>
        {icon && <div className="text-green-500/50 group-hover:text-yellow-400 transition-colors duration-300 group-hover:text-glow-yellow">{icon}</div>}
      </div>
      <div className="text-sm font-semibold text-green-400 relative z-20">{label}</div>
      <div className="text-xs text-yellow-400/70 mt-1 relative z-20 font-light">{sub}</div>
    </motion.div>
  );
}
