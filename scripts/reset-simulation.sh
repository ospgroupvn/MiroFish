#!/bin/bash
# Reset a simulation (clear state for retry)
# Usage: ./reset-simulation.sh <simulation_id>

if [ -z "$1" ]; then
    echo "Usage: $0 <simulation_id>"
    echo "Example: $0 sim_03cada64e77b"
    exit 1
fi

SIM_ID="$1"
BASE_URL="${API_BASE_URL:-http://localhost:3000}"

echo "Resetting simulation: $SIM_ID"
echo ""

RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/simulation/$SIM_ID/reset" \
  -H "Content-Type: application/json" \
  -d '{}')

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

echo "$BODY" | python3 -m json.tool 2>/dev/null || echo "$BODY"

if [ "$HTTP_CODE" -ge 200 ] && [ "$HTTP_CODE" -lt 300 ]; then
    echo ""
    echo "✓ Simulation reset successfully."
    echo "  You can now retry preparation from the UI."
else
    echo ""
    echo "✗ Reset failed with HTTP $HTTP_CODE"
    exit 1
fi
