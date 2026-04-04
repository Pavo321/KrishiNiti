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
import psycopg2.extensions
import redis

from app.features.feature_store import build_feature_matrix, FEATURE_COLUMNS
from app.models.prophet_model import ProphetPriceModel
from app.models.xgboost_model import XGBoostPriceModel
from app.models.lstm_model import LSTMPriceModel
from app.models.ensemble import ensemble_predict

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/2")
FORECAST_DISTRICT = os.environ.get("FORECAST_DISTRICT", "Ludhiana")
FORECAST_STATE = os.environ.get("FORECAST_STATE", "Punjab")

COMMODITIES = ["UREA", "DAP", "MOP", "SSP", "NPK_102626"]
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
                commodity_forecasts = _forecast_commodity(conn, commodity, district=FORECAST_DISTRICT, state=FORECAST_STATE)
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


def _forecast_commodity(conn, commodity: str, district: str = "Ludhiana", state: str = "Punjab") -> list[dict]:
    df = build_feature_matrix(conn, commodity, district=district, state=state)

    # --- Prophet (always runs) ---
    prophet = ProphetPriceModel(commodity=commodity)
    prophet.train(df)

    # --- XGBoost ---
    xgb_model = None
    try:
        xgb_model = XGBoostPriceModel(commodity=commodity)
        xgb_metrics = xgb_model.train(df)
        logger.info(f"XGBoost trained for {commodity}: MAE=₹{xgb_metrics.get('mae_inr', '?')}")
    except Exception as e:
        logger.warning(f"XGBoost training failed for {commodity}: {e}. Skipping.")
        xgb_model = None

    # --- LSTM ---
    lstm_model = None
    try:
        lstm_cols = [c for c in FEATURE_COLUMNS if c in df.columns]
        lstm_model = LSTMPriceModel(commodity=commodity, feature_columns=lstm_cols)
        lstm_metrics = lstm_model.train(df)
        logger.info(f"LSTM trained for {commodity}: val_loss={lstm_metrics.get('best_val_loss', '?')}")
    except Exception as e:
        logger.warning(f"LSTM training failed for {commodity}: {e}. Skipping.")
        lstm_model = None

    # Build features snapshot once (used for all horizons)
    snapshot_base = {}
    for col in ["price_inr", "price_lag_1m", "precipitation_mm", "ncdex_futures_premium",
                "diesel_price_inr", "retail_mrp_inr", "demand_season_score"]:
        if col in df.columns:
            try:
                val = df[col].iloc[-1]
                if val is not None and val == val:   # NaN check: NaN != NaN
                    snapshot_base[col] = round(float(val), 4)
            except Exception:
                pass

    forecasts = []
    for horizon_days in FORECAST_HORIZONS:
        target_date = date.today() + timedelta(days=horizon_days)

        # Collect predictions from available models
        preds = [prophet.predict(horizon_days=horizon_days)]

        if xgb_model is not None:
            try:
                preds.append(xgb_model.predict(df, horizon_days=horizon_days))
            except Exception as e:
                logger.warning(f"XGBoost predict failed for {commodity} {horizon_days}d: {e}")

        if lstm_model is not None:
            try:
                preds.append(lstm_model.predict(df, horizon_days=horizon_days))
            except Exception as e:
                logger.warning(f"LSTM predict failed for {commodity} {horizon_days}d: {e}")

        final_pred = ensemble_predict(preds, commodity=commodity)

        # Resolve predicted_price_inr: prefer ensemble INR, fall back to USD conversion
        predicted_price_inr = final_pred.get("predicted_price_inr")
        if predicted_price_inr is None:
            predicted_price_inr = _usd_to_inr(final_pred.get("predicted_price_usd"))

        forecast_id = str(uuid.uuid4())
        forecast_record = {
            "id": forecast_id,
            "forecast_date": date.today(),
            "target_date": target_date,
            "commodity": commodity,
            "direction": final_pred["direction"],
            "confidence_score": final_pred["confidence_score"],
            "predicted_price_inr": predicted_price_inr,
            "model_name": final_pred["model_name"],
            "model_version": "2.0",
            "features_snapshot": json.dumps({
                **snapshot_base,
                "models_used": final_pred.get("models_used", []),
                "models_agreed": final_pred.get("models_agreed"),
                "weights_used": final_pred.get("weights_used", {}),
            }),
        }

        _save_forecast(conn, forecast_record)
        forecasts.append(forecast_record)
        logger.info(
            f"{commodity} {horizon_days}d: {final_pred['direction']} "
            f"(confidence={final_pred['confidence_score']:.3f}, "
            f"models={final_pred.get('models_used', [])})"
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
    if price_usd is None or price_usd <= 0:
        return None
    # Convert USD/MT to INR/50kg bag
    return round(price_usd * rate * 50 / 1000, 2)
