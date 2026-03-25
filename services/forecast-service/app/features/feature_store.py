"""
Feature store: builds the feature matrix for ML models from DB data.
Single source of truth for all features — computed once, reused by all models.
"""

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd
import psycopg2

logger = logging.getLogger(__name__)

FEATURE_COLUMNS = [
    "price_usd",
    "price_lag_1m",
    "price_lag_3m",
    "price_lag_6m",
    "price_lag_12m",
    "price_rolling_mean_3m",
    "price_rolling_std_3m",
    "price_rolling_mean_6m",
    "month_sin",            # seasonal encoding
    "month_cos",
    "precipitation_mm",
    "temp_avg_c",
]


def build_feature_matrix(
    conn,
    commodity: str,
    district: str = "Ahmedabad",
    end_date: date | None = None,
    lookback_months: int = 36,
) -> pd.DataFrame:
    """
    Builds a feature matrix for a given commodity up to end_date.
    Joins price data with weather data.
    Returns DataFrame indexed by date with FEATURE_COLUMNS.
    """
    if end_date is None:
        end_date = date.today()
    start_date = date(end_date.year - (lookback_months // 12 + 2), 1, 1)

    prices = _load_prices(conn, commodity, start_date, end_date)
    weather = _load_weather(conn, district, start_date, end_date)

    if prices.empty:
        raise ValueError(
            f"No price data found for {commodity} between {start_date} and {end_date}. "
            "Run the data ingestion pipeline first."
        )

    df = _merge_and_engineer(prices, weather)
    logger.info(
        f"Built feature matrix: {commodity}, {len(df)} rows, "
        f"{df.index.min()} to {df.index.max()}"
    )
    return df


def _load_prices(conn, commodity: str, start_date: date, end_date: date) -> pd.DataFrame:
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
    df = df.set_index("price_date").sort_index()

    # Resample to monthly (World Bank data is already monthly, but ensure consistency)
    df = df.resample("MS").mean()
    return df


def _load_weather(conn, district: str, start_date: date, end_date: date) -> pd.DataFrame:
    query = """
        SELECT observation_date,
               AVG(precipitation_mm) AS precipitation_mm,
               AVG(temp_avg_c) AS temp_avg_c
        FROM weather_data
        WHERE district = %s
          AND observation_date BETWEEN %s AND %s
          AND is_forecast = FALSE
          AND temp_avg_c IS NOT NULL
        GROUP BY DATE_TRUNC('month', observation_date)
        ORDER BY DATE_TRUNC('month', observation_date)
    """
    with conn.cursor() as cur:
        cur.execute(query, (district, start_date, end_date))
        rows = cur.fetchall()

    if not rows:
        logger.warning(f"No weather data found for {district}. Proceeding without weather features.")
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=["date", "precipitation_mm", "temp_avg_c"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    return df


def _merge_and_engineer(prices: pd.DataFrame, weather: pd.DataFrame) -> pd.DataFrame:
    df = prices.copy()

    # Lag features (price momentum)
    df["price_lag_1m"] = df["price_usd"].shift(1)
    df["price_lag_3m"] = df["price_usd"].shift(3)
    df["price_lag_6m"] = df["price_usd"].shift(6)
    df["price_lag_12m"] = df["price_usd"].shift(12)

    # Rolling statistics
    df["price_rolling_mean_3m"] = df["price_usd"].rolling(3).mean()
    df["price_rolling_std_3m"] = df["price_usd"].rolling(3).std()
    df["price_rolling_mean_6m"] = df["price_usd"].rolling(6).mean()

    # Seasonal encoding — captures cyclical patterns without ordinal bias
    df["month_sin"] = np.sin(2 * np.pi * df.index.month / 12)
    df["month_cos"] = np.cos(2 * np.pi * df.index.month / 12)

    # Merge weather
    if not weather.empty:
        df = df.join(weather[["precipitation_mm", "temp_avg_c"]], how="left")
        df["precipitation_mm"] = df["precipitation_mm"].fillna(df["precipitation_mm"].median())
        df["temp_avg_c"] = df["temp_avg_c"].fillna(df["temp_avg_c"].median())
    else:
        df["precipitation_mm"] = 0.0
        df["temp_avg_c"] = 25.0  # Gujarat average

    # Drop rows with NaN in lag features (first 12 months)
    df = df.dropna(subset=["price_lag_12m"])

    return df[FEATURE_COLUMNS + ["price_inr"]]
