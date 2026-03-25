"""
LSTM-based price forecasting model.
Built after Prophet baseline is validated. Uses PyTorch.
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.preprocessing import MinMaxScaler

logger = logging.getLogger(__name__)

SEQUENCE_LENGTH = 12   # 12 months lookback
HIDDEN_SIZE = 64
NUM_LAYERS = 2
DROPOUT = 0.2


class LSTMPriceNet(nn.Module):
    """PyTorch LSTM network for time-series price prediction."""

    def __init__(self, input_size: int, hidden_size: int = HIDDEN_SIZE, num_layers: int = NUM_LAYERS):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=DROPOUT if num_layers > 1 else 0,
            batch_first=True,
        )
        self.dropout = nn.Dropout(DROPOUT)
        self.fc = nn.Linear(hidden_size, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        lstm_out, _ = self.lstm(x)
        out = self.dropout(lstm_out[:, -1, :])   # last timestep
        return self.fc(out)


class LSTMPriceModel:
    """
    Wraps LSTMPriceNet with training, prediction, and save/load logic.
    """

    MODEL_VERSION = "LSTM_v1"

    def __init__(self, commodity: str, feature_columns: list[str]):
        self.commodity = commodity
        self.feature_columns = feature_columns
        self.scaler = MinMaxScaler(feature_range=(0, 1))
        self.net: LSTMPriceNet | None = None
        self._is_trained = False

    def train(self, df: pd.DataFrame, epochs: int = 100, lr: float = 0.001) -> dict:
        if len(df) < SEQUENCE_LENGTH + 12:
            raise ValueError(
                f"Need at least {SEQUENCE_LENGTH + 12} rows. Got {len(df)}."
            )

        feature_data = df[self.feature_columns].values
        scaled = self.scaler.fit_transform(feature_data)

        X, y = self._create_sequences(scaled)

        X_tensor = torch.FloatTensor(X)
        y_tensor = torch.FloatTensor(y).unsqueeze(1)

        self.net = LSTMPriceNet(input_size=len(self.feature_columns))
        optimizer = torch.optim.Adam(self.net.parameters(), lr=lr)
        criterion = nn.MSELoss()

        # Train/validation split (no data leakage — time-based split)
        split = int(len(X_tensor) * 0.8)
        X_train, X_val = X_tensor[:split], X_tensor[split:]
        y_train, y_val = y_tensor[:split], y_tensor[split:]

        best_val_loss = float("inf")
        for epoch in range(epochs):
            self.net.train()
            optimizer.zero_grad()
            pred = self.net(X_train)
            loss = criterion(pred, y_train)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.net.parameters(), max_norm=1.0)
            optimizer.step()

            if (epoch + 1) % 20 == 0:
                self.net.eval()
                with torch.no_grad():
                    val_pred = self.net(X_val)
                    val_loss = criterion(val_pred, y_val).item()
                if val_loss < best_val_loss:
                    best_val_loss = val_loss
                logger.info(
                    f"Epoch {epoch+1}/{epochs} — train_loss: {loss.item():.4f}, "
                    f"val_loss: {val_loss:.4f}"
                )

        self._is_trained = True
        logger.info(f"LSTM trained for {self.commodity}. Best val_loss: {best_val_loss:.4f}")
        return {"best_val_loss": round(best_val_loss, 4)}

    def predict(self, df: pd.DataFrame, horizon_months: int = 1) -> dict:
        if not self._is_trained or self.net is None:
            raise RuntimeError("Model must be trained before prediction.")

        feature_data = df[self.feature_columns].values
        scaled = self.scaler.transform(feature_data)

        # Use the last SEQUENCE_LENGTH rows as input
        last_sequence = scaled[-SEQUENCE_LENGTH:]
        X = torch.FloatTensor(last_sequence).unsqueeze(0)

        self.net.eval()
        with torch.no_grad():
            pred_scaled = self.net(X).item()

        # Inverse transform — reconstruct full feature vector with predicted price
        dummy = np.zeros((1, len(self.feature_columns)))
        dummy[0, 0] = pred_scaled   # price_usd is first column
        predicted_price = self.scaler.inverse_transform(dummy)[0, 0]

        current_price = df["price_usd"].iloc[-1]
        pct_change = (predicted_price - current_price) / current_price

        if pct_change > 0.03:
            direction = "UP"
        elif pct_change < -0.03:
            direction = "DOWN"
        else:
            direction = "STABLE"

        # LSTM confidence: higher when recent volatility is low
        recent_std = df["price_usd"].tail(6).std()
        recent_mean = df["price_usd"].tail(6).mean()
        cv = recent_std / recent_mean if recent_mean > 0 else 0.5
        confidence = max(0.50, min(0.90, 1.0 - cv))

        return {
            "direction": direction,
            "predicted_price_usd": round(float(predicted_price), 2),
            "confidence_score": round(float(confidence), 3),
            "model_name": self.MODEL_VERSION,
            "pct_change_from_current": round(float(pct_change), 4),
        }

    def save(self, path: Path) -> None:
        if self.net is None:
            raise RuntimeError("No model to save.")
        import joblib
        torch.save(self.net.state_dict(), path / "lstm_weights.pt")
        joblib.dump(self.scaler, path / "scaler.pkl")
        logger.info(f"LSTM model saved to {path}")

    def load(self, path: Path) -> None:
        import joblib
        self.net = LSTMPriceNet(input_size=len(self.feature_columns))
        self.net.load_state_dict(torch.load(path / "lstm_weights.pt", map_location="cpu"))
        self.net.eval()
        self.scaler = joblib.load(path / "scaler.pkl")
        self._is_trained = True
        logger.info(f"LSTM model loaded from {path}")

    def _create_sequences(self, data: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        X, y = [], []
        for i in range(SEQUENCE_LENGTH, len(data)):
            X.append(data[i - SEQUENCE_LENGTH:i])
            y.append(data[i, 0])   # predict price_usd (column 0)
        return np.array(X), np.array(y)
