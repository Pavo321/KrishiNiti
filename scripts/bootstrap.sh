#!/usr/bin/env bash
# =============================================================================
# KrishiNiti — Full Bootstrap Script
# =============================================================================
# Brings up the entire stack from a clean slate, backfills historical data,
# trains models, and prints a summary of what was seeded.
#
# Usage:
#   ./scripts/bootstrap.sh
#
# Prerequisites:
#   - Docker + Docker Compose v2
#   - curl, jq
# =============================================================================

set -euo pipefail

# ── Colour palette ────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

# ── Helpers ───────────────────────────────────────────────────────────────────
log_step()  { echo -e "\n${BLUE}${BOLD}[STEP]${RESET} $*"; }
log_info()  { echo -e "${CYAN}  --> $*${RESET}"; }
log_ok()    { echo -e "${GREEN}  [OK]${RESET} $*"; }
log_warn()  { echo -e "${YELLOW}  [WARN]${RESET} $*"; }
log_error() { echo -e "${RED}  [ERROR]${RESET} $*" >&2; }

die() {
  log_error "$*"
  exit 1
}

require_cmd() {
  command -v "$1" &>/dev/null || die "'$1' is required but not installed."
}

# ── Constants ─────────────────────────────────────────────────────────────────
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="docker compose"

# Service base URLs (mapped via docker-compose ports)
INGEST_URL="http://localhost:8001"
WEATHER_URL="http://localhost:8002"
FORECAST_URL="http://localhost:8003"
ALERT_URL="http://localhost:8004"
FARMER_URL="http://localhost:8005"
ANALYTICS_URL="http://localhost:8006"

# Timeouts (seconds)
POSTGRES_TIMEOUT=60
SERVICE_HEALTH_TIMEOUT=120
INGEST_TIMEOUT=600    # 10 minutes — full Agmarknet + World Bank backfill
FORECAST_TIMEOUT=300  # 5 minutes — model training can be slow

# ── Pre-flight checks ─────────────────────────────────────────────────────────
require_cmd docker
require_cmd curl
require_cmd jq

# Verify Docker Compose v2
$COMPOSE version &>/dev/null || die "Docker Compose v2 not found. Run: docker compose version"

# ── Step 1: .env setup ────────────────────────────────────────────────────────
log_step "1/12  Checking .env configuration"

cd "$REPO_ROOT"

if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example .env
    log_warn ".env not found — copied from .env.example"
    log_warn "IMPORTANT: Edit .env and set real passwords before proceeding in production."
    log_warn "Continuing with example values (development only)..."
    echo ""
  else
    die ".env and .env.example both missing. Cannot continue."
  fi
else
  log_ok ".env found"
fi

# Warn if passwords are still the example placeholders
if grep -q "change_me" .env; then
  log_warn "Detected placeholder passwords in .env — this is fine for local dev, not for staging/prod."
fi

# ── Step 2: Clean slate ───────────────────────────────────────────────────────
log_step "2/12  Tearing down existing stack (volumes included)"

echo ""
echo -e "${YELLOW}${BOLD}WARNING:${RESET} ${YELLOW}This will destroy all existing containers AND volumes${RESET}"
echo -e "${YELLOW}(postgres data, redis data, model artifacts).${RESET}"
echo ""
read -r -p "  Type 'yes' to continue, anything else to abort: " CONFIRM
if [[ "$CONFIRM" != "yes" ]]; then
  echo "Aborted."
  exit 0
fi

$COMPOSE down -v --remove-orphans 2>/dev/null || true
log_ok "Stack torn down"

# ── Step 3: Start infrastructure only ────────────────────────────────────────
log_step "3/12  Starting infrastructure (postgres + redis)"

$COMPOSE up -d postgres redis
log_info "Waiting for postgres to be healthy..."

# ── Step 4: Wait for postgres ─────────────────────────────────────────────────
log_step "4/12  Polling postgres health"

