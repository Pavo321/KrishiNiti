import logging
from datetime import date, datetime, timezone

import psycopg2
import psycopg2.extras
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["accuracy"])


class AccuracySummaryRow(BaseModel):
    commodity: str
    model_name: str
    total_evaluated: int
    correct: int
    accuracy_pct: float
    avg_confidence: float


class EvaluateResponse(BaseModel):
    evaluated: int
    correct: int
    accuracy_pct: float


class TimelineRow(BaseModel):
    week: datetime
    total: int
    correct: int
    accuracy_pct: float


def _get_conn():
    return psycopg2.connect(settings.database_url)


@router.get("/api/v1/accuracy/summary", response_model=list[AccuracySummaryRow])
def get_accuracy_summary():
    sql = """
        SELECT commodity, model_name,
               COUNT(*) AS total_evaluated,
               SUM(CASE WHEN accuracy_flag THEN 1 ELSE 0 END) AS correct,
               ROUND(AVG(confidence_score)::numeric, 3) AS avg_confidence
        FROM forecasts
        WHERE accuracy_flag IS NOT NULL
        GROUP BY commodity, model_name
        ORDER BY commodity, model_name
    """
    conn = None
    try:
        conn = _get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    except Exception as exc:
        logger.error("accuracy_summary query failed: %s", exc)
        raise HTTPException(status_code=500, detail="Database error") from exc
    finally:
        if conn:
            conn.close()

    result = []
    for row in rows:
        total = int(row["total_evaluated"])
        correct = int(row["correct"])
        accuracy_pct = round((correct / total * 100) if total > 0 else 0.0, 2)
        result.append(
            AccuracySummaryRow(
                commodity=row["commodity"],
                model_name=row["model_name"],
                total_evaluated=total,
                correct=correct,
                accuracy_pct=accuracy_pct,
                avg_confidence=float(row["avg_confidence"]),
            )
        )
    return result


@router.post("/api/v1/accuracy/evaluate", response_model=EvaluateResponse)
def evaluate_pending_forecasts():
    """
    Evaluates all forecasts whose target_date has passed and have not yet been
    assessed (accuracy_flag IS NULL). Looks up the actual price from
    commodity_prices (WORLDBANK source), derives actual_direction using the
    same 3 % threshold the forecast used, then marks accuracy_flag and writes
    evaluated_at.
    """
    pending_sql = """
        SELECT id, forecast_date, target_date, commodity,
               direction AS predicted_direction,
               confidence_score, predicted_price_inr, model_name
        FROM forecasts
        WHERE accuracy_flag IS NULL
          AND target_date < CURRENT_DATE
    """
    actual_price_sql = """
        SELECT price_inr
        FROM commodity_prices
        WHERE commodity = %s
          AND price_date BETWEEN %s - INTERVAL '7 days' AND %s + INTERVAL '7 days'
          AND price_inr IS NOT NULL AND price_inr > 0
        ORDER BY
            CASE source WHEN 'AGMARKNET' THEN 1 WHEN 'ENAM' THEN 2
                        WHEN 'FERT_NIC' THEN 3 ELSE 4 END,
            ABS(price_date - %s)
        LIMIT 1
    """
    baseline_price_sql = """
        SELECT price_inr
        FROM commodity_prices
        WHERE commodity = %s
          AND price_date BETWEEN %s - INTERVAL '7 days' AND %s + INTERVAL '7 days'
          AND price_inr IS NOT NULL AND price_inr > 0
        ORDER BY
            CASE source WHEN 'AGMARKNET' THEN 1 WHEN 'ENAM' THEN 2
                        WHEN 'FERT_NIC' THEN 3 ELSE 4 END,
            ABS(price_date - %s)
        LIMIT 1
    """
    update_sql = """
        UPDATE forecasts
        SET actual_price_inr = %s,
            actual_direction = %s,
            accuracy_flag = %s,
            evaluated_at = %s
        WHERE id = %s
    """

    conn = None
    try:
        conn = _get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(pending_sql)
            pending = cur.fetchall()

        evaluated = 0
        correct = 0
        now = datetime.now(tz=timezone.utc)

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            for forecast in pending:
                forecast_id = forecast["id"]
                commodity = forecast["commodity"]
                forecast_date: date = forecast["forecast_date"]
                target_date: date = forecast["target_date"]
                predicted_direction: str = forecast["predicted_direction"]

                # Fetch actual price at target_date (±7 days, prefer local sources)
                cur.execute(actual_price_sql, (commodity, target_date, target_date, target_date))
                actual_row = cur.fetchone()
                if actual_row is None:
                    logger.debug(
                        "No price found for %s near %s — skipping forecast %s",
                        commodity, target_date, forecast_id,
                    )
                    continue

                actual_price = float(actual_row["price_inr"])

                # Fetch baseline price at forecast_date for direction calculation
                cur.execute(baseline_price_sql, (commodity, forecast_date, forecast_date, forecast_date))
                baseline_row = cur.fetchone()
                if baseline_row is None:
                    logger.debug(
                        "No baseline price for %s near %s — skipping forecast %s",
                        commodity, forecast_date, forecast_id,
                    )
                    continue

                baseline_price = float(baseline_row["price_inr"])

                # Derive actual_direction using the same 3 % threshold
                if baseline_price > 0:
                    change_pct = (actual_price - baseline_price) / baseline_price * 100
                else:
                    change_pct = 0.0

                if change_pct > 3.0:
                    actual_direction = "UP"
                elif change_pct < -3.0:
                    actual_direction = "DOWN"
                else:
                    actual_direction = "STABLE"

                is_correct = actual_direction == predicted_direction

                cur.execute(
                    update_sql,
                    (actual_price, actual_direction, is_correct, now, forecast_id),
                )

                evaluated += 1
                if is_correct:
                    correct += 1

        conn.commit()

    except Exception as exc:
        if conn:
            conn.rollback()
        logger.error("evaluate_pending_forecasts failed: %s", exc)
        raise HTTPException(status_code=500, detail="Evaluation failed") from exc
    finally:
        if conn:
            conn.close()

    accuracy_pct = round((correct / evaluated * 100) if evaluated > 0 else 0.0, 2)
    logger.info(
        "Evaluation complete: evaluated=%d correct=%d accuracy_pct=%.2f",
        evaluated,
        correct,
        accuracy_pct,
    )
    return EvaluateResponse(evaluated=evaluated, correct=correct, accuracy_pct=accuracy_pct)


