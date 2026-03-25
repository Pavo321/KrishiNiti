"""
Prophet-based price forecasting model.
Per Google's ML Rule #1: this is the first model — simpler than LSTM, faster to debug.
"""

import logging
from datetime import date, timedelta

import pandas as pd
from prophet import Prophet

logger = logging.getLogger(__name__)


class ProphetPriceModel:
    """
    Wraps Facebook Prophet for commodity price forecasting.
    Handles seasonality, trend changepoints, and produces prediction intervals.
    """

    MODEL_VERSION = "PROPHET_v1"

    def __init__(self, commodity: str):
        self.commodity = commodity
        self.model: Prophet | None = None
        self._is_trained = False

    def train(self, df: pd.DataFrame) -> dict:
        """
        Trains Prophet on historical price data.
        df must have index as datetime and column 'price_usd'.
        Returns training metrics from cross-validation.
        """
        if df.empty or len(df) < 24:
            raise ValueError(
                f"Need at least 24 months of data to train Prophet. Got {len(df)} rows."
            )

        # Prophet requires columns 'ds' (date) and 'y' (value)
        train_df = pd.DataFrame({
            "ds": df.index,
            "y": df["price_usd"].values,
        })

        self.model = Prophet(
            yearly_seasonality=True,
            weekly_seasonality=False,   # monthly data — no weekly pattern
            daily_seasonality=False,
            changepoint_prior_scale=0.05,   # lower = less flexible trend
            seasonality_prior_scale=10.0,
            interval_width=0.80,            # 80% prediction interval
            uncertainty_samples=500,
        )

        # Add monsoon seasonality (critical for Indian agriculture)
        self.model.add_seasonality(
            name="monsoon",
            period=365.25,
            fourier_order=5,
        )

        self.model.fit(train_df)
        self._is_trained = True

        # Simple in-sample metric: MAE on last 6 months
        last_6m = train_df.tail(6)
        forecast = self.model.predict(last_6m[["ds"]])
        mae = abs(last_6m["y"].values - forecast["yhat"].values).mean()
        mape = (abs(last_6m["y"].values - forecast["yhat"].values) / last_6m["y"].values).mean()

        logger.info(
            f"Prophet trained for {self.commodity}. "
            f"In-sample MAE (last 6m): ${mae:.2f}, MAPE: {mape*100:.1f}%"
        )

        return {"mae_usd": round(float(mae), 2), "mape": round(float(mape), 4)}

    def predict(self, horizon_days: int = 14) -> dict:
        """
        Predicts price direction and confidence for horizon_days ahead.
        Returns a single prediction with confidence score.
        """
        if not self._is_trained or self.model is None:
            raise RuntimeError("Model must be trained before prediction.")

        # Create future dataframe
        future = self.model.make_future_dataframe(
            periods=horizon_days,
            freq="D",
        )
        forecast = self.model.predict(future)

        # Get the prediction at horizon_days
        target_row = forecast.iloc[-1]
        target_date = target_row["ds"].date()

        # Current price (last known)
        current_row = forecast.iloc[-(horizon_days + 1)]
        current_price = float(current_row["yhat"])
        predicted_price = float(target_row["yhat"])
        pred_low = float(target_row["yhat_lower"])
        pred_high = float(target_row["yhat_upper"])

        # Direction
        pct_change = (predicted_price - current_price) / current_price
        if pct_change > 0.03:
            direction = "UP"
        elif pct_change < -0.03:
            direction = "DOWN"
        else:
            direction = "STABLE"

        # Confidence score: based on prediction interval width relative to price
        interval_width_pct = (pred_high - pred_low) / predicted_price
        # Narrower interval → higher confidence. Scale to 0.5–0.95 range.
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
