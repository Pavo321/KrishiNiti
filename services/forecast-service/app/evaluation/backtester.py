"""
Walk-forward backtester for KrishiNiti forecast models.

Strategy:
  - Training window: all data up to month T
  - Prediction: T+1 (7d), T+2 (14d), T+4 (30d) horizons
  - Advance T by 1 month, repeat
  - Evaluation period: 2019-01 → 2024-12 (avoids 2022 spike contamination
    by reporting it separately)

Runs via: POST /api/v1/jobs/run-backtest
"""

import logging
import os
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
import pandas as pd
import psycopg2

from app.features.feature_store import build_feature_matrix, FEATURE_COLUMNS
from app.models.prophet_model import ProphetPriceModel
from app.models.xgboost_model import XGBoostPriceModel
from app.models.lstm_model import LSTMPriceModel
from app.models.ensemble import ensemble_predict, DEFAULT_WEIGHTS

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]

COMMODITIES = ["UREA", "DAP", "MOP", "SSP", "NPK_102626"]
HORIZONS = [7, 14, 30]                      # days ahead
BACKTEST_START = date(2019, 1, 1)
BACKTEST_END = date(2024, 12, 31)
SPIKE_YEAR = 2022                            # flagged separately in results


def run_backtest(commodities: list[str] | None = None,
                 start: date = BACKTEST_START,
                 end: date = BACKTEST_END) -> dict:
    """
    Runs walk-forward backtest across all commodities and horizons.
    Returns accuracy metrics per model per commodity per horizon.
    """
    targets = commodities or COMMODITIES
    conn = psycopg2.connect(DATABASE_URL)

    all_results = {}
    try:
        for commodity in targets:
            logger.info(f"Backtesting {commodity} from {start} to {end}")
            try:
                result = _backtest_commodity(conn, commodity, start, end)
                all_results[commodity] = result
            except Exception as e:
                logger.error(f"Backtest failed for {commodity}: {e}", exc_info=True)
                all_results[commodity] = {"error": str(e)}
    finally:
        conn.close()

    return all_results


