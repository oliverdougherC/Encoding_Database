#!/usr/bin/env bash
set -euo pipefail

cd ~/Encoding_Database
git pull --rebase --autostash

# Rebuild images for changed services
docker compose -f docker-compose.prod.yml build server frontend

# Recreate containers for server and frontend
docker compose -f docker-compose.prod.yml up -d --no-deps --force-recreate server frontend

# Apply Prisma migrations (idempotent; server also runs this on startup)
docker compose -f docker-compose.prod.yml exec server npx prisma migrate deploy || true

# Wait for backend readiness via nginx proxy
echo "Waiting for backend readiness at http://localhost/health/ready ..."
for i in {1..30}; do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost/health/ready || true)
  if [ "$code" = "200" ]; then
    echo "Backend ready."
    break
  fi
  sleep 2
done

# Optionally check frontend
echo "Checking frontend at http://localhost ..."
curl -s -o /dev/null -w "Frontend HTTP %{http_code}\n" http://localhost || true

# Tail recent logs
docker compose -f docker-compose.prod.yml logs --tail=80 server