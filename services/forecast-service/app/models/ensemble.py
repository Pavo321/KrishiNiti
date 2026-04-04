"""
Weighted ensemble: combines Prophet + XGBoost + LSTM predictions.
Weights are fetched from DB (adaptive — updated nightly by analytics-service).
Falls back to default weights if DB unavailable.
"""

import logging
import os

import psycopg2

logger = logging.getLogger(__name__)

# Initial weights — updated by analytics-service once accuracy data accumulates
DEFAULT_WEIGHTS = {
    "PROPHET_v1":  0.50,
    "XGBOOST_v1":  0.35,
    "LSTM_v1":     0.15,
}

DIRECTION_TO_SCORE = {"UP": 1, "STABLE": 0, "DOWN": -1}
SCORE_TO_DIRECTION = {1: "UP", 0: "STABLE", -1: "DOWN"}


def get_adaptive_weights(commodity: str) -> dict:
    """
    Fetches model weights based on recent accuracy from the forecasts table.
    Falls back to DEFAULT_WEIGHTS if insufficient data.
    """
    try:
        db_url = os.environ.get("DATABASE_URL", "")
        if not db_url:
            return DEFAULT_WEIGHTS

        conn = psycopg2.connect(db_url)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT model_name,
                       COUNT(*) AS total,
                       SUM(accuracy_flag::int) AS correct
                FROM forecasts
                WHERE commodity = %s
                  AND accuracy_flag IS NOT NULL
                  AND evaluated_at >= NOW() - INTERVAL '60 days'
                GROUP BY model_name
                HAVING COUNT(*) >= 5
            """, (commodity,))
            rows = cur.fetchall()
        conn.close()

        if not rows:
            return DEFAULT_WEIGHTS

        accuracies = {}
        for model_name, total, correct in rows:
            accuracies[model_name] = correct / total if total > 0 else 0.5

        # Normalize to weights, floor at 0.10
        total_acc = sum(accuracies.values())
        if total_acc == 0:
            return DEFAULT_WEIGHTS

        weights = {}
        for model_name in DEFAULT_WEIGHTS:
            raw_acc = accuracies.get(model_name, 0.5)
            weights[model_name] = max(0.10, raw_acc / total_acc)

        # Re-normalize so weights sum to 1.0
        total_w = sum(weights.values())
        weights = {k: round(v / total_w, 3) for k, v in weights.items()}

        logger.info(f"Adaptive weights for {commodity}: {weights}")
        return weights

    except Exception as e:
        logger.warning(f"Could not fetch adaptive weights for {commodity}: {e}. Using defaults.")
        return DEFAULT_WEIGHTS


def ensemble_predict(predictions: list[dict], commodity: str = "UNKNOWN",
                     weights: dict | None = None) -> dict:
    """
    Combines multiple model predictions into a single ensemble forecast.

    predictions: list of dicts from ProphetPriceModel/XGBoostPriceModel/LSTMPriceModel
    commodity: used to fetch adaptive weights from DB
    weights: explicit override (used in backtesting)

    Returns: single prediction dict with ensemble metadata.
    """
    if not predictions:
        raise ValueError("No predictions to ensemble.")

    if len(predictions) == 1:
        result = predictions[0].copy()
        result["model_name"] = "ENSEMBLE_v1"
        return result

    # Use adaptive weights unless explicitly overridden
    w = weights or get_adaptive_weights(commodity)

    weighted_price_usd = 0.0
    weighted_price_inr = 0.0
    weighted_confidence = 0.0
    total_weight_usd = 0.0
    total_weight_inr = 0.0
    total_weight_conf = 0.0
    direction_votes = []

    for pred in predictions:
        model_name = pred.get("model_name", "UNKNOWN")
        weight = w.get(model_name, 1.0 / len(predictions))

        if pred.get("predicted_price_usd"):
            weighted_price_usd += float(pred["predicted_price_usd"]) * weight
            total_weight_usd += weight

        if pred.get("predicted_price_inr"):
            weighted_price_inr += float(pred["predicted_price_inr"]) * weight
            total_weight_inr += weight

        weighted_confidence += pred["confidence_score"] * weight
        total_weight_conf += weight

        direction_score = DIRECTION_TO_SCORE.get(pred["direction"], 0)
        direction_votes.append((direction_score, weight))

    # Ensemble direction: weighted vote
    total_vote_w = sum(w for _, w in direction_votes)
    weighted_dir_score = sum(s * w for s, w in direction_votes) / max(total_vote_w, 1e-6)

    if weighted_dir_score > 0.25:
        direction = "UP"
    elif weighted_dir_score < -0.25:
        direction = "DOWN"
    else:
        direction = "STABLE"

    # Check agreement across models
    all_directions = {pred["direction"] for pred in predictions}
    models_agreed = len(all_directions) == 1

    # Confidence: penalize disagreement
    base_confidence = weighted_confidence / max(total_weight_conf, 1e-6)
    ensemble_confidence = base_confidence if models_agreed else base_confidence * 0.85

    final_price_inr = round(weighted_price_inr / total_weight_inr, 2) if total_weight_inr > 0 else None
    final_price_usd = round(weighted_price_usd / total_weight_usd, 2) if total_weight_usd > 0 else None

    # If we have a predicted price, derive direction from it — price is ground truth.
    # Weighted vote direction is only a fallback when no price is available.
    current_price = None
    for pred in predictions:
        if pred.get("predicted_price_inr") and pred.get("pct_change_from_current") is not None:
            # Back-calculate current price from XGBoost's pct_change
            pct = float(pred["pct_change_from_current"])
            p = float(pred["predicted_price_inr"])
            if abs(pct + 1) > 1e-6:
                current_price = p / (1 + pct)
            break

    if final_price_inr is not None and current_price is not None and current_price > 0:
        pct_change = (final_price_inr - current_price) / current_price
        if pct_change > 0.02:
            direction = "UP"
        elif pct_change < -0.02:
            direction = "DOWN"
        else:
            direction = "STABLE"

    result = {
        "direction": direction,
        "predicted_price_usd": final_price_usd,
        "predicted_price_inr": final_price_inr,
        "confidence_score": round(min(0.95, ensemble_confidence), 3),
        "model_name": "ENSEMBLE_v1",
        "model_version": "2.0",
        "models_used": [p.get("model_name") for p in predictions],
        "models_agreed": models_agreed,
        "weights_used": {p.get("model_name"): w.get(p.get("model_name", ""), 0) for p in predictions},
    }

    logger.info(
        f"Ensemble [{commodity}]: direction={direction}, confidence={result['confidence_score']:.3f}, "
        f"agreed={models_agreed}, weights={result['weights_used']}"
    )
    return result
