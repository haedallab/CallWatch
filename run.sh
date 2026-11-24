#!/usr/bin/env bash
# Local run: FastAPI on :8000 (Swagger /docs) + React (Vite) on :5173
set -e
cd "$(dirname "$0")"
(cd backend && uvicorn app.main:app --port 8000 --reload) &
API_PID=$!
trap "kill $API_PID" EXIT
cd web
[ -d node_modules ] || npm install
VITE_API_URL=${VITE_API_URL:-http://localhost:8000} npm run dev