deadline=$(( $(date +%s) + POSTGRES_TIMEOUT ))
while true; do
  if $COMPOSE exec -T postgres pg_isready -U krishiniti_app -d krishiniti -q 2>/dev/null; then
    log_ok "Postgres is ready"
    break
  fi
  if (( $(date +%s) > deadline )); then
    die "Postgres did not become ready within ${POSTGRES_TIMEOUT}s. Check: docker compose logs postgres"
  fi
  echo -n "."
  sleep 2
done

# ── Step 5: Build and start all services ──────────────────────────────────────
log_step "5/12  Building and starting all services"
log_info "This may take several minutes on first run (Docker image builds)..."

$COMPOSE up -d --build
log_ok "All services started"

# ── Step 6: Wait for all service /health endpoints ───────────────────────────
log_step "6/12  Waiting for all services to pass health checks"

declare -A SERVICES=(
  ["price-ingestion"]="$INGEST_URL"
  ["weather"]="$WEATHER_URL"
  ["forecast"]="$FORECAST_URL"
  ["alert"]="$ALERT_URL"
  ["farmer"]="$FARMER_URL"
  ["analytics"]="$ANALYTICS_URL"
)

wait_for_health() {
  local name="$1"
  local base_url="$2"
  local deadline=$(( $(date +%s) + SERVICE_HEALTH_TIMEOUT ))
  local url="${base_url}/health"

  log_info "Waiting for ${name} at ${url} ..."
  while true; do
    http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "$url" 2>/dev/null || echo "000")
    if [[ "$http_code" == "200" ]]; then
      log_ok "${name} is healthy"
      return 0
    fi
    if (( $(date +%s) > deadline )); then
      die "${name} did not become healthy within ${SERVICE_HEALTH_TIMEOUT}s (last HTTP: ${http_code}). Check: docker compose logs ${name}-service"
    fi
    echo -n "."
    sleep 3
  done
}

for name in "${!SERVICES[@]}"; do
  wait_for_health "$name" "${SERVICES[$name]}"
done

echo ""
log_ok "All services are healthy"

# ── Step 7: Trigger Agmarknet price backfill ──────────────────────────────────
log_step "7/12  Triggering Agmarknet + World Bank price ingestion backfill"
log_info "POST ${INGEST_URL}/api/v1/jobs/run-ingest"

INGEST_RESPONSE=$(curl -s -w "\n%{http_code}" \
  -X POST "${INGEST_URL}/api/v1/jobs/run-ingest" \
  -H "Content-Type: application/json" \
  --max-time 30 2>/dev/null)

INGEST_HTTP=$(echo "$INGEST_RESPONSE" | tail -n1)
INGEST_BODY=$(echo "$INGEST_RESPONSE" | head -n-1)

if [[ "$INGEST_HTTP" != "200" ]]; then
  die "Ingest trigger failed with HTTP ${INGEST_HTTP}. Body: ${INGEST_BODY}"
fi
log_ok "Ingest job triggered — running in background"
log_info "Response: $(echo "$INGEST_BODY" | jq -c '.' 2>/dev/null || echo "$INGEST_BODY")"

# ── Step 8: Poll until ingest completes ───────────────────────────────────────
log_step "8/12  Polling ingest completion (timeout: ${INGEST_TIMEOUT}s)"
log_info "Ingest backfills historical commodity prices — this takes several minutes."

# The ingest endpoint is synchronous (awaits run_daily_ingest), so HTTP 200
# means it completed already. We check the price record count via a DB query
# to confirm data landed. Polling a separate status endpoint would be ideal,
# but the service does not currently expose one — so we verify via row count.

deadline=$(( $(date +%s) + INGEST_TIMEOUT ))
PRICE_RECORDS=0

