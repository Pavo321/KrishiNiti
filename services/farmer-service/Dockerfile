FROM python:3.11-slim AS base
WORKDIR /app

RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

FROM base AS deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM deps AS runtime
COPY app/ ./app/
RUN chown -R appuser:appgroup /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
