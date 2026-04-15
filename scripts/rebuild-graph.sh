#!/bin/bash
# Rebuild graph for a project (force rebuild)
# Usage: ./rebuild-graph.sh <project_id>

if [ -z "$1" ]; then
    echo "Usage: $0 <project_id>"
    echo "Example: $0 proj_a39214a21f50"
    exit 1
fi

PROJECT_ID="$1"
BASE_URL="${API_BASE_URL:-http://localhost:3000}"

echo "Rebuilding graph for project: $PROJECT_ID"
echo "API endpoint: $BASE_URL/api/graph/build"
echo ""

RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/graph/build" \
  -H "Content-Type: application/json" \
  -d "{\"project_id\": \"$PROJECT_ID\", \"force\": true}")

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

echo "$BODY" | python3 -m json.tool 2>/dev/null || echo "$BODY"

if [ "$HTTP_CODE" -ge 200 ] && [ "$HTTP_CODE" -lt 300 ]; then
    echo ""
    echo "✓ Graph rebuild task started successfully."
    echo "  Query progress via: $BASE_URL/api/task/<task_id>"
else
    echo ""
    echo "✗ Rebuild failed with HTTP $HTTP_CODE"
    exit 1
fi
