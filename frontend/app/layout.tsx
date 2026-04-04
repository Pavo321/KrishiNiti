import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "KrishiNiti — AI Farm Input Timing",
  description: "Predicts best time for Indian farmers to buy fertilizers. Saves 25–40% on input costs.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <nav className="border-b border-[#2d4a2d] px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-2xl">🌾</span>
            <span className="font-bold text-lg text-[#4ade80]">KrishiNiti</span>
            <span className="text-yellow-400/70 text-sm">AI Farm Input Timing</span>
          </div>
          <div className="flex gap-6 text-sm text-green-400">
            <a href="/" className="hover:text-[#4ade80] transition-colors">Dashboard</a>
            <a href="/forecasts" className="hover:text-[#4ade80] transition-colors">Forecasts</a>
            <a href="/prices" className="hover:text-[#4ade80] transition-colors">Price History</a>
            <a href="/planner" className="hover:text-[#4ade80] transition-colors">Planner</a>
            <a href="/analysis" className="hover:text-[#4ade80] transition-colors">Analysis</a>
          </div>
        </nav>
        <main className="max-w-7xl mx-auto px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
