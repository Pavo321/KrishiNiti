"""
Weighted ensemble: combines Prophet + LSTM predictions.
Weights are derived from backtested accuracy per commodity.
"""

import logging

logger = logging.getLogger(__name__)

# Initial weights (updated by backtesting as data accumulates)
# Prophet is weighted higher initially — it's more interpretable and validated first
DEFAULT_WEIGHTS = {
    "PROPHET_v1": 0.65,
    "LSTM_v1": 0.35,
}

DIRECTION_TO_SCORE = {"UP": 1, "STABLE": 0, "DOWN": -1}
SCORE_TO_DIRECTION = {
    score: direction for direction, score in DIRECTION_TO_SCORE.items()
}


def ensemble_predict(predictions: list[dict], weights: dict | None = None) -> dict:
    """
    Combines multiple model predictions into a single ensemble forecast.
    predictions: list of dicts from ProphetPriceModel.predict() or LSTMPriceModel.predict()
    weights: optional override of DEFAULT_WEIGHTS
    Returns: single prediction dict with ensemble confidence score.
    """
    if not predictions:
        raise ValueError("No predictions to ensemble.")

    if len(predictions) == 1:
        result = predictions[0].copy()
        result["model_name"] = "ENSEMBLE_v1"
        return result

    w = weights or DEFAULT_WEIGHTS

    # Weighted average of price predictions
    total_weight = 0.0
    weighted_price = 0.0
    weighted_confidence = 0.0
    direction_scores = []

    for pred in predictions:
        model_name = pred.get("model_name", "UNKNOWN")
        weight = w.get(model_name, 0.5)

        if pred.get("predicted_price_usd"):
            weighted_price += pred["predicted_price_usd"] * weight
            total_weight += weight

        weighted_confidence += pred["confidence_score"] * weight
        direction_score = DIRECTION_TO_SCORE.get(pred["direction"], 0)
        direction_scores.append((direction_score, weight))

    if total_weight == 0:
        total_weight = 1.0

    # Ensemble direction: weighted vote
    total_w = sum(w for _, w in direction_scores)
    weighted_dir_score = sum(score * w for score, w in direction_scores) / total_w
    if weighted_dir_score > 0.3:
        direction = "UP"
    elif weighted_dir_score < -0.3:
        direction = "DOWN"
    else:
        direction = "STABLE"

    # Ensemble confidence: weighted average, reduced if models disagree
    all_directions = [d for d, _ in [(SCORE_TO_DIRECTION.get(round(s), "STABLE"), w)
                                       for s, w in direction_scores]]
    agreement = len(set(all_directions)) == 1   # all models agree
    base_confidence = weighted_confidence / total_weight
    ensemble_confidence = base_confidence if agreement else base_confidence * 0.85

    result = {
        "direction": direction,
        "predicted_price_usd": round(weighted_price / total_weight, 2) if weighted_price else None,
        "confidence_score": round(min(0.95, ensemble_confidence), 3),
        "model_name": "ENSEMBLE_v1",
        "model_version": "1.0",
        "models_used": [p.get("model_name") for p in predictions],
        "models_agreed": agreement,
    }

    logger.info(
        f"Ensemble: direction={direction}, confidence={result['confidence_score']:.3f}, "
        f"models_agreed={agreement}"
    )
    return result
