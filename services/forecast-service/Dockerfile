FROM python:3.11-slim AS base
WORKDIR /app

RUN addgroup --system appgroup && adduser --system --ingroup appgroup --home /home/appuser appuser
RUN mkdir -p /home/appuser && chown appuser:appgroup /home/appuser

FROM base AS deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Fix prophet's cmdstan path: the bundled cmdstan-2.33.1 is missing its makefile.
# Prophet only needs stanc (pre-built) + the compiled prophet_model.bin.
# We create a minimal valid directory so cmdstanpy path validation passes.
FROM deps AS runtime
COPY fix_prophet.py .
RUN python fix_prophet.py

COPY app/ ./app/
RUN chown -R appuser:appgroup /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
