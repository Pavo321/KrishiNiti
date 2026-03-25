# KrishiNiti — Claude's Session Notes

## What This Project Is
**AI Farm Input Timing Optimizer** — predicts the best time for Indian farmers to buy fertilizers (Urea, DAP, MOP) and seeds, saving 25–40% on input costs.
- Delivery: WhatsApp alerts in Gujarati
- Target users: Small farmers near Ahmedabad (2–5 acre holdings)
- Market: $250B agri-input market

## The Real Problem We're Solving
Farmers buy inputs when they have cash (post-harvest), not when prices are low. Price gaps are 20–40% seasonal. No predictive tool exists for small farmers. We fix the timing.

## Our 7 Differentiators (Already Brainstormed — Don't Re-suggest These as New)
1. **Collective Flash Buying** — aggregate 500+ farmers, negotiate bulk rates with distributors when model predicts dip
2. **Input Substitution Intelligence** — "Skip DAP, buy SSP+MOP for same NPK at 23% less"
3. **Micro-Hedging Instrument** — farmer pays ₹500 to lock in price for 3 months; we hedge on NCDEX
4. **Credit Timing Alignment** — partner with NBFCs, trigger micro-loan when buying window opens
5. **Soil-Adjusted Recommendations** — cross-reference Soil Health Card data, reduce over-buying
6. **Government Scheme Timing** — model PM-KISAN disbursements, neem-urea subsidy cycles as price signals
7. **Laminated Season Calendar** — printed 6-month buying calendar delivered physically to low-connectivity farmers

## Tech Stack
- ML: LSTM + Prophet ensemble
- Inputs: Urea, DAP, MOP, seed prices
- Data: Agmarknet, NCDEX, IMD weather, World Bank Pink Sheet
- Backend: Daily forecast jobs
- Delivery: WhatsApp Business API
- Language: Gujarati

## Team Roles
| Person | Role | Owns |
|--------|------|------|
| Person 1 | ML / Forecasting | LSTM+Prophet model, backtesting |
| Person 2 | Data Pipeline | Agmarknet scraping, IMD API, daily refresh |
| Person 3 | Backend + Alerts | WhatsApp delivery, crop calendar logic, farmer preferences |
| Person 4 | Field Research + UX | Village visits, farmer recruitment, Gujarati translation, impact tracking |

## Data Sources (Already Identified)
| Data | Source |
|------|--------|
| Fertilizer prices (global, 60yr history) | World Bank Pink Sheet Excel |
| India mandi prices | agmarknet.gov.in |
| Fertilizer futures | ncdex.com/market-data |
| Global fertilizer indices | FAO GIEWS |
| India retail fertilizer prices | fert.nic.in |
| Weather (historical + forecast) | IMD, NASA POWER API, Open-Meteo (free) |
| Soil health data | data.gov.in (Soil Health Card scheme) |
| Real transaction prices | eNAM |
| State-level input prices | APEDA, Gujarat GSAPS portal |

## Biggest Risk to Always Keep in Mind
**Last-mile trust** — if the model is wrong and a farmer loses money following our advice, word spreads in villages and kills adoption. Every alert must show a confidence score. Model must be right 70%+ in Year 1.

## How Jignesh Likes to Work
- Direct, no fluff answers
- Skip obvious ideas — he wants things nobody has thought of
- He thinks at startup scale, not just feature scale
- Don't repeat ideas already in this file as if they're new
- Give code when asked, give strategy when asked — don't mix unless relevant
- He is building this as a real product, not a hackathon project

## Current Status
- Ideation phase complete
- Data sources identified
- No code written yet
- Next: build data pipeline (Person 2 scope) — scrape World Bank Pink Sheet + Agmarknet historical data

## What NOT to Do
- Don't suggest building a mobile app — WhatsApp is the deliberate choice for rural penetration
- Don't suggest generic "price alert" features — that's what we're replacing, not building
- Don't over-engineer the ML before the data pipeline exists
- Don't ignore the Gujarati language requirement for all farmer-facing output
