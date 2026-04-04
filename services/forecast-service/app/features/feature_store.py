"""
Feature store: builds the feature matrix for ML models from DB data.
Single source of truth for all features — computed once, reused by all models.

v2: Uses local Agmarknet/fert.nic.in/eNAM prices as primary signal.
    Falls back to World Bank if local data < 12 months.
    Adds 9 new features: NCDEX futures, diesel price, PM-KISAN flag,
    retail MRP, rainfall anomaly, demand pressure index.
"""

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd
import psycopg2

logger = logging.getLogger(__name__)

FEATURE_COLUMNS = [
    # Core price features (now from local mandi prices)
    "price_inr",
    "price_lag_1m",
    "price_lag_3m",
    "price_lag_6m",
    "price_lag_12m",
    "price_rolling_mean_3m",
    "price_rolling_std_3m",
    "price_rolling_mean_6m",
    # Seasonal encoding
    "month_sin",
    "month_cos",
    # Weather
    "precipitation_mm",
    "temp_avg_c",
    "rainfall_anomaly",         # deviation from 3yr monthly mean (drought/flood signal)
    # Market signals (new in v2)
    "ncdex_futures_premium",    # NCDEX futures price - current spot (forward premium/discount)
    "diesel_price_inr",         # HSD retail price (logistics cost proxy)
    "diesel_mom_pct",           # diesel month-on-month change
    "pmkisan_flag",             # 1 if PM-KISAN tranche released in past 30 days
    "demand_season_score",      # 0-1 score: 1=peak kharif/rabi demand, 0=off-season
    "retail_mrp_inr",           # fert.nic.in retail MRP (what farmers pay at shop)
]

# Prophet still needs price_usd for its own log-transform training
PROPHET_COLUMNS = FEATURE_COLUMNS + ["price_usd"]

# Local sources in priority order — prefer granular/local over global
LOCAL_PRICE_SOURCES = ("AGMARKNET", "ENAM", "FERT_NIC")
GLOBAL_PRICE_SOURCES = ("WORLDBANK",)
MIN_LOCAL_MONTHS = 12  # need at least 12 months of local data to use it


