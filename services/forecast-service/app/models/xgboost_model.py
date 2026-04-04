"""
XGBoost price forecasting model.
Captures nonlinear feature interactions that Prophet cannot model:
  - NCDEX futures premium × diesel price interaction
  - PM-KISAN cash → demand → price lag
  - Rainfall anomaly × crop season interaction

Trained on the full 21-feature matrix from feature_store v2.
"""

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

try:
    import xgboost as xgb
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False
    logger.warning("xgboost not installed. XGBoostPriceModel will be unavailable.")


class XGBoostPriceModel:

    MODEL_VERSION = "XGBOOST_v1"

    # Features used for training — excludes price_usd (Prophet uses that)
    # Uses price_inr (local mandi prices) as the primary signal
    TRAIN_FEATURES = [
        "price_lag_1m", "price_lag_3m", "price_lag_6m", "price_lag_12m",
        "price_rolling_mean_3m", "price_rolling_std_3m", "price_rolling_mean_6m",
        "month_sin", "month_cos",
        "precipitation_mm", "temp_avg_c", "rainfall_anomaly",
        "ncdex_futures_premium", "diesel_price_inr", "diesel_mom_pct",
        "pmkisan_flag", "demand_season_score", "retail_mrp_inr",
    ]

    def __init__(self, commodity: str):
        self.commodity = commodity
        self.model = None
        self._is_trained = False
        self._last_price_inr = 0.0

    def train(self, df: pd.DataFrame) -> dict:
        if not XGB_AVAILABLE:
            raise RuntimeError("xgboost package not installed.")

        if len(df) < 24:
            raise ValueError(f"Need at least 24 months of data. Got {len(df)}.")

        available_features = [f for f in self.TRAIN_FEATURES if f in df.columns]
        if len(available_features) < 6:
            raise ValueError(f"Too few features available: {available_features}")

        self._last_price_inr = float(df["price_inr"].iloc[-1])
        self._available_features = available_features

        X = df[available_features].values
        y = df["price_inr"].shift(-1).dropna().values  # predict next month's price
        X = X[:len(y)]  # align

        # Time-based train/val split (80/20, no leakage)
        split = int(len(X) * 0.8)
        X_train, X_val = X[:split], X[split:]
        y_train, y_val = y[:split], y[split:]

        self.model = xgb.XGBRegressor(
            n_estimators=300,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=3,
            reg_alpha=0.1,      # L1 regularization
            reg_lambda=1.0,     # L2 regularization
            random_state=42,
            n_jobs=-1,
            early_stopping_rounds=30,
            eval_metric="mae",
        )

        self.model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            verbose=False,
        )

        val_pred = self.model.predict(X_val)
        mae = float(np.mean(np.abs(val_pred - y_val)))
        mape = float(np.mean(np.abs((val_pred - y_val) / (y_val + 1e-6))))

        self._is_trained = True
        logger.info(
            f"XGBoost trained for {self.commodity}. "
            f"Val MAE: ₹{mae:.1f}, MAPE: {mape*100:.1f}% "
            f"Features used: {len(available_features)}"
        )
        return {"mae_inr": round(mae, 2), "mape": round(mape, 4)}

    def predict(self, df: pd.DataFrame, horizon_days: int = 14) -> dict:
        if not self._is_trained or self.model is None:
            raise RuntimeError("Model must be trained before prediction.")

        target_date = date.today() + timedelta(days=horizon_days)
        available_features = [f for f in self._available_features if f in df.columns]

        last_row = df[available_features].iloc[-1:].values
        predicted_price = float(self.model.predict(last_row)[0])

        current_price = self._last_price_inr

        # Clamp to realistic move per horizon
        max_move = {7: 0.08, 14: 0.12, 30: 0.18}.get(horizon_days, 0.20)
        lo = current_price * (1 - max_move)
        hi = current_price * (1 + max_move)
        predicted_price = float(np.clip(predicted_price, lo, hi))

        pct_change = (predicted_price - current_price) / max(current_price, 1e-6)

        if pct_change > 0.03:
            direction = "UP"
        elif pct_change < -0.03:
            direction = "DOWN"
        else:
            direction = "STABLE"

        # Confidence from feature importances — higher when top features available
        n_features_used = len(available_features)
        n_features_max = len(self.TRAIN_FEATURES)
        feature_coverage = n_features_used / n_features_max

        # Lower confidence for volatile commodities
        recent_cv = df["price_rolling_std_3m"].iloc[-1] / max(df["price_rolling_mean_3m"].iloc[-1], 1)
        volatility_penalty = min(0.15, float(recent_cv))

        confidence = max(0.50, min(0.92, 0.75 * feature_coverage - volatility_penalty))

        # Boost confidence if NCDEX futures agree with direction
        if "ncdex_futures_premium" in df.columns:
            futures_premium = float(df["ncdex_futures_premium"].iloc[-1])
            futures_bullish = futures_premium > 0
            if (direction == "UP" and futures_bullish) or (direction == "DOWN" and not futures_bullish):
                confidence = min(0.92, confidence + 0.05)

        return {
            "target_date": target_date.isoformat(),
            "direction": direction,
            "predicted_price_usd": None,  # XGBoost works in INR
            "predicted_price_inr": round(predicted_price, 2),
            "confidence_score": round(confidence, 3),
            "model_name": self.MODEL_VERSION,
            "pct_change_from_current": round(pct_change, 4),
        }

    def feature_importance(self) -> dict:
        if not self._is_trained or self.model is None:
            return {}
        scores = self.model.feature_importances_
        return dict(sorted(
            zip(self._available_features, scores.tolist()),
            key=lambda x: x[1], reverse=True
        ))