class ModelWeightsRow(BaseModel):
    commodity: str
    model_name: str
    accuracy_pct: float
    weight: float
    sample_size: int


@router.post("/api/v1/accuracy/compute-weights", response_model=list[ModelWeightsRow])
def compute_model_weights():
    """
    Recomputes adaptive ensemble weights per commodity based on last 60 days of
    evaluated forecasts. Results are written to the model_weights table so
    ensemble.py can fetch them at runtime.

    Floor: 0.10 — no model is ever fully ignored.
    """
    query_sql = """
        SELECT commodity, model_name,
               COUNT(*) AS total,
               SUM(accuracy_flag::int) AS correct
        FROM forecasts
        WHERE accuracy_flag IS NOT NULL
          AND evaluated_at >= NOW() - INTERVAL '60 days'
        GROUP BY commodity, model_name
        HAVING COUNT(*) >= 5
        ORDER BY commodity, model_name
    """
    upsert_sql = """
        INSERT INTO model_weights (commodity, model_name, weight, sample_size, computed_at)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (commodity, model_name)
        DO UPDATE SET weight = EXCLUDED.weight,
                      sample_size = EXCLUDED.sample_size,
                      computed_at = EXCLUDED.computed_at
    """

    conn = None
    try:
        conn = _get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query_sql)
            rows = cur.fetchall()
    except Exception as exc:
        logger.error("compute_model_weights query failed: %s", exc)
        raise HTTPException(status_code=500, detail="Database error") from exc

    if not rows:
        if conn:
            conn.close()
        return []

    # Group by commodity, compute normalized weights with 0.10 floor
    from collections import defaultdict
    by_commodity: dict = defaultdict(list)
    for row in rows:
        acc = float(row["correct"]) / float(row["total"]) if row["total"] > 0 else 0.5
        by_commodity[row["commodity"]].append({
            "model_name": row["model_name"],
            "accuracy": acc,
            "total": int(row["total"]),
        })

    result = []
    now = datetime.now(tz=timezone.utc)

    try:
        with conn.cursor() as cur:
            for commodity, models in by_commodity.items():
                total_acc = sum(m["accuracy"] for m in models)
                if total_acc == 0:
                    continue

                raw_weights = {m["model_name"]: max(0.10, m["accuracy"] / total_acc) for m in models}
                total_w = sum(raw_weights.values())
                final_weights = {k: round(v / total_w, 3) for k, v in raw_weights.items()}

                for m in models:
                    model_name = m["model_name"]
                    weight = final_weights[model_name]
                    accuracy_pct = round(m["accuracy"] * 100, 2)

                    cur.execute(upsert_sql, (commodity, model_name, weight, m["total"], now))

                    result.append(ModelWeightsRow(
                        commodity=commodity,
                        model_name=model_name,
                        accuracy_pct=accuracy_pct,
                        weight=weight,
                        sample_size=m["total"],
                    ))

        conn.commit()
    except Exception as exc:
        if conn:
            conn.rollback()
        logger.error("compute_model_weights upsert failed: %s", exc)
        raise HTTPException(status_code=500, detail="Weight upsert failed") from exc
    finally:
        if conn:
            conn.close()

    logger.info("Model weights recomputed: %d entries updated", len(result))
    return result


@router.get("/api/v1/accuracy/timeline", response_model=list[TimelineRow])
def get_accuracy_timeline():
    sql = """
        SELECT DATE_TRUNC('week', evaluated_at) AS week,
               COUNT(*) AS total,
               SUM(CASE WHEN accuracy_flag THEN 1 ELSE 0 END) AS correct
        FROM forecasts
        WHERE accuracy_flag IS NOT NULL
          AND evaluated_at > NOW() - INTERVAL '90 days'
        GROUP BY 1
        ORDER BY 1
    """
    conn = None
    try:
        conn = _get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    except Exception as exc:
        logger.error("accuracy_timeline query failed: %s", exc)
        raise HTTPException(status_code=500, detail="Database error") from exc
    finally:
        if conn:
            conn.close()

    result = []
    for row in rows:
        total = int(row["total"])
        correct = int(row["correct"])
        accuracy_pct = round((correct / total * 100) if total > 0 else 0.0, 2)
        result.append(
            TimelineRow(
                week=row["week"],
                total=total,
                correct=correct,
                accuracy_pct=accuracy_pct,
            )
        )
    return result
