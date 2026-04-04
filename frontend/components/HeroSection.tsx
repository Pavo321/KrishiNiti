"use client";

import Link from "next/link";
import { motion, Variants } from "framer-motion";
import { Sprout, Sun, Tractor, CloudRain } from "lucide-react";

export default function HeroSection() {
  const containerVariants: Variants = {
    hidden: { opacity: 0 },
    visible: { opacity: 1, transition: { staggerChildren: 0.2 } },
  };

  const itemVariants: Variants = {
    hidden: { opacity: 0, y: 30 },
    visible: { opacity: 1, y: 0, transition: { type: "spring", stiffness: 50, damping: 10 } },
  };

  return (
    <motion.div
      className="relative w-full py-16 lg:py-24 flex flex-col items-center justify-center text-center px-4"
      variants={containerVariants}
      initial="hidden"
      animate="visible"
    >
      <motion.div
        animate={{ y: [0, -15, 0], rotate: [0, 5, -5, 0] }}
        transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
        className="absolute top-10 left-[10%] text-yellow-400 opacity-60"
      >
        <Sun size={64} />
      </motion.div>
      <motion.div
        animate={{ y: [0, 20, 0], x: [0, -10, 0] }}
        transition={{ duration: 5, repeat: Infinity, ease: "easeInOut", delay: 1 }}
        className="absolute bottom-10 right-[15%] text-green-400 opacity-50"
      >
        <CloudRain size={48} />
      </motion.div>

      <motion.div
        variants={itemVariants}
        className="inline-flex items-center gap-3 mb-6 bg-green-900/40 border border-green-500/30 px-6 py-2 rounded-full backdrop-blur-md"
      >
        <Sprout className="text-green-400" size={20} />
        <span className="text-green-400 font-medium tracking-wide text-sm uppercase">
          Next Generation Farming Intelligence
        </span>
      </motion.div>

      <motion.h1
        variants={itemVariants}
        className="text-5xl md:text-7xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-green-300 via-green-400 to-yellow-300 mb-6 drop-shadow-xl"
      >
        KrishiNiti
      </motion.h1>

      <motion.p
        variants={itemVariants}
        className="max-w-2xl text-lg md:text-xl text-green-300 leading-relaxed font-light"
      >
        Real-time fertilizer price intelligence for Indian farmers.
        <br className="hidden md:block" /> Powered by{" "}
        <span className="text-yellow-400 font-semibold">dynamic data</span> and natural rhythms.
      </motion.p>

      <motion.div variants={itemVariants} className="mt-10 flex gap-4">
        <Link href="/prices" className="relative group overflow-hidden rounded-full p-[1px]">
          <span className="absolute inset-0 bg-gradient-to-r from-green-400 to-yellow-400 rounded-full opacity-70 group-hover:opacity-100 transition-opacity duration-300" />
          <div className="relative bg-[#061e14] px-8 py-3 rounded-full flex items-center gap-2 transition-all duration-300 group-hover:bg-transparent">
            <Tractor size={20} className="text-green-400 group-hover:text-black transition-colors" />
            <span className="font-semibold text-green-400 group-hover:text-black transition-colors">
              Explore Prices
            </span>
          </div>
        </Link>
      </motion.div>
    </motion.div>
  );
}
