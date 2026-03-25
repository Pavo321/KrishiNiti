"""
Daily forecast job — runs at 3:00 AM IST.
Trains/loads models, runs predictions for all commodities, writes to DB.
Publishes Redis event to trigger alert-service.
"""

import json
import logging
import os
import uuid
from datetime import date, timedelta

import psycopg2
import psycopg2.extras
import redis

from app.features.feature_store import build_feature_matrix, FEATURE_COLUMNS
from app.models.prophet_model import ProphetPriceModel
from app.models.ensemble import ensemble_predict

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/2")

COMMODITIES = ["UREA", "DAP", "MOP"]
FORECAST_HORIZONS = [7, 14, 30]   # days ahead


async def run_daily_forecast() -> dict:
    logger.info("Starting daily forecast job")
    results = {}

    conn = psycopg2.connect(DATABASE_URL)
    r = redis.from_url(REDIS_URL, decode_responses=True)

    try:
        forecasts_created = []

        for commodity in COMMODITIES:
            try:
                commodity_forecasts = _forecast_commodity(conn, commodity)
                forecasts_created.extend(commodity_forecasts)
                results[commodity] = len(commodity_forecasts)
            except Exception as e:
                logger.error(f"Forecast failed for {commodity}: {e}", exc_info=True)
                results[commodity] = "ERROR"

        if forecasts_created:
            # Publish event for alert-service to consume
            r.publish(
                "forecasts:ready",
                json.dumps({
                    "forecast_date": date.today().isoformat(),
                    "forecast_ids": [str(f["id"]) for f in forecasts_created],
                    "commodities": COMMODITIES,
                }),
            )
            logger.info(f"Published forecasts:ready event for {len(forecasts_created)} forecasts")

    finally:
        conn.close()
        r.close()

    logger.info(f"Daily forecast job complete: {results}")
    return results


def _forecast_commodity(conn, commodity: str) -> list[dict]:
    df = build_feature_matrix(conn, commodity)

    # Train Prophet (fast, always retrain on latest data)
    prophet = ProphetPriceModel(commodity=commodity)
    prophet.train(df)

    forecasts = []
    for horizon_days in FORECAST_HORIZONS:
        target_date = date.today() + timedelta(days=horizon_days)

        prophet_pred = prophet.predict(horizon_days=horizon_days)
        final_pred = ensemble_predict([prophet_pred])   # LSTM added in v2

        forecast_id = uuid.uuid4()
        forecast_record = {
            "id": forecast_id,
            "forecast_date": date.today(),
            "target_date": target_date,
            "commodity": commodity,
            "direction": final_pred["direction"],
            "confidence_score": final_pred["confidence_score"],
            "predicted_price_inr": _usd_to_inr(final_pred.get("predicted_price_usd")),
            "model_name": final_pred["model_name"],
            "model_version": "1.0",
            "features_snapshot": json.dumps({
                "latest_price_usd": float(df["price_usd"].iloc[-1]),
                "price_lag_1m": float(df["price_lag_1m"].iloc[-1]),
                "precipitation_mm": float(df["precipitation_mm"].iloc[-1]),
            }),
        }

        _save_forecast(conn, forecast_record)
        forecasts.append(forecast_record)
        logger.info(
            f"{commodity} {horizon_days}d: {final_pred['direction']} "
            f"(confidence: {final_pred['confidence_score']:.3f})"
        )

    return forecasts


def _save_forecast(conn, record: dict) -> None:
    sql = """
        INSERT INTO forecasts (
            id, forecast_date, target_date, commodity,
            direction, confidence_score, predicted_price_inr,
            model_name, model_version, features_snapshot
        ) VALUES (
            %(id)s, %(forecast_date)s, %(target_date)s, %(commodity)s,
            %(direction)s, %(confidence_score)s, %(predicted_price_inr)s,
            %(model_name)s, %(model_version)s, %(features_snapshot)s
        )
        ON CONFLICT DO NOTHING
    """
    with conn.cursor() as cur:
        cur.execute(sql, record)
    conn.commit()


def _usd_to_inr(price_usd: float | None, rate: float = 83.5) -> float | None:
    if price_usd is None:
        return None
    # Convert USD/MT to INR/50kg bag
    return round(price_usd * rate * 50 / 1000, 2)