while true; do
  # Query the DB container directly for commodity_prices count
  COUNT_RESULT=$($COMPOSE exec -T postgres \
    psql -U krishiniti_app -d krishiniti -t -A \
    -c "SELECT COUNT(*) FROM commodity_prices;" 2>/dev/null || echo "0")

  PRICE_RECORDS=$(echo "$COUNT_RESULT" | tr -d '[:space:]')

  if [[ "$PRICE_RECORDS" =~ ^[0-9]+$ ]] && (( PRICE_RECORDS > 0 )); then
    log_ok "Ingest complete — ${PRICE_RECORDS} price records in DB"
    break
  fi

  if (( $(date +%s) > deadline )); then
    log_warn "Ingest timeout reached. commodity_prices count = ${PRICE_RECORDS}. Continuing anyway."
    log_warn "Check logs: docker compose logs price-ingestion-service"
    break
  fi

  log_info "commodity_prices = ${PRICE_RECORDS} rows — still ingesting..."
  sleep 15
done

# ── Step 9: Trigger Open-Meteo weather backfill ───────────────────────────────
log_step "9/12  Triggering Open-Meteo historical weather backfill (ERA5, 1984–present)"
log_info "POST ${INGEST_URL}/api/v1/jobs/run-backfill-weather"
log_info "This runs in background — poll ${INGEST_URL}/api/v1/jobs/backfill-weather/<job_id> for progress."

WEATHER_BF_RESPONSE=$(curl -s -w "\n%{http_code}" \
  -X POST "${INGEST_URL}/api/v1/jobs/run-backfill-weather?start_year=1984" \
  -H "Content-Type: application/json" \
  --max-time 30 2>/dev/null)

WEATHER_BF_HTTP=$(echo "$WEATHER_BF_RESPONSE" | tail -n1)
WEATHER_BF_BODY=$(echo "$WEATHER_BF_RESPONSE" | head -n-1)

if [[ "$WEATHER_BF_HTTP" == "200" ]]; then
  WEATHER_JOB_ID=$(echo "$WEATHER_BF_BODY" | jq -r '.job_id' 2>/dev/null || echo "unknown")
  log_ok "Weather backfill started — job_id: ${WEATHER_JOB_ID}"
  log_info "Poll: ${INGEST_URL}/api/v1/jobs/backfill-weather/${WEATHER_JOB_ID}"
  log_info "Backfill runs in background (~10-30 min). Continuing to forecast step."
else
  log_warn "Weather backfill trigger returned HTTP ${WEATHER_BF_HTTP} — skipping."
  log_info "You can run it manually later: curl -X POST ${INGEST_URL}/api/v1/jobs/run-backfill-weather"
fi

# ── Step 10: Trigger forecast model training ──────────────────────────────────
log_step "10/12  Triggering forecast model training"
log_info "POST ${FORECAST_URL}/api/v1/jobs/run-forecast"

FORECAST_RESPONSE=$(curl -s -w "\n%{http_code}" \
  -X POST "${FORECAST_URL}/api/v1/jobs/run-forecast" \
  -H "Content-Type: application/json" \
  --max-time 30 2>/dev/null)

FORECAST_HTTP=$(echo "$FORECAST_RESPONSE" | tail -n1)
FORECAST_BODY=$(echo "$FORECAST_RESPONSE" | head -n-1)

if [[ "$FORECAST_HTTP" != "200" ]]; then
  die "Forecast trigger failed with HTTP ${FORECAST_HTTP}. Body: ${FORECAST_BODY}"
fi
log_ok "Forecast job triggered"
log_info "Response: $(echo "$FORECAST_BODY" | jq -c '.' 2>/dev/null || echo "$FORECAST_BODY")"

# ── Step 11: Wait for forecast to complete ────────────────────────────────────
log_step "11/12  Polling forecast completion (timeout: ${FORECAST_TIMEOUT}s)"
log_info "Forecast trains LSTM + Prophet per commodity — may take 2-5 minutes."

deadline=$(( $(date +%s) + FORECAST_TIMEOUT ))
FORECAST_RECORDS=0

