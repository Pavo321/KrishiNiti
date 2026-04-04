"""
Prophet-based price forecasting model.
Per Google's ML Rule #1: this is the first model — simpler than LSTM, faster to debug.
"""

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd
from prophet import Prophet

logger = logging.getLogger(__name__)


class ProphetPriceModel:
    """
    Wraps Facebook Prophet for commodity price forecasting.
    Uses log-scale transformation so predictions stay positive and
    percentage changes are modelled symmetrically.
    """

    MODEL_VERSION = "PROPHET_v1"

    def __init__(self, commodity: str):
        self.commodity = commodity
        self.model: Prophet | None = None
        self._is_trained = False
        self._last_actual_price_usd: float = 0.0

    def train(self, df: pd.DataFrame) -> dict:
        """
        Trains Prophet on historical price data.
        df must have index as datetime and column 'price_usd'.
        """
        if df.empty or len(df) < 24:
            raise ValueError(
                f"Need at least 24 months of data to train Prophet. Got {len(df)} rows."
            )

        prices = df["price_usd"].astype(float)
        self._last_actual_price_usd = float(prices.iloc[-1])

        # Log-transform: prevents negative predictions, models % changes symmetrically
        train_df = pd.DataFrame({
            "ds": df.index,
            "y": np.log(prices.values),
        })

        self.model = Prophet(
            yearly_seasonality=True,
            weekly_seasonality=False,   # monthly data — no weekly pattern
            daily_seasonality=False,
            changepoint_prior_scale=0.05,   # conservative — avoid over-fitting 2022 spike
            seasonality_prior_scale=10.0,
            interval_width=0.80,
            uncertainty_samples=500,
        )

        # Monsoon seasonality (critical for Indian agriculture input demand)
        self.model.add_seasonality(name="monsoon", period=365.25, fourier_order=5)

        self.model.fit(train_df)
        self._is_trained = True

        # In-sample MAE on last 6 months (back-transformed to USD)
        last_6m = train_df.tail(6)
        fc = self.model.predict(last_6m[["ds"]])
        actual = np.exp(last_6m["y"].values)
        predicted = np.exp(fc["yhat"].values)
        mae = abs(actual - predicted).mean()
        mape = (abs(actual - predicted) / actual).mean()

        logger.info(
            f"Prophet trained for {self.commodity}. "
            f"In-sample MAE (last 6m): ${mae:.2f}, MAPE: {mape*100:.1f}%"
        )

        return {"mae_usd": round(float(mae), 2), "mape": round(float(mape), 4)}

    def predict(self, horizon_days: int = 14) -> dict:
        """
        Predicts price direction and confidence for horizon_days ahead.
        """
        if not self._is_trained or self.model is None:
            raise RuntimeError("Model must be trained before prediction.")

        # Generate enough daily periods to reach today + horizon_days
        last_train_date = pd.Timestamp(self.model.history["ds"].max()).date()
        target_date = date.today() + timedelta(days=horizon_days)
        periods_needed = max(horizon_days, (target_date - last_train_date).days)

        future = self.model.make_future_dataframe(periods=periods_needed, freq="D")
        forecast = self.model.predict(future)

        target_row = forecast.iloc[-1]

        # Back-transform from log-scale
        current_price = self._last_actual_price_usd
        raw_predicted = float(np.exp(target_row["yhat"]))
        pred_low = float(np.exp(target_row["yhat_lower"]))
        pred_high = float(np.exp(target_row["yhat_upper"]))

        # Clamp predicted price to realistic max move per horizon.
        # Fertilizer prices don't move >15% in 30 days — Prophet can extrapolate
        # wildly when training data ends months before today.
        max_move = {7: 0.08, 14: 0.12, 30: 0.18}.get(horizon_days, 0.20)
        lo_bound = current_price * (1 - max_move)
        hi_bound = current_price * (1 + max_move)
        predicted_price = float(np.clip(raw_predicted, lo_bound, hi_bound))

        # Direction vs last actual price
        pct_change = (predicted_price - current_price) / current_price
        if pct_change > 0.03:
            direction = "UP"
        elif pct_change < -0.03:
            direction = "DOWN"
        else:
            direction = "STABLE"

        # Confidence: narrower prediction interval → higher confidence
        interval_width_pct = (pred_high - pred_low) / max(predicted_price, 1e-6)
        confidence = max(0.50, min(0.95, 1.0 - (interval_width_pct * 0.8)))

        return {
            "target_date": target_date.isoformat(),
            "direction": direction,
            "predicted_price_usd": round(predicted_price, 2),
            "prediction_interval_low_usd": round(pred_low, 2),
            "prediction_interval_high_usd": round(pred_high, 2),
            "confidence_score": round(confidence, 3),
            "model_name": self.MODEL_VERSION,
            "pct_change_from_current": round(pct_change, 4),
        }