def build_feature_matrix(
    conn,
    commodity: str,
    district: str = "Ludhiana",
    state: str = "Punjab",
    end_date: date | None = None,
    lookback_months: int = 36,
) -> pd.DataFrame:
    """
    Builds a feature matrix for a given commodity up to end_date.
    v2: Prefers local mandi prices over World Bank global benchmarks.
    """
    if end_date is None:
        end_date = date.today()
    start_date = date(end_date.year - (lookback_months // 12 + 2), 1, 1)

    # Load prices — prefer local, fall back to World Bank
    prices = _load_prices_smart(conn, commodity, district, state, start_date, end_date)
    weather = _load_weather(conn, district, state, start_date, end_date)
    market = _load_market_signals(conn, commodity, start_date, end_date)

    if prices.empty:
        raise ValueError(
            f"No price data found for {commodity} between {start_date} and {end_date}. "
            "Run the data ingestion pipeline first."
        )

    df = _merge_and_engineer(prices, weather, market)
    logger.info(
        f"Built feature matrix: {commodity}, {len(df)} rows, "
        f"{df.index.min()} to {df.index.max()}, "
        f"source={prices.attrs.get('source', 'UNKNOWN')}"
    )
    return df


def _load_prices_smart(conn, commodity: str, district: str, state: str,
                        start_date: date, end_date: date) -> pd.DataFrame:
    """
    Loads price data preferring local mandi sources.
    Falls back to World Bank if local data insufficient.
    """
    # Try local sources first (Agmarknet for this specific district, or any district in state)
    local_df = _load_local_prices(conn, commodity, district, state, start_date, end_date)

    if len(local_df) >= MIN_LOCAL_MONTHS:
        local_df.attrs["source"] = "LOCAL"
        logger.info(f"Using local mandi prices for {commodity}/{district}: {len(local_df)} months")
        return local_df

    # SSP and NPK have no World Bank data — only local sources exist
    LOCAL_ONLY_COMMODITIES = ("SSP", "NPK_102626", "NPK_123216")
    if commodity in LOCAL_ONLY_COMMODITIES:
        if local_df.empty:
            raise ValueError(
                f"No local price data found for {commodity}. "
                "Run `POST /api/v1/jobs/run-ingest` to fetch Agmarknet/fert.nic.in data first."
            )
        # Use whatever local data we have even if < MIN_LOCAL_MONTHS
        local_df.attrs["source"] = "LOCAL"
        logger.warning(
            f"Using {len(local_df)} months of local data for {commodity} "
            f"(below {MIN_LOCAL_MONTHS}-month ideal minimum)."
        )
        return local_df

    # Fall back to World Bank for UREA/DAP/MOP
    logger.info(
        f"Local data insufficient for {commodity}/{district} ({len(local_df)} months < {MIN_LOCAL_MONTHS}). "
        "Falling back to World Bank."
    )
    wb_df = _load_worldbank_prices(conn, commodity, start_date, end_date)
    wb_df.attrs["source"] = "WORLDBANK"
    return wb_df


def _load_local_prices(conn, commodity: str, district: str, state: str,
                        start_date: date, end_date: date) -> pd.DataFrame:
    """
    Loads Agmarknet/eNAM/fert.nic.in prices.
    Applies IQR-based outlier capping and 3-day forward fill for gaps.
    """
    sources_placeholder = ",".join(["%s"] * len(LOCAL_PRICE_SOURCES))
    query = f"""
        SELECT price_date, AVG(price_inr) AS price_inr
        FROM commodity_prices
        WHERE commodity = %s
          AND price_date BETWEEN %s AND %s
          AND source IN ({sources_placeholder})
          AND price_inr IS NOT NULL
          AND price_inr > 0
          AND (district = %s OR state = %s OR district IS NULL)
        GROUP BY price_date
        ORDER BY price_date
    """
    params = (commodity, start_date, end_date) + LOCAL_PRICE_SOURCES + (district, state)

    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=["price_date", "price_inr"])
    df["price_date"] = pd.to_datetime(df["price_date"])
    df["price_inr"] = pd.to_numeric(df["price_inr"], errors="coerce")
    df = df.set_index("price_date").sort_index()

    # IQR outlier capping per commodity
    q1, q3 = df["price_inr"].quantile([0.15, 0.85])
    iqr = q3 - q1
    df["price_inr"] = df["price_inr"].clip(q1 - 2.5 * iqr, q3 + 2.5 * iqr)

    # Resample to monthly mean (daily mandi data → monthly for Prophet)
    df = df.resample("MS").mean()

    # Add price_usd estimate for Prophet compatibility (reverse convert)
    USD_TO_INR = 83.5
    df["price_usd"] = (df["price_inr"] * 1000) / (USD_TO_INR * 50)

    return df


def _load_worldbank_prices(conn, commodity: str, start_date: date, end_date: date) -> pd.DataFrame:
    query = """
        SELECT price_date, price_usd, price_inr
        FROM commodity_prices
        WHERE commodity = %s
          AND price_date BETWEEN %s AND %s
          AND source = 'WORLDBANK'
          AND price_usd IS NOT NULL
        ORDER BY price_date
    """
    with conn.cursor() as cur:
        cur.execute(query, (commodity, start_date, end_date))
        rows = cur.fetchall()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=["price_date", "price_usd", "price_inr"])
    df["price_date"] = pd.to_datetime(df["price_date"])
    df["price_usd"] = pd.to_numeric(df["price_usd"], errors="coerce")
    df["price_inr"] = pd.to_numeric(df["price_inr"], errors="coerce")
    df = df.set_index("price_date").sort_index()
    df = df.resample("MS").mean()
    return df


def _load_weather(conn, district: str, state: str, start_date: date, end_date: date) -> pd.DataFrame:
    query = """
        SELECT DATE_TRUNC('month', observation_date) AS date,
               AVG(precipitation_mm) AS precipitation_mm,
               AVG(temp_avg_c) AS temp_avg_c
        FROM weather_data
        WHERE (district = %s OR state = %s)
          AND observation_date BETWEEN %s AND %s
          AND is_forecast = FALSE
          AND temp_avg_c IS NOT NULL
        GROUP BY DATE_TRUNC('month', observation_date)
        ORDER BY DATE_TRUNC('month', observation_date)
    """
    with conn.cursor() as cur:
        cur.execute(query, (district, state, start_date, end_date))
        rows = cur.fetchall()

    if not rows:
        logger.warning(f"No weather data for {district}/{state}. Using defaults.")
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=["date", "precipitation_mm", "temp_avg_c"])
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df = df.set_index("date").sort_index()
    return df


