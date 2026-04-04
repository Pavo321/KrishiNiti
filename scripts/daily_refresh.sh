#!/usr/bin/env bash
# =============================================================================
# KrishiNiti — Daily Refresh Script
# =============================================================================
# Lightweight script intended to be called by a cron job or CI scheduler after
# the full bootstrap has already been run.
#
# What it does (in order):
#   1. Ingest latest prices  (price-ingestion-service)
#   2. Run forecast          (forecast-service)
#   3. Evaluate accuracy     (analytics-service)
#   4. Recompute weights     (analytics-service)
#
# Usage:
#   ./scripts/daily_refresh.sh
#
# Exit codes:
#   0  — all steps succeeded
#   1  — one or more steps failed (check output)
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
INGEST_URL="http://localhost:8001"
FORECAST_URL="http://localhost:8003"
ANALYTICS_URL="http://localhost:8006"

STEP_TIMEOUT=30   # seconds to wait for each trigger HTTP call
POLL_INTERVAL=10  # seconds between completion polls

ERRORS=0

# ── Pre-flight ────────────────────────────────────────────────────────────────
require_cmd curl
require_cmd jq

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${BOLD}  KrishiNiti Daily Refresh — $(date '+%Y-%m-%d %H:%M:%S %Z')${RESET}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"

# ── Helper: call an endpoint, check HTTP 200, pretty-print result ─────────────
# Usage: call_endpoint STEP_LABEL METHOD URL [body]
call_endpoint() {
  local label="$1"
  local method="$2"
  local url="$3"

  log_step "${label}"
  log_info "${method} ${url}"

  RESPONSE=$(curl -s -w "\n%{http_code}" \
    -X "$method" "$url" \
    -H "Content-Type: application/json" \
    --max-time "$STEP_TIMEOUT" 2>/dev/null) || {
    log_error "curl failed — is the service running?"
    ERRORS=$(( ERRORS + 1 ))
    return 1
  }

  HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
  BODY=$(echo "$RESPONSE" | head -n-1)

  if [[ "$HTTP_CODE" != "200" ]]; then
    log_error "HTTP ${HTTP_CODE} from ${url}"
    log_error "Body: ${BODY}"
    ERRORS=$(( ERRORS + 1 ))
    return 1
  fi

  log_ok "Success (HTTP 200)"
  echo "$BODY" | jq '.' 2>/dev/null || echo "  $BODY"
}

# ── Step 1: Price Ingestion ───────────────────────────────────────────────────
# Fetches latest Agmarknet + World Bank data and upserts into commodity_prices.
# The endpoint is synchronous — it returns after ingestion completes.
call_endpoint \
  "1/4  Price ingestion (Agmarknet + World Bank)" \
  "POST" \
  "${INGEST_URL}/api/v1/jobs/run-ingest" || true

# ── Step 2: Forecast ──────────────────────────────────────────────────────────
# Runs LSTM + Prophet ensemble, writes predictions to forecasts table.
# Synchronous — returns after training + prediction completes.
call_endpoint \
  "2/4  Forecast (LSTM + Prophet ensemble)" \
  "POST" \
  "${FORECAST_URL}/api/v1/jobs/run-forecast" || true

# ── Step 3: Accuracy evaluation ───────────────────────────────────────────────
# Evaluates all forecasts whose target_date has passed (accuracy_flag IS NULL).
# Compares predicted direction vs. actual WORLDBANK price — uses 3% threshold.
call_endpoint \
  "3/4  Accuracy evaluation (forecast vs. actuals)" \
  "POST" \
  "${ANALYTICS_URL}/api/v1/accuracy/evaluate" || true

# ── Step 4: Recompute ensemble weights ────────────────────────────────────────
# Reads last 60 days of evaluated forecasts, recomputes adaptive weights
# per commodity per model (floor: 0.10), writes to model_weights table.
call_endpoint \
  "4/4  Recompute ensemble weights (last 60 days)" \
  "POST" \
  "${ANALYTICS_URL}/api/v1/accuracy/compute-weights" || true

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"

if (( ERRORS == 0 )); then
  echo -e "${GREEN}${BOLD}  Daily refresh complete — all 4 steps succeeded.${RESET}"
else
  echo -e "${RED}${BOLD}  Daily refresh finished with ${ERRORS} error(s).${RESET}"
  echo -e "${RED}  Review output above and check service logs:${RESET}"
  echo -e "${RED}    docker compose logs --tail=50 <service-name>${RESET}"
fi

echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""

exit "$ERRORS"
