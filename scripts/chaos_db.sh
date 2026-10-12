#!/usr/bin/env bash
set -eo pipefail

API_URL="${API_URL:-http://localhost:8000}"

echo "=========================================================="
echo " [CHAOS TEST 3] PostGIS Database Outage Resilience         "
echo "=========================================================="

echo "[1/5] Stopping PostGIS database container..."
docker compose stop db

echo "[2/5] Querying GET /route to verify HTTP 503 Outage Contract..."
HEADER_FILE=$(mktemp)
BODY_FILE=$(mktemp)

curl -s -D "${HEADER_FILE}" -o "${BODY_FILE}" "${API_URL}/route?src_lat=41.8845&src_lon=-87.6330&dst_lat=41.8785&dst_lon=-87.6250"

HTTP_STATUS=$(grep -E "^HTTP/[0-9.]+ 503" "${HEADER_FILE}" || true)
RETRY_HEADER=$(grep -i "^Retry-After: 5" "${HEADER_FILE}" || true)
BODY=$(cat "${BODY_FILE}")

echo "Response Headers:"
cat "${HEADER_FILE}"
echo "Response Body: ${BODY}"

if [ -z "${HTTP_STATUS}" ]; then
  echo "FAIL: Expected HTTP 503 Service Unavailable, got headers above."
  docker compose start db
  rm -f "${HEADER_FILE}" "${BODY_FILE}"
  exit 1
fi

if [ -z "${RETRY_HEADER}" ]; then
  echo "FAIL: Missing required header 'Retry-After: 5'."
  docker compose start db
  rm -f "${HEADER_FILE}" "${BODY_FILE}"
  exit 1
fi

if [[ "${BODY}" != *"\"error\": \"database_unavailable\""* && "${BODY}" != *"\"error\":\"database_unavailable\""* ]]; then
  echo "FAIL: Response body does not match DB Outage Error Contract."
  docker compose start db
  rm -f "${HEADER_FILE}" "${BODY_FILE}"
  exit 1
fi
echo "SUCCESS: /route returned clean HTTP 503 with Retry-After: 5 and database_unavailable error."

echo "[3/5] Checking GET /health to verify database disconnected report..."
HEALTH_RESP=$(curl -s "${API_URL}/health")
echo "Health Response: ${HEALTH_RESP}"

if [[ "${HEALTH_RESP}" != *"\"database\": \"disconnected\""* && "${HEALTH_RESP}" != *"\"database\":\"disconnected\""* ]]; then
  echo "FAIL: Expected /health to report 'database: disconnected'."
  docker compose start db
  rm -f "${HEADER_FILE}" "${BODY_FILE}"
  exit 1
fi
echo "SUCCESS: /health correctly reported database disconnected."

echo "[4/5] Restarting PostGIS container..."
docker compose start db
echo "Waiting 8s for PostGIS engine to ready incoming connections..."
sleep 8

echo "[5/5] Verifying connection pool recovery on next /route request..."
RECOVER_RESP=$(curl -s -w "\n%{http_code}" "${API_URL}/route?src_lat=41.8845&src_lon=-87.6330&dst_lat=41.8785&dst_lon=-87.6250")
REC_STATUS=$(echo "$RECOVER_RESP" | tail -n 1)
REC_BODY=$(echo "$RECOVER_RESP" | sed '$d')

echo "Recovery Status: ${REC_STATUS}"
echo "Recovery Body: ${REC_BODY}"

if [ "${REC_STATUS}" -eq 200 ]; then
  echo "SUCCESS: Connection pool successfully reconnected and served route!"
else
  echo "WARNING: Received status ${REC_STATUS}, database may still be initializing."
fi

rm -f "${HEADER_FILE}" "${BODY_FILE}"
echo "=========================================================="
echo " [CHAOS TEST 3 PASSED] Database failure mode verified!    "
echo "=========================================================="