def _load_market_signals(conn, commodity: str, start_date: date, end_date: date) -> pd.DataFrame:
    """
    Loads NCDEX futures prices, diesel prices, and PM-KISAN events.
    Returns monthly aggregated signals.
    """
    signals = {}

    # NCDEX futures settlement prices
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DATE_TRUNC('month', event_date) AS month,
                       AVG(price_inr) AS ncdex_price
                FROM market_events
                WHERE event_type = 'NCDEX_SETTLEMENT'
                  AND commodity = %s
                  AND event_date BETWEEN %s AND %s
                GROUP BY DATE_TRUNC('month', event_date)
                ORDER BY 1
            """, (commodity, start_date, end_date))
            ncdex_rows = cur.fetchall()
        if ncdex_rows:
            ncdex_df = pd.DataFrame(ncdex_rows, columns=["date", "ncdex_price"])
            ncdex_df["date"] = pd.to_datetime(ncdex_df["date"]).dt.tz_localize(None)
            signals["ncdex_price"] = ncdex_df.set_index("date")["ncdex_price"]
    except Exception as e:
        logger.debug(f"NCDEX signals not available: {e}")

    # Diesel prices
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DATE_TRUNC('month', price_date) AS month,
                       AVG(price_inr) AS diesel_price
                FROM commodity_prices
                WHERE commodity = 'DIESEL'
                  AND source = 'PPAC'
                  AND price_date BETWEEN %s AND %s
                GROUP BY DATE_TRUNC('month', price_date)
                ORDER BY 1
            """, (start_date, end_date))
            diesel_rows = cur.fetchall()
        if diesel_rows:
            diesel_df = pd.DataFrame(diesel_rows, columns=["date", "diesel_price"])
            diesel_df["date"] = pd.to_datetime(diesel_df["date"]).dt.tz_localize(None)
            signals["diesel_price"] = diesel_df.set_index("date")["diesel_price"]
    except Exception as e:
        logger.debug(f"Diesel prices not available: {e}")

    # PM-KISAN tranche events (binary flag: was there a tranche in this month?)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DATE_TRUNC('month', event_date) AS month, COUNT(*) AS count
                FROM market_events
                WHERE event_type = 'PMKISAN_TRANCHE'
                  AND event_date BETWEEN %s AND %s
                GROUP BY DATE_TRUNC('month', event_date)
            """, (start_date, end_date))
            pmkisan_rows = cur.fetchall()
        if pmkisan_rows:
            pm_df = pd.DataFrame(pmkisan_rows, columns=["date", "count"])
            pm_df["date"] = pd.to_datetime(pm_df["date"]).dt.tz_localize(None)
            signals["pmkisan_flag"] = pm_df.set_index("date")["count"].clip(upper=1)
    except Exception as e:
        logger.debug(f"PM-KISAN signals not available: {e}")

    # Retail MRP from fert.nic.in
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DATE_TRUNC('month', price_date) AS month,
                       AVG(price_inr) AS retail_mrp
                FROM commodity_prices
                WHERE commodity = %s
                  AND source = 'FERT_NIC'
                  AND price_date BETWEEN %s AND %s
                GROUP BY DATE_TRUNC('month', price_date)
                ORDER BY 1
            """, (commodity, start_date, end_date))
            mrp_rows = cur.fetchall()
        if mrp_rows:
            mrp_df = pd.DataFrame(mrp_rows, columns=["date", "retail_mrp"])
            mrp_df["date"] = pd.to_datetime(mrp_df["date"]).dt.tz_localize(None)
            signals["retail_mrp"] = mrp_df.set_index("date")["retail_mrp"]
    except Exception as e:
        logger.debug(f"Retail MRP not available: {e}")

    if not signals:
        return pd.DataFrame()

    result = pd.DataFrame(signals)
    result.index = pd.to_datetime(result.index)
    return result


def _demand_season_score(month: int) -> float:
    """
    Returns 0-1 score for fertilizer demand pressure by month.
    Kharif sowing: May-July (score ~1.0)
    Rabi sowing: Oct-Nov (score ~0.8)
    Off-season: Jan-Mar (score ~0.2)
    """
    scores = {1: 0.2, 2: 0.2, 3: 0.3, 4: 0.5, 5: 0.9, 6: 1.0,
              7: 1.0, 8: 0.8, 9: 0.6, 10: 0.9, 11: 0.8, 12: 0.4}
    return scores.get(month, 0.5)


