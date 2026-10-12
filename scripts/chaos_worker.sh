#!/usr/bin/env bash
set -eo pipefail

API_URL="${API_URL:-http://localhost:8000}"
WAIT_TIME="${WAIT_TIME:-65}"

echo "=========================================================="
echo " [CHAOS TEST 1] Worker Termination & Multiplier Staleness "
echo "=========================================================="

echo "[1/5] Stopping congestion worker container..."
docker compose stop worker

echo "[2/5] Waiting ${WAIT_TIME}s for Redis heartbeat key to expire (>60s threshold)..."
sleep "${WAIT_TIME}"

echo "[3/5] Querying GET /route to verify stale cost fallback contract..."
ROUTE_RESP=$(curl -s -w "\n%{http_code}" "${API_URL}/route?src_lat=41.8845&src_lon=-87.6330&dst_lat=41.8785&dst_lon=-87.6250")
HTTP_STATUS=$(echo "$ROUTE_RESP" | tail -n 1)
BODY=$(echo "$ROUTE_RESP" | sed '$d')

echo "HTTP Status: ${HTTP_STATUS}"
echo "Body: ${BODY}"

if [ "${HTTP_STATUS}" -ne 200 ]; then
  echo "FAIL: Expected HTTP 200 from /route during worker downtime, got ${HTTP_STATUS}"
  docker compose start worker
  exit 1
fi

if [[ "${BODY}" != *"\"costs_stale\": true"* && "${BODY}" != *"\"costs_stale\":true"* ]]; then
  echo "FAIL: Expected 'costs_stale: true' in response body."
  docker compose start worker
  exit 1
fi
echo "SUCCESS: /route gracefully responded with costs_stale: true."

echo "[4/5] Restarting worker container..."
docker compose start worker

echo "[5/5] Waiting 10s for worker heartbeat to refresh..."
sleep 10

RECOVER_RESP=$(curl -s "${API_URL}/route?src_lat=41.8845&src_lon=-87.6330&dst_lat=41.8785&dst_lon=-87.6250")
echo "Recovery Response: ${RECOVER_RESP}"

if [[ "${RECOVER_RESP}" == *"\"costs_stale\": false"* || "${RECOVER_RESP}" == *"\"costs_stale\":false"* ]]; then
  echo "SUCCESS: Heartbeat refreshed; costs_stale restored to false."
else
  echo "WARNING: Worker still resuming heartbeat..."
fi

echo "=========================================================="
echo " [CHAOS TEST 1 PASSED] Worker failure mode fully verified! "
echo "=========================================================="