while true; do
  COUNT_RESULT=$($COMPOSE exec -T postgres \
    psql -U krishiniti_app -d krishiniti -t -A \
    -c "SELECT COUNT(*) FROM forecasts;" 2>/dev/null || echo "0")

  FORECAST_RECORDS=$(echo "$COUNT_RESULT" | tr -d '[:space:]')

  if [[ "$FORECAST_RECORDS" =~ ^[0-9]+$ ]] && (( FORECAST_RECORDS > 0 )); then
    log_ok "Forecast complete — ${FORECAST_RECORDS} forecast records in DB"
    break
  fi

  if (( $(date +%s) > deadline )); then
    log_warn "Forecast timeout reached. forecasts count = ${FORECAST_RECORDS}. Continuing anyway."
    log_warn "Check logs: docker compose logs forecast-service"
    break
  fi

  log_info "forecasts = ${FORECAST_RECORDS} rows — still training..."
  sleep 10
done

# ── Step 12: Summary ──────────────────────────────────────────────────────────
log_step "12/12  Bootstrap summary"

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${BOLD}  KrishiNiti Bootstrap Complete${RESET}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""

# Database record counts
print_db_stat() {
  local label="$1"
  local table="$2"
  local count
  count=$($COMPOSE exec -T postgres \
    psql -U krishiniti_app -d krishiniti -t -A \
    -c "SELECT COUNT(*) FROM ${table};" 2>/dev/null | tr -d '[:space:]' || echo "error")
  printf "  %-30s %s\n" "${label}:" "${count} rows"
}

print_db_stat "commodity_prices"   "commodity_prices"
print_db_stat "forecast records"   "forecasts"

# Models trained (distinct model_name in forecasts)
MODELS_TRAINED=$($COMPOSE exec -T postgres \
  psql -U krishiniti_app -d krishiniti -t -A \
  -c "SELECT STRING_AGG(DISTINCT model_name, ', ' ORDER BY model_name) FROM forecasts;" \
  2>/dev/null | tr -d '[:space:]' || echo "none")

printf "  %-30s %s\n" "models trained:" "${MODELS_TRAINED:-none}"

# Commodities covered
COMMODITIES=$($COMPOSE exec -T postgres \
  psql -U krishiniti_app -d krishiniti -t -A \
  -c "SELECT STRING_AGG(DISTINCT commodity, ', ' ORDER BY commodity) FROM forecasts;" \
  2>/dev/null | tr -d '[:space:]' || echo "none")

printf "  %-30s %s\n" "commodities forecasted:" "${COMMODITIES:-none}"

echo ""
echo -e "${BOLD}  Service Endpoints:${RESET}"
printf "  %-30s %s\n" "Price Ingestion API:" "${INGEST_URL}/docs"
printf "  %-30s %s\n" "Weather Service API:" "${WEATHER_URL}/docs"
printf "  %-30s %s\n" "Forecast Service API:" "${FORECAST_URL}/docs"
printf "  %-30s %s\n" "Alert Service API:" "${ALERT_URL}/docs"
printf "  %-30s %s\n" "Farmer Service API:" "${FARMER_URL}/docs"
printf "  %-30s %s\n" "Analytics Service API:" "${ANALYTICS_URL}/docs"
echo ""
echo -e "${BOLD}  Next steps:${RESET}"
echo -e "  ${GREEN}*${RESET} Weather backfill running in background — poll job_id to check progress"
echo -e "  ${GREEN}*${RESET} After 30+ days of forecasts: run accuracy evaluation"
echo -e "    curl -X POST ${ANALYTICS_URL}/api/v1/accuracy/evaluate"
echo -e "  ${GREEN}*${RESET} Daily refresh: ./scripts/daily_refresh.sh"
echo ""
echo -e "${GREEN}${BOLD}  Stack is live. Run daily refresh with: ./scripts/daily_refresh.sh${RESET}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