def _merge_and_engineer(prices: pd.DataFrame, weather: pd.DataFrame,
                         market: pd.DataFrame) -> pd.DataFrame:
    # Cast all numeric columns to float — PostgreSQL returns Decimal which breaks numpy ops
    prices = prices.apply(pd.to_numeric, errors="coerce")
    if not weather.empty:
        weather = weather.apply(pd.to_numeric, errors="coerce")
    if not market.empty:
        market = market.apply(pd.to_numeric, errors="coerce")

    df = prices.copy()
    price_col = "price_inr"  # primary price column (local INR)

    # Lag features
    df["price_lag_1m"] = df[price_col].shift(1)
    df["price_lag_3m"] = df[price_col].shift(3)
    df["price_lag_6m"] = df[price_col].shift(6)
    df["price_lag_12m"] = df[price_col].shift(12)

    # Rolling statistics
    df["price_rolling_mean_3m"] = df[price_col].rolling(3).mean()
    df["price_rolling_std_3m"] = df[price_col].rolling(3).std()
    df["price_rolling_mean_6m"] = df[price_col].rolling(6).mean()

    # Seasonal encoding
    df["month_sin"] = np.sin(2 * np.pi * df.index.month / 12)
    df["month_cos"] = np.cos(2 * np.pi * df.index.month / 12)

    # Demand season score
    df["demand_season_score"] = df.index.month.map(_demand_season_score)

    # Merge weather
    if not weather.empty:
        df = df.join(weather[["precipitation_mm", "temp_avg_c"]], how="left")
        median_precip = df["precipitation_mm"].median()
        median_temp = df["temp_avg_c"].median()
        df["precipitation_mm"] = df["precipitation_mm"].fillna(median_precip)
        df["temp_avg_c"] = df["temp_avg_c"].fillna(median_temp)

        # Rainfall anomaly: deviation from 3yr rolling mean for same month
        df["monthly_precip_mean"] = df.groupby(df.index.month)["precipitation_mm"].transform(
            lambda x: x.rolling(36, min_periods=6).mean()
        )
        df["rainfall_anomaly"] = df["precipitation_mm"] - df["monthly_precip_mean"].fillna(df["precipitation_mm"])
        df = df.drop(columns=["monthly_precip_mean"])
    else:
        df["precipitation_mm"] = 0.0
        df["temp_avg_c"] = 25.0
        df["rainfall_anomaly"] = 0.0

    # Merge market signals
    if not market.empty:
        df = df.join(market, how="left")

        # NCDEX futures premium vs current spot
        if "ncdex_price" in df.columns:
            df["ncdex_futures_premium"] = df["ncdex_price"] - df[price_col]
            df["ncdex_futures_premium"] = df["ncdex_futures_premium"].fillna(0.0)
            df = df.drop(columns=["ncdex_price"])
        else:
            df["ncdex_futures_premium"] = 0.0

        # Diesel price and MoM change
        if "diesel_price" in df.columns:
            df["diesel_price_inr"] = df["diesel_price"].ffill().fillna(92.0)
            df["diesel_mom_pct"] = df["diesel_price_inr"].pct_change().fillna(0.0)
            df = df.drop(columns=["diesel_price"])
        else:
            df["diesel_price_inr"] = 92.0
            df["diesel_mom_pct"] = 0.0

        if "pmkisan_flag" in df.columns:
            df["pmkisan_flag"] = df["pmkisan_flag"].fillna(0.0)
        else:
            df["pmkisan_flag"] = 0.0

        if "retail_mrp" in df.columns:
            df["retail_mrp_inr"] = df["retail_mrp"].ffill().fillna(df[price_col])
            df = df.drop(columns=["retail_mrp"])
        else:
            df["retail_mrp_inr"] = df[price_col]
    else:
        df["ncdex_futures_premium"] = 0.0
        df["diesel_price_inr"] = 92.0
        df["diesel_mom_pct"] = 0.0
        df["pmkisan_flag"] = 0.0
        df["retail_mrp_inr"] = df[price_col]

    # Drop rows with NaN in core lag features (first 12 months)
    df = df.dropna(subset=["price_lag_12m"])

    # Ensure price_usd exists for Prophet compatibility
    if "price_usd" not in df.columns:
        USD_TO_INR = 83.5
        df["price_usd"] = (df[price_col] * 1000) / (USD_TO_INR * 50)

    available = [c for c in FEATURE_COLUMNS if c in df.columns]
    # Avoid duplicates: price_inr is already in FEATURE_COLUMNS; only add price_usd if missing
    extra = [c for c in ["price_usd", "price_inr"] if c not in available]
    return df[available + extra]