def _backtest_commodity(conn, commodity: str, start: date, end: date) -> dict:
    """Walk-forward backtest for a single commodity."""
    # Load full feature matrix (all available data)
    df_full = build_feature_matrix(conn, commodity)

    if df_full is None or len(df_full) < 36:
        raise ValueError(f"Insufficient data for {commodity}: need ≥ 36 months")

    # Ensure we have a date index for slicing
    if not isinstance(df_full.index, pd.DatetimeIndex):
        if "price_date" in df_full.columns:
            df_full = df_full.set_index("price_date")
        else:
            raise ValueError("Feature matrix has no date index or price_date column")

    df_full.index = pd.to_datetime(df_full.index)
    df_full = df_full.sort_index()

    # --- Walk-forward loop: advance by 1 month ---
    predictions_by_horizon: dict[int, list[dict]] = {h: [] for h in HORIZONS}

    current = start.replace(day=1)
    while current <= end:
        # Training data: all rows up to (and including) current month
        train_cutoff = pd.Timestamp(current)
        df_train = df_full[df_full.index <= train_cutoff]

        if len(df_train) < 24:
            current = _next_month(current)
            continue

        # Train models on this window
        prophet = _try_train_prophet(df_train, commodity)
        xgb = _try_train_xgb(df_train, commodity)
        lstm = _try_train_lstm(df_train, commodity)

        if prophet is None:
            current = _next_month(current)
            continue

        for horizon_days in HORIZONS:
            target_dt = current + timedelta(days=horizon_days)

            # Fetch actual price at target_dt from DB
            actual_price = _get_actual_price(conn, commodity, target_dt)
            if actual_price is None:
                continue   # no data for this future date yet

            # Fetch baseline price at current for direction calculation
            baseline_price = _get_actual_price(conn, commodity, current)
            if baseline_price is None or baseline_price <= 0:
                continue

            # Predict
            preds = []
            try:
                preds.append(prophet.predict(horizon_days=horizon_days))
            except Exception:
                pass

            if xgb:
                try:
                    preds.append(xgb.predict(df_train, horizon_days=horizon_days))
                except Exception:
                    pass

            if lstm:
                try:
                    preds.append(lstm.predict(df_train, horizon_days=horizon_days))
                except Exception:
                    pass

            if not preds:
                continue

            # Ensemble with fixed default weights (no DB in backtesting)
            ensemble_pred = ensemble_predict(preds, commodity=commodity, weights=DEFAULT_WEIGHTS)

            # Actual direction
            change_pct = (actual_price - baseline_price) / baseline_price
            if change_pct > 0.03:
                actual_direction = "UP"
            elif change_pct < -0.03:
                actual_direction = "DOWN"
            else:
                actual_direction = "STABLE"

            is_correct = ensemble_pred["direction"] == actual_direction

            predictions_by_horizon[horizon_days].append({
                "month": current.isoformat(),
                "predicted_direction": ensemble_pred["direction"],
                "actual_direction": actual_direction,
                "confidence": ensemble_pred["confidence_score"],
                "is_correct": is_correct,
                "is_spike_year": current.year == SPIKE_YEAR,
                "models_used": ensemble_pred.get("models_used", []),
            })

        current = _next_month(current)

    # Summarize results
    summary = {}
    for horizon_days, records in predictions_by_horizon.items():
        if not records:
            summary[f"{horizon_days}d"] = {"n": 0}
            continue

        n = len(records)
        n_correct = sum(1 for r in records if r["is_correct"])
        n_spike = [r for r in records if r["is_spike_year"]]
        n_nospike = [r for r in records if not r["is_spike_year"]]

        # Per-direction breakdown
        by_dir: dict = defaultdict(lambda: {"total": 0, "correct": 0})
        for r in records:
            by_dir[r["actual_direction"]]["total"] += 1
            if r["is_correct"]:
                by_dir[r["actual_direction"]]["correct"] += 1

        direction_acc = {
            d: round(v["correct"] / v["total"] * 100, 1) if v["total"] > 0 else 0.0
            for d, v in by_dir.items()
        }

        # 95% Wilson confidence interval on accuracy
        p = n_correct / n if n > 0 else 0
        z = 1.96
        center = (p + z**2 / (2*n)) / (1 + z**2 / n)
        margin = z * np.sqrt(p*(1-p)/n + z**2/(4*n**2)) / (1 + z**2/n)
        ci_lo = round(max(0, (center - margin)) * 100, 1)
        ci_hi = round(min(1, (center + margin)) * 100, 1)

        summary[f"{horizon_days}d"] = {
            "n": n,
            "accuracy_pct": round(p * 100, 2),
            "ci_95": [ci_lo, ci_hi],
            "excluding_spike_year": round(
                sum(1 for r in n_nospike if r["is_correct"]) / len(n_nospike) * 100, 2
            ) if n_nospike else None,
            "spike_year_only": round(
                sum(1 for r in n_spike if r["is_correct"]) / len(n_spike) * 100, 2
            ) if n_spike else None,
            "direction_accuracy": direction_acc,
            "avg_confidence": round(float(np.mean([r["confidence"] for r in records])), 3),
        }

        logger.info(
            f"{commodity} {horizon_days}d backtest: "
            f"{n_correct}/{n} = {p*100:.1f}% [{ci_lo}–{ci_hi}%]"
        )

    return summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _try_train_prophet(df: pd.DataFrame, commodity: str) -> ProphetPriceModel | None:
    try:
        m = ProphetPriceModel(commodity=commodity)
        m.train(df)
        return m
    except Exception as e:
        logger.debug(f"Prophet train failed ({commodity}): {e}")
        return None


def _try_train_xgb(df: pd.DataFrame, commodity: str) -> XGBoostPriceModel | None:
    try:
        m = XGBoostPriceModel(commodity=commodity)
        m.train(df)
        return m
    except Exception as e:
        logger.debug(f"XGBoost train failed ({commodity}): {e}")
        return None


def _try_train_lstm(df: pd.DataFrame, commodity: str) -> LSTMPriceModel | None:
    try:
        cols = [c for c in FEATURE_COLUMNS if c in df.columns]
        m = LSTMPriceModel(commodity=commodity, feature_columns=cols)
        m.train(df, epochs=50)   # fewer epochs in backtesting for speed
        return m
    except Exception as e:
        logger.debug(f"LSTM train failed ({commodity}): {e}")
        return None


def _get_actual_price(conn, commodity: str, target_date: date) -> float | None:
    """
    Fetches best available price for commodity on or within 7 days of target_date.
    Preference: Agmarknet / eNAM / FERT_NIC > WORLDBANK.
    """
    sql = """
        SELECT price_inr
        FROM commodity_prices
        WHERE commodity = %s
          AND price_date BETWEEN %s AND %s
          AND price_inr IS NOT NULL
          AND price_inr > 0
        ORDER BY
            CASE source
                WHEN 'AGMARKNET' THEN 1
                WHEN 'ENAM'      THEN 2
                WHEN 'FERT_NIC'  THEN 3
                ELSE 4
            END,
            price_date DESC
        LIMIT 1
    """
    window_start = target_date - timedelta(days=7)
    window_end = target_date + timedelta(days=7)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (commodity, window_start, window_end))
            row = cur.fetchone()
        return float(row[0]) if row else None
    except Exception as e:
        logger.debug(f"_get_actual_price failed ({commodity} {target_date}): {e}")
        return None


def _next_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)
